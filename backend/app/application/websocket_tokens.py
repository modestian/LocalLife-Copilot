"""Short-lived, single-use credentials for WebSocket handshakes."""

from __future__ import annotations

from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID


class WebSocketTokenStore(Protocol):
    async def set(self, name: str, value: str, *, ex: int, nx: bool) -> object: ...

    async def getdel(self, name: str) -> str | None: ...


class InvalidWebSocketToken(ValueError):
    """Raised when a handshake credential is expired, reused, or unknown."""


class WebSocketTokenService:
    PREFIX = "wst_"
    KEY_PREFIX = "auth:ws-token:"

    def __init__(self, store: WebSocketTokenStore, *, ttl_seconds: int = 60) -> None:
        if not 1 <= ttl_seconds <= 300:
            raise ValueError("WebSocket token TTL must be between 1 and 300 seconds")
        self._store = store
        self.ttl_seconds = ttl_seconds

    async def issue(self, user_id: UUID) -> str:
        for _attempt in range(3):
            token = f"{self.PREFIX}{token_urlsafe(48)}"
            stored = await self._store.set(
                self._key(token), str(user_id), ex=self.ttl_seconds, nx=True
            )
            if stored:
                return token
        raise RuntimeError("failed to allocate a unique WebSocket token")

    async def consume(self, token: str) -> UUID:
        if not token.startswith(self.PREFIX) or len(token) > 256:
            raise InvalidWebSocketToken("invalid WebSocket token")
        raw_user_id = await self._store.getdel(self._key(token))
        if raw_user_id is None:
            raise InvalidWebSocketToken("expired or already consumed WebSocket token")
        try:
            return UUID(raw_user_id)
        except (TypeError, ValueError) as exc:
            raise InvalidWebSocketToken("invalid WebSocket token subject") from exc

    @classmethod
    def _key(cls, token: str) -> str:
        digest = sha256(token.encode("utf-8")).hexdigest()
        return f"{cls.KEY_PREFIX}{digest}"
