# Project Baseline — Multi-Agent Housing Decision System

Last updated: after Day 3

---

## Completed

### Day 1 — Infrastructure & Scaffolding
- Monorepo structure (`apps/api/`, `infra/`, `.github/workflows/`)
- Docker Compose: Postgres, Redis, Qdrant — all healthy with real healthchecks
- FastAPI app with `/health` endpoint that genuinely checks DB + Redis connectivity (returns 503 on real failure)
- `pydantic-settings` config, `structlog` JSON logging
- `uv` package manager, Python 3.12
- Ruff + mypy + pre-commit hooks
- GitHub Actions CI: lint → type-check → test (green)
- `.env.example`, `.gitignore`, setup README

**Known workarounds from Day 1:**
- `asyncio.to_thread` used for psycopg health check (Windows ProactorEventLoop incompatibility with psycopg async). Psycopg stays sync for health check only.
- Qdrant healthcheck uses `bash -c 'echo > /dev/tcp/localhost/6333'` (minimal image has no curl/wget)

### Day 2 — Data Layer & Domain Models
- SQLAlchemy 2.0 async ORM models: `Listing`, `UserRequest`, `AgentRun`, `Recommendation`, `UserProfile`
- Alembic migrations (initial schema, idempotent — second run is a no-op)
- `_make_async_url()` helper in `session.py` and `alembic/env.py` converts `postgresql://` → `postgresql+asyncpg://` transparently. Health check still uses plain psycopg URL untouched.
- SQLAlchemy async engine uses `asyncpg` (not psycopg async) — no Windows event loop issue
- Alembic `versions/*` excluded from ruff (generated files, Alembic's own template style)
- 200 synthetic listings seeded for Austin, TX (real neighborhood names, varied price/amenities)
- 15 neighborhood profile docs embedded with `voyage-3` (dim=1024) into Qdrant collection `neighborhoods`
- Semantic smoke-test: query "safe quiet neighborhood near university" → top result Hyde Park (score=0.584), correct
- Pydantic v2 schemas for all 5 models (`*Base`, `*Create`, `*Read`)
- `verify_day2.py` script: all 5 checks pass

### Day 3 — LLM Abstraction & Planner Agent
- LiteLLM wrapper (`src/llm/client.py`): async `complete()`, returns typed `LLMResponse` (content, tool_calls, tokens, cost_usd, latency_ms)
- `litellm` pinned to `<1.70` (1.69.3) — versions ≥1.70 require MSVC Build Tools for a Rust extension; 1.69.3 is pure Python and fully functional
- Cost tracking via `litellm.completion_cost()`, latency via `time.perf_counter()`
- Typed exceptions: `LLMError`, `PlannerError` in `src/llm/exceptions.py` — raw LiteLLM exceptions never escape the client module
- Retry logic: exponential backoff with `asyncio.sleep`, up to `settings.llm_max_retries`
- `AgentState` TypedDict (`src/agents/state.py`) — full shared state schema all future agents will read/write
- All per-agent Pydantic schemas in `src/schemas/agents.py`: `UserHousingRequest`, `ExecutionPlan`, `AgentName` (StrEnum), `ListingCandidate`, `NeighborhoodAssessment`, `CommuteResult`, `BudgetAnalysis`, `RiskAssessment`, `CriticReview`, `RecommendationOutput`, `RankedListing`, `AgentTraceEvent`
- Planner agent (`src/agents/planner.py`): tool-calling with forced `tool_choice`, returns typed `ExecutionPlan`, appends `AgentTraceEvent` to state
- System prompt in `src/llm/prompts/planner.py` (not inline)
- `tool_choice` passed as dict (OpenAI requires dict form to force a specific function; litellm 1.69 signature says `str` but accepts dict cleanly)
- Unit tests: 3 scenarios, fully mocked, all passing
- Smoke-test cost: ~$0.0005 per call (GPT-4.1-mini)
- All 4 tests passing, ruff clean, mypy clean (27 source files)

### Day 4 — Listing Search & Budget Agents
- Planner system prompt rewritten with explicit per-agent selection rules and 2 few-shot examples
- Routing judgment confirmed fixed: Request B → `listing_search + budget` only (no spurious commute), Request C → `listing_search + neighborhood + risk` (risk not budget)
- `ListingFilters` Pydantic model added to `src/schemas/agents.py`
- `ListingsProvider` abstract base class + `DBListingsProvider` implementation in `src/tools/listings_repo.py`
- Listing Search agent (`src/agents/listing_search.py`): pure DB filtering, no LLM call, raises `ListingSearchError` on empty results
- Budget agent (`src/agents/budget.py`): deterministic math in Python, single batched LLM call for plain-language explanations via tool-calling
- Unit tests: 9 passing (4 for listing search, 5 for budget), all mocked
- Integration tests: 3 passing against real Postgres
- Full suite: 16 tests passing
- Smoke-test cost: ~$0.000227 per Budget agent call (GPT-4.1-mini, 263 input / 76 output tokens)

### Day 5 — Neighborhood & Commute Agents
- `VectorSearchProvider` abstract base + `QdrantVectorSearchProvider` in `src/tools/vector_search.py`
- Provider-level Voyage AI embedding cache on `(query, top_k)` — prevents hitting the 3 RPM free-tier limit when the same query is issued per candidate
- Neighborhood agent (`src/agents/neighborhood.py`): embeds user preference text, retrieves top-k neighborhood docs from Qdrant, synthesizes `NeighborhoodAssessment` (summary, safety_score 1–5, noise_score 1–5) via tool-calling; falls back to top result when no exact neighborhood name match
- `CommuteProvider` abstract base + `GoogleMapsCommuteProvider` in `src/tools/maps.py`
- Commute agent (`src/agents/commute.py`): geocodes anchor address once, calls Google Maps Directions API per candidate, no LLM call
- Redis cache for commute results: key `commute:{lat},{lon}:{lat},{lon}` (4 decimal places), TTL 24h — confirmed cache hits on second run
- Geocoding helper (`src/tools/geocoding.py`): Nominatim via `asyncio.to_thread`, raises `GeocodingError` on failure
- `GeocodingError`, `CommuteError` added to `src/llm/exceptions.py`
- `NeighborhoodDoc` Pydantic model added to `src/schemas/agents.py`
- Unit tests: 7 passing (all mocked)
- Integration tests: Qdrant query + Google Maps real API call both passing
- Full suite: 25 tests passing
- Smoke-test: 5 candidates (widened to limit=100, selected 5 closest to UT Austin), neighborhood cost ~$0.0018, Google Maps cost ~$0 (free tier)

### Day 6 — Risk Agent + Critic Agent + LangGraph Graph Wiring
- Risk agent (`src/agents/risk.py`): rule-based below-market flag (>25% below median) + batched LLM reasoning over listing descriptions via tool-calling; promotes risk level to at least `medium` when a rule flag fires
- Critic agent (`src/agents/critic.py`): reviews full state for constraint coverage, contradictions, unsupported claims; bounded retry cap enforced in code (`retry_count >= 1` → force approve), not just in prompt
- Recommendation stub (`src/agents/recommendation.py`): returns top-3 by price with `rationale="stub"` — replaced on Day 7
- `StateGraph` wiring (`src/agents/graph.py`): `planner → listing_search → parallel(neighborhood, commute, budget, risk) → critic → bounded_retry_or_recommendation`
- `trace` field uses `Annotated[list, operator.add]` for correct parallel fan-out merging in LangGraph
- `retry_count` incremented in `prepare_retry` node (not at Critic start) to avoid skipping the first retry
- `listing_search_retry` node added — retrying listing search does not re-fan-out all specialists
- `limit=100` + proximity sort to UT applied in Listing Search (carry-over from Day 5)
- Typed exceptions: `RiskError`, `CriticError` added to `src/llm/exceptions.py`
- `ListingCandidate.description` field added to schema and mapped in `listings_repo.py`
- Unit tests: 11 passing (risk, critic, graph routing — all mocked)
- Full suite: 36 tests passing
- Smoke-test costs: Request A (4 agents) ~$0.0033, Request B (2 agents) ~$0.0015
- Forced retry verified: trace shows `budget → critic → budget → critic` with `retry_count=1` and cap enforced
---

## Not Yet Built

| Day | What |
|-----|------|
| Day 7 | Recommendation agent + Postgres checkpointer (session memory) + long-term `UserProfile` memory + end-to-end CLI |
| Day 8 | FastAPI endpoints (`POST /requests`, `GET /requests/{id}/stream` SSE) + Celery task queue + Redis pub/sub bridge |
| Day 9 | Auth middleware (Clerk) + `AgentRun` persistence + rate limiting + API hardening |
| Day 10 | Next.js frontend scaffold + Clerk auth + request form |
| Day 11 | Live agent execution visualization (SSE-driven animated graph) |
| Day 12 | Results UI + map view + history page + observability dashboard |
| Day 13 | Eval harness (golden dataset, routing accuracy, constraint satisfaction, LLM-as-judge) + CI eval gate |
| Day 14 | Production deployment + LangSmith tracing + polished README + demo video |

---

## Known Issues & Notes to Resolve Later
### Day 6
- True parallel execution is `neighborhood + commute + budget + risk` only — `listing_search` always runs first since all other agents depend on `state["candidates"]`. This is correct architecture, not a limitation. Document explicitly in Day 14 README/ADR.
- `langgraph==1.2.9` pinned in lockfile — if LangGraph releases a breaking change, the parallel fan-out `add_conditional_edges` API may need updating.
- Recommendation agent is a stub — Day 7 replaces it with real ranked output and trade-off narrative.
- Critic's retry currently can target any single agent — if it targets `listing_search`, it does not re-fan-out the downstream specialists. This is intentional for cost control but means a listing-search retry produces a partial re-evaluation.

### Day 5
- Candidate selection in smoke tests requires `limit=100` + proximity sort to UT — cheapest-first top-20 are mostly far from campus and fail the 20-min constraint. Use this wider search in Day 6 end-to-end run too.
- Voyage AI free tier is 3 RPM — provider-level cache prevents re-embedding the same query. If Day 6 tests run the Neighborhood agent repeatedly, the cache will protect against rate limit errors.
- Exact neighborhood name matching between Qdrant docs and listing data is case-insensitive but fuzzy match may be needed if names diverge further (e.g., "East Austin" vs "East Side"). Monitor during Day 6 integration.

### Day 4
- Only 1 listing in the seed data matches $900 + laundry + pet-friendly simultaneously. Use looser constraints (e.g., $1,200 budget, no amenity filters) for Day 5–7 smoke tests. The tight filter is still valid for eval harness test cases.
- Request A under the tightened Planner prompt now selects `listing_search + neighborhood + commute` (not all 5), which is correct — "all 5" only triggers when the free text explicitly mentions affordability concern AND scam/trust signals. This is not a regression.
- `ListingSearchError` on 0 results is intentional — downstream agents must never run on an empty candidate set. The Critic agent (Day 6) should handle this gracefully rather than crashing the graph.


### 🔴 Planner routing judgment is looser than ideal (Day 3)
The live GPT-4.1-mini model doesn't route as precisely as the unit test expectations:
- **Request A** (full): skipped `risk` despite a below-market price concern being a natural fit
- **Request B** (minimal): added `commute` because an anchor address was present, even though no commute constraint was stated
- **Request C** (safety): chose `budget` over `risk` when `risk` was the correct specialist for a safety concern

The unit tests pass because they mock the LLM response — they test parsing, not model judgment. The smoke test reveals the real behavior.

**Root cause:** the system prompt doesn't give the model enough signal to distinguish between "an anchor address exists" (always true) vs "the user has a commute constraint" (explicit), or between "budget" (affordability) vs "risk" (scam/safety flags).

**Resolution options (pick one before Day 6 when graph wiring locks in the routing contract):**
1. Tighten the system prompt with explicit rules per agent (e.g., "only select `commute` if the user states a maximum commute time or distance"; "only select `risk` if the user mentions safety, scams, or unusually low price concerns")
2. Add few-shot examples to the prompt showing correct routing decisions for ambiguous cases
3. Accept loose routing as a known limitation and document it — the system still works, it just runs more agents than strictly necessary

**Recommended:** option 1 + a couple of few-shot examples. Address this at the start of Day 6 before wiring the graph, or it will cause flaky behavior in end-to-end tests.

### 🟡 `litellm` pinned to `<1.70` (Day 3)
Versions ≥1.70 require MSVC Build Tools (Rust extension). Safe to upgrade once Build Tools are installed. No functional impact for now — 1.69.3 has all needed features.

### 🟡 Voyage AI semantic scores are moderate (Day 2)
Top similarity score for "safe quiet neighborhood near university" was 0.584 (Hyde Park). Acceptable for RAG retrieval, but if the Neighborhood agent's results feel weak during Day 5 testing, consider lowering the retrieval threshold or expanding neighborhood doc length.

### 🟢 `asyncio.to_thread` for psycopg (Day 1, resolved)
Works correctly on Windows and Linux CI. No action needed — just don't use psycopg async anywhere else in the codebase.

### 🟢 Alembic ruff exclusion (Day 2, resolved)
`alembic/versions/*` excluded from ruff. Standard practice, no action needed.

---

## API & Cost Reference

| Service | Model / Tier | Cost |
|---------|-------------|------|
| OpenAI | `gpt-4.1-mini` | ~$0.0005 per full agent run |
| Voyage AI | `voyage-3` (free tier) | 50M tokens/month free |
| Qdrant | Cloud free tier | 1GB storage, 1 collection |
| Neon | Free tier (prod Postgres) | 0.5 GB storage |
| Upstash | Free tier (Redis) | 10k commands/day |
| Google Map API | Free tier (Day 5 commute) | - |

Total estimated API cost for entire 14-day build: **< $5**.
