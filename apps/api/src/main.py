import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.config import settings
from src.models import Base  # noqa: F401 — ensures all models are registered

logger = structlog.get_logger(__name__)


def configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.environment == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), settings.log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_structlog()
    logger.info(
        "startup",
        environment=settings.environment,
        models_registered=list(Base.metadata.tables.keys()),
    )
    yield
    logger.info("shutdown")


app = FastAPI(title="Housing Decision API", lifespan=lifespan)


def _sync_check_database(url: str) -> None:
    """Synchronous psycopg ping — safe on any event loop (including Windows ProactorEventLoop)."""
    import psycopg

    conn = psycopg.connect(url, connect_timeout=3)
    conn.execute("SELECT 1")
    conn.close()


async def _check_database() -> dict[str, Any]:
    try:
        await asyncio.to_thread(_sync_check_database, settings.database_url)
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("database_check_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}


async def _check_redis() -> dict[str, Any]:
    import redis.asyncio as aioredis

    try:
        client: aioredis.Redis[bytes] = aioredis.from_url(
            settings.redis_url, socket_connect_timeout=3
        )
        await client.ping()
        await client.aclose()  # type: ignore[attr-defined]
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("redis_check_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}


@app.get("/health")
async def health() -> JSONResponse:
    db_result = await _check_database()
    redis_result = await _check_redis()

    all_ok = db_result["status"] == "ok" and redis_result["status"] == "ok"
    status_code = 200 if all_ok else 503

    payload = {
        "status": "ok" if all_ok else "degraded",
        "checks": {
            "database": db_result,
            "redis": redis_result,
        },
    }
    logger.info("health_check", status_code=status_code, checks=payload["checks"])
    return JSONResponse(content=payload, status_code=status_code)
