from uuid import UUID

import pytest

from app.application.websocket_tokens import InvalidWebSocketToken, WebSocketTokenService


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, name: str, value: str, *, ex: int, nx: bool) -> bool:
        assert ex == 60
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    async def getdel(self, name: str) -> str | None:
        return self.values.pop(name, None)


async def test_websocket_token_is_opaque_and_single_use() -> None:
    service = WebSocketTokenService(MemoryStore())
    user_id = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125")

    token = await service.issue(user_id)

    assert token.startswith("wst_")
    assert str(user_id) not in token
    assert await service.consume(token) == user_id
    with pytest.raises(InvalidWebSocketToken):
        await service.consume(token)
