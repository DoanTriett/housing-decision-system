"""Integration tests for Google Maps commute + Redis cache."""

from __future__ import annotations

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.config import settings
from src.tools.maps import GoogleMapsCommuteProvider, _cache_key


@pytest_asyncio.fixture
async def redis_client() -> Redis:
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_maps_walk_minutes_and_cache(redis_client: Redis) -> None:
    # UT Austin tower ≈ downtown Congress Ave
    origin = (30.2849, -97.7341)
    dest = (30.2672, -97.7431)
    key = _cache_key(*origin, *dest)

    await redis_client.delete(key)

    provider = GoogleMapsCommuteProvider(
        api_key=settings.google_maps_api_key,
        redis_client=redis_client,
    )

    minutes = await provider.get_walk_minutes(*origin, *dest)
    assert isinstance(minutes, float)
    assert minutes > 0

    cached = await redis_client.get(key)
    assert cached is not None
    assert abs(float(cached) - minutes) < 0.01

    # Second call should hit cache (same value)
    minutes2 = await provider.get_walk_minutes(*origin, *dest)
    assert minutes2 == minutes
