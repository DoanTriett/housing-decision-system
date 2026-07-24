"""Unit tests for Listing Search agent — ListingsProvider is mocked, no DB."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.listing_search import run_listing_search
from src.agents.state import AgentState
from src.llm.exceptions import ListingSearchError
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import ListingsProvider


def _candidate(
    *,
    id: str,
    price: float,
    laundry: bool = False,
    pet: bool = False,
) -> ListingCandidate:
    return ListingCandidate(
        id=id,
        title=f"Listing {id}",
        address=f"{id} Main St",
        neighborhood="East Austin",
        price_monthly=price,
        beds=1.0,
        has_laundry=laundry,
        is_pet_friendly=pet,
        lat=30.26,
        lon=-97.74,
    )


def _make_state(
    *,
    budget_max: float = 1000,
    requires_laundry: bool = False,
    requires_pet_friendly: bool = False,
) -> AgentState:
    return AgentState(
        request_id="unit-ls-001",
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


class _FakeProvider(ListingsProvider):
    def __init__(self, results: list[ListingCandidate]) -> None:
        self.results = results
        self.last_filters: ListingFilters | None = None

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        self.last_filters = filters
        return self.results


@pytest.mark.asyncio
async def test_listing_search_filters_by_max_price() -> None:
    """Agent passes max_price=budget_max to the provider."""
    provider = _FakeProvider([_candidate(id="a", price=800)])
    state = _make_state(budget_max=900)

    result = await run_listing_search(state, provider)

    assert provider.last_filters is not None
    assert provider.last_filters.max_price == 900
    assert len(result["candidates"]) == 1
    assert result["candidates"][0].price_monthly == 800


@pytest.mark.asyncio
async def test_listing_search_filters_by_laundry() -> None:
    """requires_laundry=True is forwarded to the provider."""
    provider = _FakeProvider([_candidate(id="b", price=800, laundry=True)])
    state = _make_state(budget_max=1000, requires_laundry=True)

    result = await run_listing_search(state, provider)

    assert provider.last_filters is not None
    assert provider.last_filters.requires_laundry is True
    assert all(c.has_laundry for c in result["candidates"])


@pytest.mark.asyncio
async def test_listing_search_filters_by_pet_friendly() -> None:
    """requires_pet_friendly=True is forwarded to the provider."""
    provider = _FakeProvider([_candidate(id="c", price=800, pet=True)])
    state = _make_state(budget_max=1000, requires_pet_friendly=True)

    result = await run_listing_search(state, provider)

    assert provider.last_filters is not None
    assert provider.last_filters.requires_pet_friendly is True
    assert all(c.is_pet_friendly for c in result["candidates"])


@pytest.mark.asyncio
async def test_listing_search_raises_on_empty_results() -> None:
    """Empty provider response raises ListingSearchError."""
    provider = _FakeProvider([])
    state = _make_state(budget_max=100)

    with pytest.raises(ListingSearchError):
        await run_listing_search(state, provider)


@pytest.mark.asyncio
async def test_listing_search_appends_zero_cost_trace() -> None:
    """No LLM call — tokens and cost are zero."""
    provider = AsyncMock(spec=ListingsProvider)
    provider.search = AsyncMock(return_value=[_candidate(id="d", price=700)])
    state = _make_state()

    result = await run_listing_search(state, provider)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "listing_search"
    assert result["trace"][0].input_tokens == 0
    assert result["trace"][0].output_tokens == 0
    assert result["trace"][0].cost_usd == 0.0
