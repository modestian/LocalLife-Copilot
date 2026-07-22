from collections.abc import Awaitable, Callable
from typing import Any

from app.application.login_rate_limit import LoginRateLimit


class RedisLoginRateLimiter:
    _RECORD_FAILURE_SCRIPT = """
local attempts = redis.call('INCR', KEYS[1])
if attempts == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {attempts, ttl}
"""

    def __init__(self, redis_client: Any, max_attempts: int, window_seconds: int) -> None:
        self.redis = redis_client
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._record_failure: Callable[..., Awaitable[list[int]]] = redis_client.register_script(
            self._RECORD_FAILURE_SCRIPT
        )

    async def status(self, subject: str) -> LoginRateLimit:
        attempts = await self.redis.get(subject)
        if attempts is None:
            return LoginRateLimit(False, 0)
        ttl = int(await self.redis.ttl(subject))
        return LoginRateLimit(
            int(attempts) >= self.max_attempts,
            max(1, ttl) if ttl > 0 else self.window_seconds,
        )

    async def record_failure(self, subject: str) -> LoginRateLimit:
        attempts, ttl = await self._record_failure(keys=[subject], args=[self.window_seconds])
        return LoginRateLimit(
            int(attempts) >= self.max_attempts,
            max(1, int(ttl)) if int(ttl) > 0 else self.window_seconds,
        )

    async def reset(self, subject: str) -> None:
        await self.redis.delete(subject)
