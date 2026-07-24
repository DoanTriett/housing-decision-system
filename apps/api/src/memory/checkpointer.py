"""Postgres checkpointer for LangGraph session memory (per thread_id)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.config import settings


def _sync_conn_string(url: str) -> str:
    """Ensure a sync psycopg DSN (strip SQLAlchemy async drivers if present)."""
    cleaned = url.replace("postgresql+asyncpg://", "postgresql://")
    cleaned = cleaned.replace("postgres://", "postgresql://")
    return cleaned


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Yield an AsyncPostgresSaver bound to ``settings.database_url``.

    LangGraph ``ainvoke`` requires the async checkpointer API (``aget_tuple``).
    ``AsyncPostgresSaver.from_conn_string`` owns the psycopg async connection —
    keep it open for the CLI/session lifetime. Call ``await checkpointer.setup()``
    once at startup (not per invoke).
    """
    async with AsyncPostgresSaver.from_conn_string(
        _sync_conn_string(settings.database_url)
    ) as checkpointer:
        yield checkpointer
