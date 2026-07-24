"""Listings data-access adapter — abstract interface + async SQLAlchemy implementation."""

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.listing import Listing
from src.schemas.agents import ListingCandidate, ListingFilters


class ListingsProvider(ABC):
    """Abstract interface for searching housing listings."""

    @abstractmethod
    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        """Return active listings matching the given filters."""


class DBListingsProvider(ListingsProvider):
    """SQLAlchemy async (asyncpg) implementation of ListingsProvider."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        stmt = (
            select(Listing)
            .where(Listing.is_active.is_(True))
            .where(Listing.price_monthly <= filters.max_price)
        )

        if filters.requires_laundry is not None:
            stmt = stmt.where(Listing.has_laundry.is_(filters.requires_laundry))

        if filters.requires_pet_friendly is not None:
            stmt = stmt.where(Listing.is_pet_friendly.is_(filters.requires_pet_friendly))

        if filters.neighborhood is not None:
            stmt = stmt.where(Listing.neighborhood == filters.neighborhood)

        stmt = stmt.order_by(Listing.price_monthly.asc()).limit(filters.limit)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        return [
            ListingCandidate(
                id=str(row.id),
                title=row.title,
                address=row.address,
                neighborhood=row.neighborhood,
                price_monthly=float(row.price_monthly),
                beds=float(row.beds),
                has_laundry=row.has_laundry,
                is_pet_friendly=row.is_pet_friendly,
                lat=float(row.lat),
                lon=float(row.lon),
                description=row.description,
            )
            for row in rows
        ]
