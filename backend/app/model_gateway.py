import hashlib
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import get_settings

app = FastAPI(title="Local development model gateway", version="0.1.0")


class LiveResponse(BaseModel):
    status: Literal["alive"]


class EmbeddingRequest(BaseModel):
    model: str
    input: list[str]


class EmbeddingItem(BaseModel):
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    model: str
    data: list[EmbeddingItem]


@app.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Local deterministic gateway contract; replace its URL for a real model runtime."""
    return LiveResponse(status="alive")


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def embeddings(payload: EmbeddingRequest) -> EmbeddingResponse:
    """Return deterministic local vectors behind the production gateway contract."""
    settings = get_settings()
    return EmbeddingResponse(
        model=payload.model,
        data=[
            EmbeddingItem(
                index=index,
                embedding=_deterministic_vector(text, settings.embedding_dimension),
            )
            for index, text in enumerate(payload.input)
        ],
    )


def _deterministic_vector(text: str, dimension: int) -> list[float]:
    seed = text.encode("utf-8")
    values: list[float] = []
    for offset in range(dimension):
        digest = hashlib.sha256(seed + offset.to_bytes(4, "big")).digest()
        values.append(int.from_bytes(digest[:4], "big") / (2**31) - 1.0)
    return values
