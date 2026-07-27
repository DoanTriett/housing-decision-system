"""Unit test: neighborhood agent clamps out-of-range LLM scores."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.neighborhood import _assess_candidate
from src.llm.client import LLMResponse
from src.schemas.agents import ListingCandidate, NeighborhoodDoc


@pytest.mark.asyncio
async def test_neighborhood_clamps_zero_scores() -> None:
    candidate = ListingCandidate(
        id="n1",
        title="Apt",
        address="1 Main",
        neighborhood="Hyde Park",
        price_monthly=1000,
        beds=1,
        has_laundry=True,
        is_pet_friendly=True,
        lat=30.3,
        lon=-97.7,
    )
    docs = [NeighborhoodDoc(neighborhood="Hyde Park", content="Quiet streets.", score=0.9)]
    payload = {
        "listing_id": "ignored",
        "summary": "Quiet.",
        "safety_score": 0,
        "noise_score": 0,
        "source_docs": ["hyde"],
    }
    resp = LLMResponse(
        content=None,
        tool_calls=[
            SimpleNamespace(
                function=SimpleNamespace(
                    name="submit_neighborhood_assessment",
                    arguments=json.dumps(payload),
                )
            )
        ],
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
        raw=None,
    )
    with patch("src.agents.neighborhood.complete", new=AsyncMock(return_value=resp)):
        assessment, _, _, _ = await _assess_candidate(candidate, docs)
    assert assessment.safety_score >= 1
    assert assessment.noise_score >= 1
    assert assessment.listing_id == "n1"
