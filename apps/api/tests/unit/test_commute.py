"""Unit tests for Commute agent — mocked CommuteProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.commute import run_commute
from src.agents.state import AgentState
from src.schemas.agents import ListingCandidate, UserHousingRequest
from src.tools.maps import CommuteProvider


def _candidate(id: str, lat: float = 30.27, lon: float = -97.74) -> ListingCandidate:
    return ListingCandidate(
        id=id,
        title=f"Apt {id}",
        address=f"{id} Oak St",
        neighborhood="Hyde Park",
        price_monthly=1000,
        beds=1.0,
        has_laundry=True,
        is_pet_friendly=False,
        lat=lat,
        lon=lon,
    )


def _make_state(
    *,
    max_commute_minutes: int | None,
    candidates: list[ListingCandidate] | None = None,
) -> AgentState:
    return AgentState(
        request_id="unit-commute-001",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="University of Texas at Austin, Austin, TX",
            max_commute_minutes=max_commute_minutes,
        ),
        execution_plan=None,
        candidates=candidates or [_candidate("a")],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


@pytest.mark.asyncio
async def test_meets_constraint_true_when_under_max() -> None:
    provider = AsyncMock(spec=CommuteProvider)
    provider.get_walk_minutes = AsyncMock(return_value=12.0)
    state = _make_state(max_commute_minutes=20)

    with patch(
        "src.agents.commute.geocode_address",
        new=AsyncMock(return_value=(30.2849, -97.7341)),
    ):
        result = await run_commute(state, provider)

    assert result["commute_results"]["a"].meets_constraint is True
    assert result["commute_results"]["a"].walk_minutes == 12.0


@pytest.mark.asyncio
async def test_meets_constraint_false_when_over_max() -> None:
    provider = AsyncMock(spec=CommuteProvider)
    provider.get_walk_minutes = AsyncMock(return_value=35.0)
    state = _make_state(max_commute_minutes=20)

    with patch(
        "src.agents.commute.geocode_address",
        new=AsyncMock(return_value=(30.2849, -97.7341)),
    ):
        result = await run_commute(state, provider)

    assert result["commute_results"]["a"].meets_constraint is False


@pytest.mark.asyncio
async def test_meets_constraint_true_when_no_max() -> None:
    provider = AsyncMock(spec=CommuteProvider)
    provider.get_walk_minutes = AsyncMock(return_value=90.0)
    state = _make_state(max_commute_minutes=None)

    with patch(
        "src.agents.commute.geocode_address",
        new=AsyncMock(return_value=(30.2849, -97.7341)),
    ):
        result = await run_commute(state, provider)

    assert result["commute_results"]["a"].meets_constraint is True


@pytest.mark.asyncio
async def test_commute_appends_zero_cost_trace() -> None:
    provider = AsyncMock(spec=CommuteProvider)
    provider.get_walk_minutes = AsyncMock(return_value=10.0)
    state = _make_state(max_commute_minutes=20)

    with patch(
        "src.agents.commute.geocode_address",
        new=AsyncMock(return_value=(30.2849, -97.7341)),
    ):
        result = await run_commute(state, provider)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "commute"
    assert result["trace"][0].cost_usd == 0.0
    assert result["trace"][0].input_tokens == 0
