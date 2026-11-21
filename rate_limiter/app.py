import logging
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from math import ceil

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from rate_limiter.limiter import FixedWindowLimiter
from rate_limiter.settings import Settings
from rate_limiter.store import RedisCounterStore

logger = logging.getLogger(__name__)
CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
NO_STORE = {"Cache-Control": "no-store"}

CLIENT_ID_PARAMETER = {
    "name": "X-Client-ID",
    "in": "header",
    "required": True,
    "description": "Case-sensitive client identifier for the local demo.",
    "schema": {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": "^[A-Za-z0-9_-]+$",
        "example": "client-a",
    },
}


def create_app(settings: Settings | None = None, *, clock: Callable[[], float] = time.time) -> FastAPI:
    @asynccontextmanager
    async def lifespan(instance: FastAPI):
        config = settings if settings is not None else Settings.from_env()
        try:
            timeout_seconds = config.redis_timeout_ms / 1_000
            client = Redis.from_url(
                config.redis_url,
                socket_timeout=timeout_seconds,
                socket_connect_timeout=timeout_seconds,
                # A lost reply could follow a successful increment.
                retry=Retry(NoBackoff(), 0),
            )
        except ValueError:
            raise ValueError("Invalid REDIS_URL connection settings.") from None

        with client:
            store = RedisCounterStore(client)
            instance.state.store = store
            instance.state.limiter = FixedWindowLimiter(config, store, clock)
            yield

    app = FastAPI(title="Redis Rate Limiter", version="1.0.0", lifespan=lifespan)

    @app.get("/health", responses={503: {"description": "Redis unavailable"}})
    def health(request: Request) -> JSONResponse:
        try:
            request.app.state.store.check_ready()
        except RedisError as exc:
            logger.warning("Redis readiness check failed (%s).", type(exc).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503, headers=NO_STORE)
        return JSONResponse({"status": "ready"}, headers=NO_STORE)

    def require_quota(request: Request, response: Response) -> None:
        client_ids = request.headers.getlist("x-client-id")
        if len(client_ids) != 1 or not CLIENT_ID.fullmatch(client_ids[0]):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_client_id",
                    "message": "Send one X-Client-ID with 1 to 64 ASCII letters, digits, hyphens or underscores.",
                },
                headers=NO_STORE,
            )

        try:
            decision = request.app.state.limiter.consume(client_ids[0])
        except RedisError as exc:
            logger.warning("Redis quota check failed (%s).", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail={"error": "quota_unavailable", "message": "Quota could not be checked."},
                headers=NO_STORE,
            ) from None

        headers = {
            **NO_STORE,
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_at),
        }
        if decision.allowed:
            response.headers.update(headers)
            return

        logger.warning("Request refused because the rate limit was exceeded.")
        headers["Retry-After"] = str(max(1, ceil(decision.reset_at - clock())))
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded", "message": "Try again after the current window."},
            headers=headers,
        )

    @app.get(
        "/api/demo",
        dependencies=[Depends(require_quota)],
        openapi_extra={"parameters": [CLIENT_ID_PARAMETER]},
        responses={
            400: {"description": "Invalid client identifier"},
            429: {"description": "Too many requests in this window"},
            503: {"description": "Quota could not be checked"},
        },
    )
    def demo() -> dict[str, str]:
        return {"message": "Protected endpoint reached."}

    return app


app = create_app()
