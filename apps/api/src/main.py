import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.rate_limit import limiter
from src.api.routes.observability import router as observability_router
from src.api.routes.requests import router as requests_router
from src.config import configure_langsmith_env, settings
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
    configure_langsmith_env()
    logger.info(
        "startup",
        environment=settings.environment,
        models_registered=list(Base.metadata.tables.keys()),
        langsmith_enabled=bool(
            settings.langchain_api_key or settings.langsmith_api_key
        ),
    )
    yield
    logger.info("shutdown")


app = FastAPI(
    title="Housing Decision API",
    lifespan=lifespan,
    swagger_ui_init_oauth={},
)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,  # type: ignore[arg-type]
)
# Browser clients (Next.js) need CORS before auth'd fetch works.
# Always include localhost; add production origins via CORS_ORIGINS (comma-separated).
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_cors_origins.extend(
    [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.include_router(requests_router)
app.include_router(observability_router)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "HTTPBearer"
    ] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Clerk JWT (Authorization: Bearer <token>)",
    }
    # Mark authenticated API routes as requiring Bearer auth in Swagger UI.
    for path, methods in schema.get("paths", {}).items():
        path_str = str(path)
        if not (
            path_str.startswith("/api/requests")
            or path_str.startswith("/api/admin")
        ):
            continue
        for method_schema in methods.values():
            if isinstance(method_schema, dict):
                method_schema.setdefault("security", [{"HTTPBearer": []}])
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


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
