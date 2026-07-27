"""Redis pub/sub helpers for live pipeline progress (SSE bridge)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import redis
import redis.asyncio as aioredis
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def _channel(request_id: str) -> str:
    return f"{settings.sse_channel_prefix}:{request_id}"


def publish_progress(request_id: str, event: dict[str, Any]) -> None:
    """Publish a JSON progress event (sync — safe to call from Celery tasks)."""
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        payload = json.dumps(event, default=str)
        client.publish(_channel(request_id), payload)
        logger.debug(
            "progress_published",
            request_id=request_id,
            event_type=event.get("event"),
        )
    finally:
        client.close()


async def subscribe_progress(request_id: str) -> AsyncGenerator[dict[str, Any], None]:
    """Yield progress events until a terminal ``done`` or ``error`` event arrives."""
    client: aioredis.Redis[str] = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    pubsub = client.pubsub()
    channel = _channel(request_id)
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("progress_bad_json", raw=data[:200])
                continue
            if not isinstance(event, dict):
                continue
            yield event
            if event.get("event") in ("done", "error"):
                return
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await client.close()
