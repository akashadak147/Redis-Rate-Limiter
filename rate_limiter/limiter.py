from collections.abc import Callable
from dataclasses import dataclass
from math import floor

from rate_limiter.settings import Settings
from rate_limiter.store import RedisCounterStore

EXPIRY_GRACE_SECONDS = 60


@dataclass(frozen=True)
class Decision:
    count: int
    limit: int
    reset_at: int

    @property
    def allowed(self) -> bool:
        return self.count <= self.limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.count)


class FixedWindowLimiter:
    def __init__(self, settings: Settings, store: RedisCounterStore, clock: Callable[[], float]):
        self.limit = settings.requests_per_window
        self.duration = settings.window_seconds
        self.policy_key = f"{settings.redis_key_prefix}:demo-v1:{self.limit}:{self.duration}"
        self.store = store
        self.clock = clock

    def consume(self, client_id: str) -> Decision:
        now = floor(self.clock())
        window_start = now - now % self.duration
        window_end = window_start + self.duration
        key = f"{self.policy_key}:{client_id}:{window_start}"
        expires_at = window_end + EXPIRY_GRACE_SECONDS
        count = self.store.increment(key, expires_at)
        return Decision(count=count, limit=self.limit, reset_at=window_end)
