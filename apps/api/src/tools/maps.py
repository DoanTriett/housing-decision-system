"""Commute / walking-time adapter — Google Maps Directions + Redis cache."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import googlemaps
import structlog
from redis.asyncio import Redis

from src.config import settings
from src.llm.exceptions import CommuteError

logger = structlog.get_logger(__name__)


class CommuteProvider(ABC):
    """Abstract interface for walking-time calculations."""

    @abstractmethod
    async def get_walk_minutes(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> float:
        """Return walking time in minutes between two coordinates."""


def _cache_key(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> str:
    return f"commute:{origin_lat:.4f},{origin_lon:.4f}:{dest_lat:.4f},{dest_lon:.4f}"


class GoogleMapsCommuteProvider(CommuteProvider):
    """Google Maps Directions API with Redis caching."""

    def __init__(self, api_key: str, redis_client: Redis[str]) -> None:
        if not api_key:
            raise CommuteError("GOOGLE_MAPS_API_KEY is not set")
        self._client = googlemaps.Client(key=api_key)
        self._redis = redis_client
        self._ttl = settings.commute_cache_ttl_seconds

    def _directions_sync(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> float:
        try:
            response: Any = self._client.directions(
                origin=(origin_lat, origin_lon),
                destination=(dest_lat, dest_lon),
                mode="walking",
            )
        except Exception as exc:
            raise CommuteError(f"Google Maps API request failed: {exc}", cause=exc) from exc

        if not response:
            raise CommuteError(
                f"Google Maps returned ZERO_RESULTS for "
                f"({origin_lat},{origin_lon}) → ({dest_lat},{dest_lon})"
            )

        try:
            duration_seconds = response[0]["legs"][0]["duration"]["value"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CommuteError(f"Unexpected Google Maps response shape: {exc}", cause=exc) from exc

        return float(duration_seconds) / 60.0

    async def get_walk_minutes(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> float:
        key = _cache_key(origin_lat, origin_lon, dest_lat, dest_lon)

        cached = await self._redis.get(key)
        if cached is not None:
            minutes = float(cached)
            logger.info("commute_cache_hit", key=key, walk_minutes=round(minutes, 1))
            return minutes

        logger.info("commute_cache_miss", key=key)
        minutes = await asyncio.to_thread(
            self._directions_sync, origin_lat, origin_lon, dest_lat, dest_lon
        )
        await self._redis.set(key, str(minutes), ex=self._ttl)
        logger.debug("commute_cached", key=key, walk_minutes=minutes, ttl=self._ttl)
        return minutes
