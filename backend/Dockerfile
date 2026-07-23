ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.13.14-slim
FROM ${PYTHON_IMAGE} AS base

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml ./

# Resolve the expensive third-party dependency layer from the stable manifest only.
# Preinstall CPU-only PyTorch so pip does not pull unused CUDA/NVIDIA runtimes.
RUN pip install --no-cache-dir --index-url ${TORCH_INDEX_URL} torch \
    && mkdir -p app \
    && touch app/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf app

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
