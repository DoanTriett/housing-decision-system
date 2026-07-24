"""Unit tests for Neighborhood agent — mocked provider and LLM."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.neighborhood import run_neighborhood
from src.agents.state import AgentState
from src.llm.client import LLMResponse
from src.schemas.agents import ListingCandidate, NeighborhoodDoc, UserHousingRequest
from src.tools.vector_search import VectorSearchProvider


def _candidate(id: str, neighborhood: str) -> ListingCandidate:
    return ListingCandidate(
        id=id,
        title=f"Apt {id}",
        address=f"{id} Main St",
        neighborhood=neighborhood,
        price_monthly=1000,
        beds=1.0,
        has_laundry=True,
        is_pet_friendly=False,
        lat=30.27,
        lon=-97.74,
    )


def _make_state(candidates: list[ListingCandidate]) -> AgentState:
    return AgentState(
        request_id="unit-nbhd-001",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="UT Austin",
            free_text="safe and quiet neighborhood",
        ),
        execution_plan=None,
        candidates=candidates,
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


def _mock_llm(
    listing_id: str,
    *,
    safety: int = 4,
    noise: int = 2,
    source: str = "Hyde Park",
) -> LLMResponse:
    fn = SimpleNamespace(
        name="submit_neighborhood_assessment",
        arguments=json.dumps(
            {
                "listing_id": listing_id,
                "summary": f"{source} is safe and relatively quiet.",
                "safety_score": safety,
                "noise_score": noise,
                "source_docs": [source],
            }
        ),
    )
    return LLMResponse(
        content=None,
        tool_calls=[SimpleNamespace(function=fn)],
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0002,
        latency_ms=300.0,
        raw=None,
    )


@pytest.mark.asyncio
async def test_neighborhood_filters_docs_to_matching_neighborhood() -> None:
    """Provider docs are filtered to the candidate's neighborhood when present."""
    docs = [
        NeighborhoodDoc(
            neighborhood="East Austin",
            content="East Austin is lively.",
            score=0.7,
        ),
        NeighborhoodDoc(
            neighborhood="Hyde Park",
            content="Hyde Park is quiet and safe.",
            score=0.55,
        ),
    ]
    provider = AsyncMock(spec=VectorSearchProvider)
    provider.search = AsyncMock(return_value=docs)
    state = _make_state([_candidate("a", "Hyde Park")])

    with patch(
        "src.agents.neighborhood.complete",
        new=AsyncMock(return_value=_mock_llm("a", source="Hyde Park")),
    ) as mock_complete:
        result = await run_neighborhood(state, provider)

    # LLM was called; the user message should reference Hyde Park docs
    call_args = mock_complete.await_args
    user_msg = call_args.kwargs["messages"][1]["content"]
    assert "Hyde Park" in user_msg
    assert "East Austin is lively" not in user_msg
    assert result["neighborhood_findings"]["a"].source_docs == ["Hyde Park"]


@pytest.mark.asyncio
async def test_neighborhood_scores_populated() -> None:
    provider = AsyncMock(spec=VectorSearchProvider)
    provider.search = AsyncMock(
        return_value=[NeighborhoodDoc(neighborhood="Mueller", content="Very safe.", score=0.6)]
    )
    state = _make_state([_candidate("b", "Mueller")])

    with patch(
        "src.agents.neighborhood.complete",
        new=AsyncMock(return_value=_mock_llm("b", safety=5, noise=1, source="Mueller")),
    ):
        result = await run_neighborhood(state, provider)

    assessment = result["neighborhood_findings"]["b"]
    assert assessment.safety_score == 5
    assert assessment.noise_score == 1
    assert assessment.summary != ""


@pytest.mark.asyncio
async def test_neighborhood_appends_trace() -> None:
    provider = AsyncMock(spec=VectorSearchProvider)
    provider.search = AsyncMock(
        return_value=[NeighborhoodDoc(neighborhood="Zilker", content="Quiet parks.", score=0.5)]
    )
    state = _make_state([_candidate("c", "Zilker")])

    with patch(
        "src.agents.neighborhood.complete",
        new=AsyncMock(return_value=_mock_llm("c", source="Zilker")),
    ):
        result = await run_neighborhood(state, provider)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "neighborhood"
    assert result["trace"][0].input_tokens == 100
    assert result["trace"][0].cost_usd == 0.0002
