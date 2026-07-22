import pytest

from app.application.login_rate_limit import (
    InMemoryLoginRateLimiter,
    login_rate_limit_subject,
)
from app.infrastructure.cache.login_rate_limit import RedisLoginRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def register_script(self, script: str):
        assert "INCR" in script

        async def execute(*, keys: list[str], args: list[int]) -> list[int]:
            key = keys[0]
            self.values[key] = self.values.get(key, 0) + 1
            self.ttls.setdefault(key, args[0])
            return [self.values[key], self.ttls[key]]

        return execute

    async def get(self, key: str) -> int | None:
        return self.values.get(key)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)


def test_login_rate_limit_subject_is_normalized_and_contains_no_raw_identity() -> None:
    first = login_rate_limit_subject(" Operator01 ", "192.0.2.10")
    second = login_rate_limit_subject("operator01", "192.0.2.10")

    assert first == second
    assert first.startswith("rate:login:")
    assert "operator01" not in first
    assert "192.0.2.10" not in first


@pytest.mark.asyncio
async def test_in_memory_login_rate_limiter_counts_and_resets() -> None:
    limiter = InMemoryLoginRateLimiter(max_attempts=2, window_seconds=30)

    assert not (await limiter.status("subject")).blocked
    assert not (await limiter.record_failure("subject")).blocked
    assert (await limiter.record_failure("subject")).blocked
    assert (await limiter.status("subject")).blocked

    await limiter.reset("subject")
    assert not (await limiter.status("subject")).blocked


@pytest.mark.asyncio
async def test_redis_login_rate_limiter_uses_atomic_counter_and_ttl() -> None:
    redis = FakeRedis()
    limiter = RedisLoginRateLimiter(redis, max_attempts=2, window_seconds=45)

    assert not (await limiter.record_failure("rate:login:digest")).blocked
    blocked = await limiter.record_failure("rate:login:digest")

    assert blocked.blocked
    assert blocked.retry_after_seconds == 45
    assert (await limiter.status("rate:login:digest")).blocked
    await limiter.reset("rate:login:digest")
    assert not (await limiter.status("rate:login:digest")).blocked
