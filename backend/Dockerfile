ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.13.14-slim
FROM ${PYTHON_IMAGE} AS base

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# Install core project dependencies only (no torch/transformers).
COPY pyproject.toml ./
RUN mkdir -p app \
    && touch app/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf app

# Pre-download the embedding model into the image so no network is needed at runtime.
# BAAI/bge-small-zh-v1.5 is MIT-licensed, ~130 MB, 512-dim Chinese-optimized.

FROM base AS model

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG EMBEDDING_MODEL_ID=BAAI/bge-small-zh-v1.5
ARG EMBEDDING_MODEL_DIR=/models/embedding-cache/bge-small-zh-v1.5

# Model stage: torch + transformers + sentence-transformers.
# Only used by model-gateway; other services build from base directly.
RUN pip install --no-cache-dir --index-url ${TORCH_INDEX_URL} torch \
    && pip install --no-cache-dir ".[model]"
ENV SENTENCE_TRANSFORMERS_HOME=/models/embedding-cache
RUN mkdir -p "${EMBEDDING_MODEL_DIR}" \
    && python -c "from huggingface_hub import snapshot_download; from sentence_transformers import SentenceTransformer; model_dir = snapshot_download(repo_id='${EMBEDDING_MODEL_ID}', local_dir='${EMBEDDING_MODEL_DIR}'); SentenceTransformer(model_dir)"
ENV EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL_ID} \
    EMBEDDING_MODEL_PATH=${EMBEDDING_MODEL_DIR} \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY app ./app
COPY training ./training
COPY evaluation ./evaluation
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install --no-cache-dir --no-deps .

FROM base AS test

RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
CMD ["python", "-m", "pytest", "--cov=app", "--cov-report=term-missing", "--cov-fail-under=70"]

FROM base AS runtime

COPY app ./app
COPY training ./training
COPY evaluation ./evaluation
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install --no-cache-dir --no-deps .

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
