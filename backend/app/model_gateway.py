import hashlib
import traceback

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.analytics.sentiment_classifier import SentimentAnalyzer, SentimentResult
from app.core.config import get_settings

app = FastAPI(title="Model Gateway", version="0.1.0")

analyzer = SentimentAnalyzer()


class LiveResponse(BaseModel):
    status: Literal["alive"]


class BatchRequest(BaseModel):
    reviews: list[str]


class BatchResponse(BaseModel):
    results: list[SentimentResult]
    model_version: str


class ModelInfoResponse(BaseModel):
    model_name: str
    version: str
    device: str


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
    return LiveResponse(status="alive")


@app.post("/v1/sentiment/batch", response_model=BatchResponse)
async def batch_sentiment(request: BatchRequest) -> BatchResponse:
    if not request.reviews:
        return BatchResponse(results=[], model_version=analyzer.version)

    try:
        results = analyzer.analyze_batch(request.reviews)
        return BatchResponse(results=results, model_version=analyzer.version)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Model inference failed: {e!s}") from e


@app.get("/v1/models/sentiment", response_model=ModelInfoResponse)
async def get_model_info() -> ModelInfoResponse:
    return ModelInfoResponse(
        model_name=analyzer.classifier.model_name,
        version=analyzer.version,
        device=analyzer.classifier._device,
    )


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
