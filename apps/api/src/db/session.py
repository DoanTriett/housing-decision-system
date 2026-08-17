import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import settings
from src.db.url import make_asyncpg_url

_database_url, _connect_args = make_asyncpg_url(settings.database_url)

# Celery tasks call asyncio.run() which creates a new event loop each time.
# asyncpg pooled connections are bound to the loop that created them, so a
# QueuePool from a previous loop is stale/closed (InterfaceError on commit).
# NullPool never retains connections across those asyncio.run() boundaries.
# FastAPI must NOT set WORKER_MODE — it keeps the default pooled engine.
_worker_mode = os.environ.get("WORKER_MODE", "").lower() == "true"

engine = (
    create_async_engine(
        _database_url,
        echo=False,
        pool_pre_ping=True,
        connect_args=_connect_args,
        poolclass=NullPool,
    )
    if _worker_mode
    else create_async_engine(
        _database_url,
        echo=False,
        pool_pre_ping=True,
        connect_args=_connect_args,
    )
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
