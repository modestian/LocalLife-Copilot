ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.13.14-slim
FROM ${PYTHON_IMAGE} AS base

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=${PIP_INDEX_URL}

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=1     PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# Layer 1: PyTorch -- large wheel (~200 MB), rarely changes, independently cached.
RUN pip install --no-cache-dir --index-url ${TORCH_INDEX_URL} torch

# Layer 2: All other project dependencies -- only rebuilds when pyproject.toml changes.
COPY pyproject.toml ./
RUN mkdir -p app     && touch app/__init__.py     && pip install --no-cache-dir .     && rm -rf app

# Pre-download the embedding model into the image so no network is needed at runtime.
# BAAI/bge-small-zh-v1.5 is MIT-licensed, ~130 MB, 512-dim Chinese-optimized.
ENV SENTENCE_TRANSFORMERS_HOME=/models/embedding-cache
RUN mkdir -p /models/embedding-cache     && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5', cache_folder='/models/embedding-cache')"

COPY app ./app
COPY training ./training
COPY evaluation ./evaluation
COPY alembic.ini ./
COPY migrations ./migrations

# Install the frequently changing application package without resolving dependencies again.
RUN pip install --no-cache-dir --no-deps .

FROM base AS test

RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
CMD ["python", "-m", "pytest", "--cov=app", "--cov-report=term-missing", "--cov-fail-under=70"]

FROM base AS runtime

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
