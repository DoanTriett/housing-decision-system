"""Geocoding helper using Nominatim (OpenStreetMap)."""

from __future__ import annotations

import asyncio

from geopy.geocoders import Nominatim

from src.config import settings
from src.llm.exceptions import GeocodingError


def _geocode_sync(address: str) -> tuple[float, float]:
    geolocator = Nominatim(user_agent=settings.nominatim_user_agent)
    location = geolocator.geocode(address, timeout=10)
    if location is None:
        raise GeocodingError(f"Could not geocode address: {address!r}")
    return float(location.latitude), float(location.longitude)


async def geocode_address(address: str) -> tuple[float, float]:
    """Resolve an address to (lat, lon). Raises GeocodingError on failure."""
    try:
        return await asyncio.to_thread(_geocode_sync, address)
    except GeocodingError:
        raise
    except Exception as exc:
        raise GeocodingError(f"Geocoding failed for {address!r}: {exc}", cause=exc) from exc
