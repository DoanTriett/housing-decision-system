"""Regression: persisted Recommendation scores must reflect Day 9 hard-constraint clamp.

Day 12 false alarm: walk_minutes=24.9 with max_commute_minutes=25 is NOT a violation.
This test uses an explicit commute failure (meets_constraint=False) and asserts the
clamped score is what lands in the DB after Day 12 enrichment/persist.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.agents.recommendation import run_recommendation
from src.agents.state import AgentState
from src.api.result_enrichment import enrich_ranked_listings
from src.db.session import AsyncSessionLocal, engine
from src.llm.client import LLMResponse
from src.models.recommendation import Recommendation
from src.models.user_request import UserRequest
from src.schemas.agents import (
    CommuteResult,
    ListingCandidate,
    NeighborhoodAssessment,
    UserHousingRequest,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> Any:
    yield
    await engine.dispose()


def _candidate(listing_id: str) -> ListingCandidate:
    return ListingCandidate(
        id=listing_id,
        title=f"Apt {listing_id}",
        address="100 Test St, Austin, TX",
        neighborhood="Hyde Park",
        price_monthly=1100,
        beds=1.0,
        has_laundry=True,
        is_pet_friendly=True,
        lat=30.30,
        lon=-97.73,
    )


def _state() -> AgentState:
    ok = _candidate("listing-ok")
    bad = _candidate("listing-bad")
    state = AgentState(
        request_id=str(uuid.uuid4()),
        user_request=UserHousingRequest(
            budget_max=1400,
            anchor_address="University of Texas at Austin, Austin, TX",
            max_commute_minutes=20,
            free_text="safe quiet near campus",
        ),
        execution_plan=None,
        candidates=[ok, bad],
        neighborhood_findings={
            ok.id: NeighborhoodAssessment(
                listing_id=ok.id,
                summary="Quiet",
                safety_score=4,
                noise_score=2,
                source_docs=["hyde"],
            ),
            bad.id: NeighborhoodAssessment(
                listing_id=bad.id,
                summary="Quiet",
                safety_score=4,
                noise_score=2,
                source_docs=["hyde"],
            ),
        },
        commute_results={
            ok.id: CommuteResult(listing_id=ok.id, walk_minutes=12.0, meets_constraint=True),
            bad.id: CommuteResult(listing_id=bad.id, walk_minutes=35.0, meets_constraint=False),
        },
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )
    return state


def _llm_payload() -> dict[str, Any]:
    # Intentionally high score for the violator — Day 9 clamp must bring it down.
    return {
        "ranked_listings": [
            {
                "listing_id": "listing-ok",
                "rank": 1,
                "score": 0.92,
                "rationale": "Short walk and quiet streets (Commute + Neighborhood).",
            },
            {
                "listing_id": "listing-bad",
                "rank": 2,
                "score": 0.95,
                "rationale": "Nice place but far.",
            },
        ],
        "trade_off_narrative": "Top pick meets commute; #2 does not.",
    }


@pytest.mark.asyncio
async def test_persisted_ranked_listing_score_respects_clamp() -> None:
    state = _state()
    args = json.dumps(_llm_payload())
    mock_resp = LLMResponse(
        content=None,
        tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="submit_recommendation", arguments=args))
        ],
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.0,
        latency_ms=1.0,
        raw=None,
    )

    with patch("src.agents.recommendation.complete", new=AsyncMock(return_value=mock_resp)):
        updated = await run_recommendation(state)

    rec = updated["recommendation"]
    assert rec is not None
    by_id = {item.listing_id: item for item in rec.ranked_listings}
    assert by_id["listing-ok"].score > 0.5
    assert by_id["listing-bad"].score <= 0.5

    enriched = enrich_ranked_listings(updated)
    enriched_by_id = {row["listing_id"]: row for row in enriched}
    assert enriched_by_id["listing-bad"]["score"] <= 0.5
    assert enriched_by_id["listing-bad"]["walk_minutes"] == 35.0

    request_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            UserRequest(
                id=request_id,
                user_id="clamp_persist_test",
                raw_text="safe quiet",
                budget_max=1400,
                anchor_address="University of Texas at Austin, Austin, TX",
                max_commute_minutes=20,
                status="completed",
            )
        )
        await session.flush()
        session.add(
            Recommendation(
                request_id=request_id,
                ranked_listings=enriched,
                trade_off_narrative=rec.trade_off_narrative,
                result_context={"anchor_lat": 30.28, "anchor_lon": -97.73},
            )
        )
        await session.commit()

        loaded = (
            await session.execute(
                select(Recommendation).where(Recommendation.request_id == request_id)
            )
        ).scalar_one()
        db_by_id = {row["listing_id"]: row for row in (loaded.ranked_listings or [])}
        assert db_by_id["listing-bad"]["score"] <= 0.5
        assert db_by_id["listing-ok"]["score"] > 0.5
