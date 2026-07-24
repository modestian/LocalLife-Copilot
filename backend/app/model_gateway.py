import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import Literal

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    StoppingCriteria,
    StoppingCriteriaList,
)
from transformers import pipeline as hf_pipeline

from app.analytics import SentimentAnalyzer, SentimentResult

logger = logging.getLogger(__name__)
analyzer = SentimentAnalyzer()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


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
    device: str | None


class EmbeddingRequest(BaseModel):
    model: str
    input: list[str]


class EmbeddingItem(BaseModel):
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    model: str
    data: list[EmbeddingItem]


class GenerationRequest(BaseModel):
    model: str = Field(default="local-llm", max_length=128)
    messages: list[dict[str, str]] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    stop: list[str] = Field(default_factory=list, max_length=8)


class GenerationResponse(BaseModel):
    model: str
    text: str
    finish_reason: Literal["stop", "length", "stop_token", "timeout"]
    usage: dict[str, int]


class ClassificationRequest(BaseModel):
    model: str = Field(default="local-bert-classifier", max_length=128)
    input: str = Field(min_length=1, max_length=2000)
    candidate_labels: list[str] = Field(
        default=["knowledge_query", "tool_use", "general_chat"], max_length=20
    )
    return_all_scores: bool = True


class ClassificationItem(BaseModel):
    label: str
    score: float


class ClassificationResponse(BaseModel):
    model: str
    predicted_label: str
    scores: list[ClassificationItem]


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------

_embedding_model: SentenceTransformer | None = None
_embedding_model_name: str = ""

_generation_model: AutoModelForCausalLM | None = None
_generation_tokenizer: AutoTokenizer | None = None
_generation_model_name: str = ""

_classifier_pipeline = None
_classifier_model_name: str = ""


def _get_classifier():
    global _classifier_pipeline, _classifier_model_name
    name = os.getenv(
        "CLASSIFIER_MODEL_NAME",
        "D:/CodingProjects/LocalLife Copilot/backend/training/output/final_model",
    )
    if _classifier_pipeline is None or _classifier_model_name != name:
        logger.info("Loading classification model %s on %s", name, _device())
        _classifier_pipeline = hf_pipeline(
            "text-classification",
            model=name,
            tokenizer=name,
            device=0 if _device() == "cuda" else -1,
            top_k=None,
        )
        _classifier_model_name = name
    return _classifier_pipeline


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model, _embedding_model_name
    name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
    if _embedding_model is None or _embedding_model_name != name:
        logger.info("Loading embedding model %s on %s", name, _device())
        _embedding_model = SentenceTransformer(name, device=_device(), trust_remote_code=True)
        _embedding_model_name = name
    return _embedding_model


def _get_generation_model() -> tuple[AutoModelForCausalLM, AutoTokenizer]:
    global _generation_model, _generation_tokenizer, _generation_model_name
    name = os.getenv("GENERATION_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
    if _generation_model is None or _generation_model_name != name:
        logger.info("Loading generation model %s on %s", name, _device())
        tokenizer = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model_kwargs: dict[str, object] = {
            "trust_remote_code": True,
            "torch_dtype": torch.float16 if _device() == "cuda" else torch.float32,
        }
        if _device() == "cuda":
            model_kwargs["device_map"] = "auto"
        _generation_model = AutoModelForCausalLM.from_pretrained(name, **model_kwargs)
        if _device() == "cpu":
            _generation_model = _generation_model.to(_device())
        _generation_tokenizer = tokenizer
        _generation_model_name = name
        _generation_model.eval()
    return _generation_model, _generation_tokenizer


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm models on startup so the first request is fast."""
    try:
        _get_embedding_model()
        logger.info("Embedding model ready")
    except Exception:
        logger.warning("Embedding model not available at startup; will retry on first request")
    try:
        _get_generation_model()
        logger.info("Generation model ready")
    except Exception:
        logger.warning("Generation model not available at startup; will retry on first request")
    try:
        _get_classifier()
        logger.info("Classifier model ready")
    except Exception:
        logger.warning("Classifier model not available at startup; will retry on first request")
    yield


app = FastAPI(title="Model Gateway", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="alive")


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Classification — BERT-based intent & constraint routing
# ---------------------------------------------------------------------------


@app.post("/v1/classify", response_model=ClassificationResponse)
async def classify(payload: ClassificationRequest) -> ClassificationResponse:
    """Classify user query into intent/constraint categories using local BERT."""
    try:
        pipeline = _get_classifier()
        results = pipeline(payload.input, top_k=None)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Classifier unavailable: {exc!s}") from exc
    if not results or not isinstance(results, list) or not results[0]:
        raise HTTPException(status_code=500, detail="Classifier returned no results")
    scores = {}
    for item in results[0]:
        label = str(item.get("label", "unknown")).strip()
        score = float(item.get("score", 0.0))
        scores[label] = score
    predicted = max(scores, key=scores.get) if scores else "unknown"
    pipeline_name = os.getenv(
        "CLASSIFIER_MODEL_NAME",
        "D:/CodingProjects/LocalLife Copilot/backend/training/output/final_model",
    )
    return ClassificationResponse(
        model=payload.model or pipeline_name,
        predicted_label=predicted,
        scores=scores,
    )


@app.get("/v1/models/classifier", response_model=ModelInfoResponse)
async def classifier_model_info() -> ModelInfoResponse:
    name = os.getenv(
        "CLASSIFIER_MODEL_NAME",
        "D:/CodingProjects/LocalLife Copilot/backend/training/output/final_model",
    )
    return ModelInfoResponse(model_name=name, version=name, device=_device())


# ---------------------------------------------------------------------------
# Embeddings — real semantic vectors via sentence-transformers
# ---------------------------------------------------------------------------


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def embeddings(payload: EmbeddingRequest) -> EmbeddingResponse:
    """Return dense semantic embeddings for hybrid search."""
    if not payload.input:
        return EmbeddingResponse(model=payload.model, data=[])
    try:
        model = _get_embedding_model()
        raw = model.encode(payload.input, normalize_embeddings=True, show_progress_bar=False)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Embedding model inference failed: {exc!s}"
        ) from exc

    return EmbeddingResponse(
        model=payload.model,
        data=[
            EmbeddingItem(index=idx, embedding=vector.tolist()) for idx, vector in enumerate(raw)
        ],
    )


@app.get("/v1/models/embeddings", response_model=ModelInfoResponse)
async def embedding_model_info() -> ModelInfoResponse:
    name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
    return ModelInfoResponse(model_name=name, version=name, device=_device())


# ---------------------------------------------------------------------------
# Text generation — used by GroundedRAGGenerator and intent/constraint nodes
# ---------------------------------------------------------------------------


class _EOSStoppingCriteria(StoppingCriteria):
    def __init__(self, stop_ids: list[list[int]]) -> None:
        super().__init__()
        self._stop_sequences = stop_ids

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> bool:  # type: ignore[override]
        for stop_ids in self._stop_sequences:
            if len(stop_ids) > input_ids.shape[1]:
                continue
            if torch.equal(input_ids[0, -len(stop_ids) :], torch.tensor(stop_ids)):
                return True
        return False


@app.post("/v1/generate", response_model=GenerationResponse)
async def generate(payload: GenerationRequest) -> GenerationResponse:
    """Generate grounded text for RAG, intent classification, and constraint extraction."""
    if not payload.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    try:
        model, tokenizer = _get_generation_model()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Generation model unavailable: {exc!s}"
        ) from exc

    text = tokenizer.apply_chat_template(
        payload.messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    stop_ids: list[list[int]] = []
    for token in payload.stop:
        stop_ids.append(tokenizer.encode(token, add_special_tokens=False))

    stopping: StoppingCriteriaList | None = (
        StoppingCriteriaList([_EOSStoppingCriteria(stop_ids)]) if stop_ids else None
    )

    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=payload.max_tokens,
            temperature=payload.temperature,
            top_p=payload.top_p,
            do_sample=payload.temperature > 0,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            stopping_criteria=stopping,
        )

    generated_ids = outputs[0][inputs["input_ids"].shape[1] :]
    answer = tokenizer.decode(generated_ids, skip_special_tokens=True)

    finish_reason: Literal["stop", "length", "stop_token", "timeout"] = (
        "length" if len(generated_ids) >= payload.max_tokens else "stop"
    )

    return GenerationResponse(
        model=payload.model,
        text=answer,
        finish_reason=finish_reason,
        usage={
            "prompt_tokens": int(inputs["input_ids"].shape[1]),
            "completion_tokens": int(len(generated_ids)),
        },
    )
