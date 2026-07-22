import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LoginRateLimit:
    blocked: bool
    retry_after_seconds: int


class LoginRateLimiter(Protocol):
    async def status(self, subject: str) -> LoginRateLimit: ...

    async def record_failure(self, subject: str) -> LoginRateLimit: ...

    async def reset(self, subject: str) -> None: ...


def login_rate_limit_subject(username: str, client_ip: str) -> str:
    """Return a stable key without retaining raw usernames or IP addresses."""
    normalized = username.strip().casefold()
    digest = hashlib.sha256(f"{normalized}\0{client_ip}".encode()).hexdigest()
    return f"rate:login:{digest}"


class InMemoryLoginRateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def status(self, subject: str) -> LoginRateLimit:
        async with self._lock:
            return self._status(subject, time.monotonic())

    async def record_failure(self, subject: str) -> LoginRateLimit:
        async with self._lock:
            now = time.monotonic()
            current = self._status(subject, now)
            if current.blocked:
                return current
            attempts, deadline = self._attempts.get(subject, (0, now + self.window_seconds))
            attempts += 1
            self._attempts[subject] = (attempts, deadline)
            retry_after = max(1, int(deadline - now + 0.999))
            return LoginRateLimit(attempts >= self.max_attempts, retry_after)

    async def reset(self, subject: str) -> None:
        async with self._lock:
            self._attempts.pop(subject, None)

    def _status(self, subject: str, now: float) -> LoginRateLimit:
        entry = self._attempts.get(subject)
        if entry is None:
            return LoginRateLimit(False, 0)
        attempts, deadline = entry
        if deadline <= now:
            self._attempts.pop(subject, None)
            return LoginRateLimit(False, 0)
        retry_after = max(1, int(deadline - now + 0.999))
        return LoginRateLimit(attempts >= self.max_attempts, retry_after)
