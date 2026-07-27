"""Celery task: run the LangGraph housing pipeline and publish SSE progress."""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

import redis.asyncio as aioredis
import structlog
from langchain_core.runnables import RunnableConfig
from qdrant_client import QdrantClient
from sqlalchemy import select

from src.agents.graph import Providers, build_graph
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal, engine
from src.memory.checkpointer import get_checkpointer
from src.models.agent_run import AgentRun
from src.models.recommendation import Recommendation
from src.models.user_request import UserRequest
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider, ListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider
from src.worker.celery_app import celery_app
from src.worker.progress import publish_progress

logger = structlog.get_logger(__name__)

# Keep API runs cheap (same carry-over as Day 5–7 smoke scripts).
_CANDIDATE_LIMIT = 5
_UT_LAT = 30.2849
_UT_LON = -97.7341


def _closest_to_ut(candidates: list[ListingCandidate]) -> list[ListingCandidate]:
    def dist(c: ListingCandidate) -> float:
        return (c.lat - _UT_LAT) ** 2 + (c.lon - _UT_LON) ** 2

    return sorted(candidates, key=dist)[:_CANDIDATE_LIMIT]


class _CappedListingsProvider(ListingsProvider):
    """limit=100 pool, then keep ~5 closest to UT for cost control."""

    def __init__(self, inner: ListingsProvider) -> None:
        self._inner = inner

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        widened = ListingFilters(
            max_price=filters.max_price,
            requires_laundry=filters.requires_laundry,
            requires_pet_friendly=filters.requires_pet_friendly,
            neighborhood=filters.neighborhood,
            limit=max(filters.limit, 100),
        )
        pool = await self._inner.search(widened)
        return _closest_to_ut(pool)


def _initial_state(request_id: str, req: UserHousingRequest) -> AgentState:
    return AgentState(
        request_id=request_id,
        user_request=req,
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


def _recommendation_payload(state: AgentState) -> dict[str, Any] | None:
    rec = state.get("recommendation")
    if rec is None:
        return None
    return rec.model_dump(mode="json")


def _agent_summary(node_name: str, node_update: Any) -> str:
    """One-line status for SSE (no LLM) — feeds the Day 11 live graph."""
    if not isinstance(node_update, dict):
        return f"{node_name.replace('_', ' ')} finished"

    if node_name == "planner":
        plan = node_update.get("execution_plan")
        if plan is not None:
            agents = getattr(plan, "selected_agents", []) or []
            return f"Selected {len(agents)} specialist(s)"
        return "Plan ready"

    if node_name in ("listing_search", "listing_search_retry"):
        candidates = node_update.get("candidates") or []
        return f"Found {len(candidates)} candidates"

    if node_name == "neighborhood":
        findings = node_update.get("neighborhood_findings") or {}
        return f"Assessed {len(findings)} listing(s)"

    if node_name == "commute":
        results = node_update.get("commute_results") or {}
        return f"Checked walk times for {len(results)} listing(s)"

    if node_name == "budget":
        analysis = node_update.get("budget_analysis") or {}
        affordable = sum(1 for item in analysis.values() if getattr(item, "is_affordable", False))
        return f"{affordable}/{len(analysis)} within budget"

    if node_name == "risk":
        flags = node_update.get("risk_flags") or {}
        flagged = sum(1 for item in flags.values() if getattr(item, "flags", None))
        if flagged:
            return f"Flagged {flagged} listing(s)"
        return f"Scanned {len(flags)} listing(s)"

    if node_name == "critic":
        notes = node_update.get("critic_notes")
        if notes is not None:
            if getattr(notes, "approved", False):
                return "Approved — proceed to recommendation"
            issues = getattr(notes, "issues", []) or []
            return f"Retry requested ({len(issues)} issue(s))"
        return "Review complete"

    if node_name == "recommendation":
        rec = node_update.get("recommendation")
        if rec is not None:
            ranked = getattr(rec, "ranked_listings", []) or []
            return f"Ranked top {len(ranked)}"
        return "Recommendation ready"

    return f"{node_name.replace('_', ' ')} finished"


def _enrich_progress_payload(node_name: str, node_update: Any, request_id: str) -> dict[str, Any]:
    """Build an ``agent_complete`` SSE payload with summary (+ planner plan fields)."""
    # Map retry node onto the listing_search card in the live graph.
    display_agent = "listing_search" if node_name == "listing_search_retry" else node_name
    payload: dict[str, Any] = {
        "event": "agent_complete",
        "agent": display_agent,
        "request_id": request_id,
        "summary": _agent_summary(node_name, node_update),
    }
    if isinstance(node_update, dict):
        trace = node_update.get("trace")
        if trace:
            last = trace[-1]
            payload["tokens"] = int(getattr(last, "input_tokens", 0) or 0) + int(
                getattr(last, "output_tokens", 0) or 0
            )
            payload["cost_usd"] = getattr(last, "cost_usd", 0.0)
        if node_name == "planner":
            plan = node_update.get("execution_plan")
            if plan is not None:
                selected = getattr(plan, "selected_agents", []) or []
                payload["selected_agents"] = [
                    a.value if hasattr(a, "value") else str(a) for a in selected
                ]
                payload["reasoning"] = getattr(plan, "reasoning", "") or ""
    return payload


async def _set_request_status(request_id: uuid.UUID, status: str) -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserRequest).where(UserRequest.id == request_id))
        row = result.scalar_one_or_none()
        if row is None:
            logger.warning("user_request_missing", request_id=str(request_id))
            return
        row.status = status
        await session.commit()


async def _persist_results(request_id: uuid.UUID, state: AgentState) -> None:
    """Persist one AgentRun row per specialist in the trace + one Recommendation row.

    Judgment: per-agent AgentRun rows (from ``state["trace"]``) match Day 2's schema
    better than a single summary row and give Day 9 observability something concrete.
    """
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserRequest).where(UserRequest.id == request_id))
        row = result.scalar_one_or_none()
        if row is None:
            raise RuntimeError(f"UserRequest {request_id} not found for persistence")

        for event in state.get("trace") or []:
            session.add(
                AgentRun(
                    request_id=request_id,
                    agent_name=event.agent_name,
                    started_at=event.started_at,
                    finished_at=event.finished_at,
                    tokens_used=event.input_tokens + event.output_tokens,
                    cost_usd=event.cost_usd,
                    output_json={
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                    },
                )
            )

        rec = state.get("recommendation")
        if rec is not None:
            # Day 12: persist comparison/map fields so GET /api/requests/{id}
            # can build the trade-off table without re-running agents.
            from src.api.result_enrichment import (
                build_result_context,
                enrich_ranked_listings,
            )

            enriched = enrich_ranked_listings(state)
            result_context = await build_result_context(state)
            session.add(
                Recommendation(
                    request_id=request_id,
                    ranked_listings=enriched,
                    trade_off_narrative=rec.trade_off_narrative,
                    result_context=result_context,
                )
            )

        row.status = "completed"
        await session.commit()


async def execute_pipeline(
    request_id: str, user_request_dict: dict[str, Any]
) -> dict[str, Any] | None:
    """Run the compiled graph with ``stream_mode="updates"`` and publish progress.

    Returns the final recommendation payload (or None).
    """
    # Each Celery task uses asyncio.run() → a new event loop. Dispose pooled
    # asyncpg connections that may still be bound to a previous loop.
    await engine.dispose()

    req_uuid = uuid.UUID(request_id)
    housing_req = UserHousingRequest.model_validate(user_request_dict)

    await _set_request_status(req_uuid, "running")
    publish_progress(
        request_id,
        {"event": "status", "status": "running", "request_id": request_id},
    )

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    final_state: AgentState | None = None

    try:
        async with get_checkpointer() as checkpointer:
            await checkpointer.setup()
            async with AsyncSessionLocal() as session:
                providers = Providers(
                    listings=_CappedListingsProvider(DBListingsProvider(session)),
                    vector=QdrantVectorSearchProvider(
                        client=qdrant, collection=settings.qdrant_collection
                    ),
                    commute=GoogleMapsCommuteProvider(
                        api_key=settings.google_maps_api_key,
                        redis_client=redis_client,
                    ),
                )
                graph = build_graph(providers, checkpointer=checkpointer)
                config: RunnableConfig = {"configurable": {"thread_id": request_id}}
                initial = _initial_state(request_id, housing_req)

                async for update in graph.astream(initial, config=config, stream_mode="updates"):
                    if not isinstance(update, dict):
                        continue
                    for node_name, node_update in update.items():
                        # Skip internal bookkeeping nodes from the SSE feed.
                        if node_name in ("prepare_retry",):
                            continue
                        payload = _enrich_progress_payload(node_name, node_update, request_id)
                        publish_progress(request_id, payload)

                # Load final checkpointed state for persistence.
                snapshot = await graph.aget_state(config)
                values = snapshot.values if snapshot else {}
                final_state = values  # type: ignore[assignment]

        if not final_state:
            raise RuntimeError("Graph finished without a final state")

        await _persist_results(req_uuid, final_state)
        recommendation = _recommendation_payload(final_state)
        publish_progress(
            request_id,
            {
                "event": "done",
                "request_id": request_id,
                "recommendation": recommendation,
            },
        )
        return recommendation
    finally:
        await redis_client.close()


def _run_coro(coro: Any) -> Any:
    """Run an async coroutine from sync Celery code.

    When ``task_always_eager`` runs inside FastAPI's event loop, ``asyncio.run``
    fails — fall back to a dedicated thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@celery_app.task(name="run_pipeline")  # type: ignore[untyped-decorator]
def run_pipeline_task(request_id: str, user_request_dict: dict[str, Any]) -> None:
    """Celery entrypoint — sync wrapper around the async graph pipeline."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        _run_coro(execute_pipeline(request_id, user_request_dict))
    except Exception as exc:
        logger.exception("pipeline_task_failed", request_id=request_id, error=str(exc))
        try:
            publish_progress(
                request_id,
                {"event": "error", "request_id": request_id, "detail": str(exc)},
            )
        except Exception:
            logger.exception("failed_to_publish_error_event", request_id=request_id)
        try:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            _run_coro(_set_request_status(uuid.UUID(request_id), "failed"))
        except Exception:
            logger.exception("failed_to_mark_request_failed", request_id=request_id)
        raise
