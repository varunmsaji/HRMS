# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src
COPY entrypoints ./entrypoints
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

FROM base AS runtime
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Default: API process (override command for worker/beat/ingestion — Document 13 §2)
CMD ["uvicorn", "entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000"]
