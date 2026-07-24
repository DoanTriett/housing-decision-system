"""Integration tests for Listing Search against real local Postgres.

Requires Docker Compose infra running (postgres on localhost:5432).
Marked with pytest.mark.integration so CI can skip when Docker is unavailable.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.agents.listing_search import run_listing_search
from src.agents.state import AgentState
from src.config import settings
from src.llm.exceptions import ListingSearchError
from src.schemas.agents import UserHousingRequest
from src.tools.listings_repo import DBListingsProvider


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(_async_url(settings.database_url), echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


def _make_state(
    *,
    budget_max: float,
    requires_laundry: bool = False,
    requires_pet_friendly: bool = False,
) -> AgentState:
    return AgentState(
        request_id="integration-ls-001",
        user_request=UserHousingRequest(
            budget_max=budget_max,
            anchor_address="Austin, TX",
            requires_laundry=requires_laundry,
            requires_pet_friendly=requires_pet_friendly,
        ),
        execution_plan=None,
        candidates=[],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_max_price_1200_returns_results(session: AsyncSession) -> None:
    provider = DBListingsProvider(session)
    state = _make_state(budget_max=1200)

    result = await run_listing_search(state, provider)

    assert len(result["candidates"]) >= 1
    assert all(c.price_monthly <= 1200 for c in result["candidates"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_pet_friendly_only(session: AsyncSession) -> None:
    provider = DBListingsProvider(session)
    state = _make_state(budget_max=2500, requires_pet_friendly=True)

    result = await run_listing_search(state, provider)

    assert len(result["candidates"]) >= 1
    assert all(c.is_pet_friendly for c in result["candidates"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_impossible_price_raises(session: AsyncSession) -> None:
    provider = DBListingsProvider(session)
    state = _make_state(budget_max=1)

    with pytest.raises(ListingSearchError):
        await run_listing_search(state, provider)
