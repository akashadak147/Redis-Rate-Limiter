from dataclasses import dataclass, field
from os import environ
from re import fullmatch


def positive_setting(name: str, default: int) -> int:
    message = f"{name} must be an integer between 1 and 2147483647."
    try:
        value = int(environ.get(name, str(default)))
    except ValueError:
        raise ValueError(message) from None
    if not 1 <= value <= 2_147_483_647:
        raise ValueError(message)
    return value


@dataclass(frozen=True)
class Settings:
    redis_url: str = field(default="redis://127.0.0.1:6379/0", repr=False)
    redis_key_prefix: str = "rate-limit"
    requests_per_window: int = 5
    window_seconds: int = 60
    redis_timeout_ms: int = 2_000

    @classmethod
    def from_env(cls) -> "Settings":
        url = environ.get("REDIS_URL", cls.redis_url)
        if not url.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("REDIS_URL must be a Redis connection URL.")

        prefix = environ.get("REDIS_KEY_PREFIX", cls.redis_key_prefix)
        if not fullmatch(r"[A-Za-z0-9_-]{1,64}", prefix):
            raise ValueError("REDIS_KEY_PREFIX must use 1 to 64 ASCII letters, digits, hyphens or underscores.")

        return cls(
            redis_url=url,
            redis_key_prefix=prefix,
            requests_per_window=positive_setting("RATE_LIMIT_REQUESTS", cls.requests_per_window),
            window_seconds=positive_setting("RATE_LIMIT_WINDOW_SECONDS", cls.window_seconds),
            redis_timeout_ms=positive_setting("REDIS_TIMEOUT_MS", cls.redis_timeout_ms),
        )
