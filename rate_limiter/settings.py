from dataclasses import dataclass, field
from os import environ


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
    mongodb_uri: str = field(default="mongodb://127.0.0.1:27017", repr=False)
    mongodb_database: str = "rate_limiter"
    requests_per_window: int = 5
    window_seconds: int = 60
    mongodb_timeout_ms: int = 2_000

    @classmethod
    def from_env(cls) -> "Settings":
        uri = environ.get("MONGODB_URI", cls.mongodb_uri)
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URI must be a MongoDB connection URI.")

        return cls(
            mongodb_uri=uri,
            mongodb_database=environ.get("MONGODB_DATABASE", cls.mongodb_database),
            requests_per_window=positive_setting("RATE_LIMIT_REQUESTS", cls.requests_per_window),
            window_seconds=positive_setting("RATE_LIMIT_WINDOW_SECONDS", cls.window_seconds),
            mongodb_timeout_ms=positive_setting("MONGODB_TIMEOUT_MS", cls.mongodb_timeout_ms),
        )
