from redis import Redis

INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIREAT', KEYS[1], ARGV[1])
end
return count
"""


class RedisCounterStore:
    def __init__(self, client: Redis):
        self.client = client

    def check_ready(self) -> None:
        self.client.ping()

    def increment(self, key: str, expires_at: int) -> int:
        return self.client.eval(INCREMENT_WITH_EXPIRY, 1, key, expires_at)
