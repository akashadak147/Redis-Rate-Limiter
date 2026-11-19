import logging
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from math import ceil
from typing import Any

import pymongo
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, InvalidName, InvalidURI, PyMongoError

from rate_limiter.limiter import FixedWindowLimiter
from rate_limiter.settings import Settings
from rate_limiter.store import MongoCounterStore

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
            client: MongoClient[dict[str, Any]] = MongoClient(
                config.mongodb_uri,
                timeoutMS=config.mongodb_timeout_ms,
                retryWrites=False,
                connect=False,
                tz_aware=True,
            )
        except (InvalidURI, ConfigurationError, ValueError):
            raise ValueError("Invalid MongoDB connection settings.") from None

        with client:
            try:
                store = MongoCounterStore(client, config.mongodb_database)
            except InvalidName:
                raise ValueError("Invalid MONGODB_DATABASE name.") from None

            instance.state.store = store
            instance.state.limiter = FixedWindowLimiter(config, store, clock)
            instance.state.timeout_seconds = config.mongodb_timeout_ms / 1_000
            try:
                await run_in_threadpool(store.ensure_index)
            except PyMongoError as exc:
                logger.warning("MongoDB counter index setup deferred (%s).", type(exc).__name__)
            yield

    app = FastAPI(title="MongoDB Rate Limiter", version="1.0.0", lifespan=lifespan)

    @app.get("/health", responses={503: {"description": "MongoDB unavailable"}})
    def health(request: Request) -> JSONResponse:
        try:
            with pymongo.timeout(request.app.state.timeout_seconds):
                request.app.state.store.check_ready()
        except PyMongoError as exc:
            logger.warning("MongoDB readiness check failed (%s).", type(exc).__name__)
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
            with pymongo.timeout(request.app.state.timeout_seconds):
                decision = request.app.state.limiter.consume(client_ids[0])
        except PyMongoError as exc:
            logger.warning("MongoDB quota check failed (%s).", type(exc).__name__)
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
