# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY scripts/ ./scripts/
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

# Railway uses the same image for API and worker services.
CMD ["sh", "-c", "if [ \"$PROCESS_TYPE\" = \"worker\" ]; then celery -A src.worker.celery_app:celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2}; else uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]
