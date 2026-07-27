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

### Day 7 — Recommendation Agent + Memory + Week 1 Milestone
- Recommendation agent (`src/agents/recommendation.py`): real ranked top-3 via tool-calling, rationale cites specific agent findings (Budget/Risk/Neighborhood/Commute), trade-off narrative synthesizes across candidates
- `AsyncPostgresSaver` used for the LangGraph checkpointer (not sync `PostgresSaver` — `ainvoke` requires `aget_tuple`, sync version raises `NotImplementedError`)
- `get_checkpointer()` is an async context manager; `from_conn_string` owns the connection lifetime
- `WindowsSelectorEventLoopPolicy` set in the CLI — psycopg async rejects ProactorEventLoop (same root cause as Day 1's health-check workaround, different code path)
- `Providers` dataclass (`src/agents/graph.py`) bundles DBListingsProvider/QdrantVectorSearchProvider/GoogleMapsCommuteProvider into one constructor arg
- Long-term memory (`src/memory/long_term.py`): extracts durable preferences via tool-calling after each run, upserts to `user_profiles`, wrapped in try/except so failures don't crash the pipeline
- End-to-end CLI (`scripts/run_pipeline.py`): two-turn session proven — Turn 1 (tight filters, 1 candidate) → Turn 2 (relaxed filters, same thread_id, 5 candidates) — session continuity confirmed via LangGraph checkpointer
- Truncated `listing_id` resolution: LLM sometimes returns UUID prefixes instead of full IDs; added a matcher + single-candidate short-circuit rather than silently falling back
- Unit tests: 4 passing for Recommendation agent (mocked)
- Full suite: 40 tests passing
- Session cost: $0.004005 across both turns (well under the $0.01 target)
- `UserProfile` after Turn 2 correctly captured: `budget_ceiling=1200`, `max_acceptable_commute_minutes=20`, `prefers_laundry=false`, `prefers_pet_friendly=false`

### Day 8 — FastAPI Endpoints + Celery + SSE Streaming
- `POST /api/requests`: validates input, inserts `UserRequest` row, enqueues `run_pipeline_task.delay()`, returns 202 with `request_id` in ~120ms (doesn't block on the graph)
- `GET /api/requests/{id}/stream`: SSE endpoint via `sse-starlette`, subscribes to Redis pub/sub channel `run_progress:{request_id}`, emits `agent_complete` events per node and a final `done` event with the full recommendation
- `GET /api/requests/{id}`: returns persisted status/recommendation from Postgres
- SSE late-join handling: if a client connects after the run already finished, the stream reads final status from Postgres instead of hanging on an empty Redis channel
- Celery task (`src/worker/tasks.py`) uses `stream_mode="updates"` when invoking the graph so progress can be published per-node in real time
- Persistence: one `AgentRun` row per trace event + one `Recommendation` row per completed request
- `engine.dispose()` called at the start of each Celery task run — each `asyncio.run()` gets a fresh event loop, and pooled asyncpg connections can't cross loops
- Windows Celery workaround: `--pool=solo` + unique worker node name (`-n day8@%h`) — prefork pool was unreliable locally, duplicate nodenames stole tasks during smoke testing
- Integration tests patch `.delay` with an in-loop async stub rather than using `task_always_eager`, to avoid nested `asyncio.run()` / asyncpg event-loop conflicts
- Full manual curl verification: POST → 202 in ~120ms, SSE stream shows all 7 agent-complete events in order + done, GET matches stream output, 404 on bad ID, two sequential requests both completed independently
- Unit + integration tests: 44 passing total
- Full suite: 44 tests passing, ruff clean, mypy clean (57 source files)

### Day 9 — Auth, Recommendation Hardening, Rate Limiting
- Clerk JWT auth (`src/api/auth.py`): verifies Bearer tokens against JWKS, returns `sub` claim as `user_id`, 401 on any failure (raw JWT errors logged server-side, not leaked to client)
- All request routes now require auth: `POST /api/requests`, `GET /api/requests/{id}`, `GET /api/requests/{id}/stream`, new `GET /api/requests` (paginated list)
- Ownership checks: a user cannot view another user's request (403), confirmed via `test_auth_isolation.py`
- **Recommendation hard-constraint fix**: violations (`meets_constraint=False`, `is_affordable=False`) are computed in Python — not left to the LLM — and passed into the prompt explicitly per candidate; LLM must name the violation in `rationale`; a Python-level clamp caps `score` at 0.5 for any constraint-violating candidate regardless of what the LLM returns. Verified: real case showed LLM returning 0.95, code correctly clamped to 0.5, rationale explicitly stated "exceeds your 20-minute commute limit by 62 minutes"
- Redis-based rate limiting (`slowapi`, keyed by `user_id` not IP): confirmed 5th request in a 5/hour test window returns 429
- Input validation hardening: max lengths on `free_text`/`anchor_address`, bounds on `budget_max`/`max_commute_minutes`, basic prompt-injection string rejection on `free_text`
- OpenAPI docs confirmed: `HTTPBearer` security scheme shows on protected routes in `/docs`
- Dev tooling: `scripts/make_dev_token.py` generates local HS256 test JWTs so auth can be tested without a live Clerk account (`CLERK_JWKS_URL=local` env override)
- Full suite: 48 tests passing, ruff clean, mypy clean (59 source files)

### Day 10 — Frontend Scaffold + Request Form
- Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui scaffolded at `apps/web`
- Clerk auth wired on frontend: sign-in/sign-up pages, `middleware.ts` protecting all routes except landing page, `<UserButton />` for sign-out
- Frontend uses the **same Clerk application** as the backend (shared JWKS/issuer) — confirmed real Clerk RS256 tokens verify successfully against the backend
- API client (`lib/api-client.ts`): typed fetch wrapper attaching `Authorization: Bearer {token}` from Clerk session, typed `ApiError` on failures
- Request form (`app/request/page.tsx`): react-hook-form + zod, validation rules mirror backend exactly (budget > 0 and < 100000, anchor address 3–200 chars, commute 1–180 min, free text ≤ 500 chars)
- Form submission → `POST /api/requests` → 202 → redirects to `/request/{id}` placeholder page
- Confirmed end-to-end: real Clerk user signs up → submits form → Postgres `UserRequest.user_id` matches the real Clerk `user_...` ID, not a dev-token subject
- Invalid input (budget = -5) blocked client-side with zero network calls
- Signed-out access to `/request` redirects to `/sign-in` (middleware protection confirmed)

### Day 11 — Live Agent Execution Visualization
- SSE client hook (`hooks/use-request-stream.ts`) using `@microsoft/fetch-event-source` — Clerk Bearer token attached via header, no new backend token endpoint needed
- `AgentGraph` component (`components/agent-graph.tsx`): all 8 agents shown with idle/skipped/running/done states, skipped agents visually distinct with a badge
- `src/worker/tasks.py` updated: `agent_complete` events now include per-agent one-line summaries (e.g., "Found 5 candidates", "Checked walk times for 5 listing(s)") and the planner event includes `selected_agents` + `reasoning`
- Confirmed routing is visibly different between a full-constraint request (5 agents) and a minimal request (2 agents) — concrete proof of dynamic routing for the demo video
- Late-join handling confirmed: reconnecting to a completed request immediately returns the `done` event with full recommendation
- `/request/[id]/results` page created as a Day 12 placeholder (raw JSON stopgap)
- Full suite: 52 tests passing (backend), `npm run build` clean (frontend)

### Day 12 — Results UI, Map, History, Observability Dashboard
- Backend schema extensions: enriched `ranked_listings` at persist time + `result_context` (anchor lat/lon) — `GET /api/requests/{id}` now returns comparison/map fields directly, not faked on the frontend
- Affordability fallback: when the Planner skips the Budget agent, price vs `budget_max` fills the trade-off table (applied retroactively via GET for older rows too)
- Results page (`app/request/[id]/results/page.tsx`): ranked cards, trade-off comparison table, constraint-violation badges (score ≤ 0.5 flagged)
- Map view (`components/results-map.tsx`): Leaflet + OpenStreetMap tiles (`react-leaflet@4.2.1`, pinned for React 18 compatibility — v5 needs React 19), anchor + candidate pins with popups
- History page (`app/history/page.tsx`): paginated list working with `total`/`limit`/`offset`
- Observability dashboard (`app/admin/observability/page.tsx`) + backend endpoint `GET /api/admin/observability/summary`: aggregates last 50 requests (`OBSERVABILITY_RECENT_REQUEST_LIMIT`), shows per-agent avg latency/cost/call-count and total cost — confirmed real data, not mocked (e.g., neighborhood agent avg_latency_ms=11205.5, budget avg_cost_usd=0.00143)
- Stale-pending detection: requests pending > 90s (`stale_pending_seconds`) surfaced in both the observability panel and history page (`is_stale: true`); verified via a backdated pending row (~135s)
- No admin role gate yet — observability dashboard is reachable by any authenticated user (documented as a future gap, not fixed today)
- Full suite: 53 tests passing, ruff clean, mypy clean

### Day 13 — Evaluation Harness + Testing + CI Hardening
- Day 12 carry-over resolved as a **false alarm**: `walk_minutes=24.9` against `max_commute_minutes=25` correctly does not violate the constraint (24.9 < 25). Confirmed the clamp logic is correct by re-testing with `max_commute_minutes=20`, where all commute violators correctly clamped to `score<=0.5`
- Persistence regression test added: `test_persisted_ranked_listing_score_respects_clamp` — asserts the clamp holds in the database, not just in-memory
- Golden dataset: 40 hand-written diverse requests in `eval/golden_dataset.jsonl`, labeled with `expected_agents` and `expects_hard_constraint_satisfied`
- Eval runner (`eval/run_eval.py`): routing F1, constraint-satisfaction match rate, LLM-as-judge quality/faithfulness score (checked against raw agent findings, not just "does this sound good")
- **Full eval results (40 examples):** routing F1 = 0.9922, constraint match rate = 0.8750, judge score = 3.63/5, total cost $0.15, wall clock 514s
- CI eval gate: runs a small subset (`--ci --skip-judge`) on every PR, thresholds set at routing F1 ≥ 0.70 and constraint match ≥ 0.65 (deliberately below the real full-eval numbers to leave headroom for dataset noise)
- **Regression proof verified**: baseline F1=0.986 → broken (commute rule disabled) F1=0.853 → restored F1=0.986. Used the commute rule instead of pet-friendly (pet-friendly is a listing filter, not a routing decision, so it doesn't affect the routing-accuracy metric)
- Bug found and fixed via the eval harness itself: Neighborhood agent's LLM occasionally returned `safety_score`/`noise_score = 0`, outside the valid 1–5 range, crashing the eval — added a clamp in `neighborhood.py`
- Coverage: 68.13% (`pytest-cov`, `fail_under=55`)
- Full suite: 60 tests passing, ruff clean, mypy clean

### Day 13 — Evaluation Harness + Testing + CI Hardening
- Day 12 carry-over resolved as a **false alarm**: `walk_minutes=24.9` against `max_commute_minutes=25` correctly does not violate the constraint (24.9 < 25). Confirmed the clamp logic is correct by re-testing with `max_commute_minutes=20`, where all commute violators correctly clamped to `score<=0.5`
- Persistence regression test added: `test_persisted_ranked_listing_score_respects_clamp` — asserts the clamp holds in the database, not just in-memory
- Golden dataset: 40 hand-written diverse requests in `eval/golden_dataset.jsonl`, labeled with `expected_agents` and `expects_hard_constraint_satisfied`
- Eval runner (`eval/run_eval.py`): routing F1, constraint-satisfaction match rate, LLM-as-judge quality/faithfulness score (checked against raw agent findings, not just "does this sound good")
- **Full eval results (40 examples):** routing F1 = 0.9922, constraint match rate = 0.8750, judge score = 3.63/5, total cost $0.15, wall clock 514s
- CI eval gate: runs a small subset (`--ci --skip-judge`) on every PR, thresholds set at routing F1 ≥ 0.70 and constraint match ≥ 0.65 (deliberately below the real full-eval numbers to leave headroom for dataset noise)
- **Regression proof verified**: baseline F1=0.986 → broken (commute rule disabled) F1=0.853 → restored F1=0.986. Used the commute rule instead of pet-friendly (pet-friendly is a listing filter, not a routing decision, so it doesn't affect the routing-accuracy metric)
- Bug found and fixed via the eval harness itself: Neighborhood agent's LLM occasionally returned `safety_score`/`noise_score = 0`, outside the valid 1–5 range, crashing the eval — added a clamp in `neighborhood.py`
- Coverage: 68.13% (`pytest-cov`, `fail_under=55`)
- Full suite: 60 tests passing, ruff clean, mypy clean
---

## Not Yet Built

| Day | What |
|-----|------|
| Day 14 | Production deployment + LangSmith tracing + polished README + demo video |

---

## Known Issues & Notes to Resolve Later
### Day 13
- Constraint match rate is 87.5%, not 100% — 5 of 40 golden examples don't match expected pass/fail behavior. Worth a quick manual review of which ones before writing the Day 14 README, to understand whether these are dataset labeling issues or genuine system limitations, and report the number honestly either way.
- Judge score (3.63/5) is decent but not high — don't overstate this in the README. Pair it with the strong routing F1 rather than letting one number imply the other.
- Golden dataset labels were tuned for the seed geography (UT Austin walks are rarely ≤15–20 min given the synthetic listing distribution) — this means the dataset is somewhat overfit to this specific seed data and city; worth a one-line disclaimer in the README if claiming general system quality.
- CI eval gate thresholds (0.70 / 0.65) are set well below the real full-eval numbers (0.99 / 0.875) — this was a deliberate choice to avoid CI flakiness from a small subset, but means CI passing doesn't prove the system is at its best; the full eval report is the real quality signal.

### Day 12
- 🟡 **Unconfirmed possible regression:** verification result showed a #1-ranked candidate with `walk_minutes=24.9` but `score=1.0` and `constraint_flag=false`. If the source request had a `max_commute_minutes` constraint (most smoke tests used 20 min), this should have been clamped to `score<=0.5` per the Day 9 fix. Need to confirm whether that specific request actually included a commute constraint — if it did, the clamp is not firing correctly on this code path (possibly related to the new result-enrichment/persistence logic added today) and must be fixed before Day 13, since constraint-satisfaction is a core eval metric.
- Day 11 stuck-pending issue is still only partially resolved — detection/visibility exists (staleness badges), but no actual fix (Celery task time limits or a periodic sweep job to auto-fail stale requests). Still open.
- No real admin role system — anyone authenticated can view `/admin/observability`. Acceptable for a portfolio demo, but worth a one-line disclaimer in the Day 14 README.
- `react-leaflet` pinned to `4.2.1` because v5 requires React 19 — revisit if the frontend is upgraded later.
### Day 11
- 🟡 **No error signal when the Celery worker itself is down**, only when the pipeline fails mid-run. If the worker isn't running, a submitted request stays at `status="pending"` indefinitely with no `error` SSE event — nothing ever runs to publish one. The UI's error-state handling works correctly for pipeline failures, but there's currently no timeout/staleness detection for "the task was never picked up at all." Worth adding either a Celery task time limit + a periodic sweep marking stale `pending` requests as `failed`, or a simple "still waiting after N seconds, something may be wrong" banner on the frontend. Decide during Day 12 (observability) or flag explicitly for later hardening — don't let this ship silently to Day 14.
- Mid-run page refresh can't replay past pub/sub events (Redis pub/sub isn't a durable log, this is inherent to the Day 8 design) — a completed late-join works fine, but refreshing mid-run only picks up from that point forward. A banner is shown to make this visible to the user rather than looking broken. Acceptable trade-off, just document it in the Day 14 README.
- "View full results" currently links to a placeholder page showing raw recommendation JSON — Day 12 replaces this with the real results UI.

### Day 10
- Headless/scripted Clerk sign-up is blocked by Cloudflare Turnstile ("verify you are human"). Verification today used a manually created test user + Clerk sign-in token flow instead. This is fine for manual dev testing but means Day 13's eval harness (if it ever needs to simulate multiple users) cannot use scripted sign-up — it should create test users via Clerk's backend API/admin endpoints instead, not the sign-up UI flow.
- Duplicate/placeholder Clerk keys were found and cleaned out of `.env.local` during this session — worth double-checking `.env.local` has exactly one set of real Clerk keys before Day 14 deployment config is finalized.

**Day 9 carry-over — resolved, not a real bug:**
- The earlier `401` / `"alg value is not allowed"` error was caused by the API process inheriting a stray `CLERK_JWKS_URL=local` env var from the shell (leftover from Day 9's HS256 dev-token testing), not an actual JWKS/RS256 verification bug. After clearing the env var and restarting with the real Clerk JWKS/issuer values, RS256 verification succeeded cleanly. Lesson: when switching between dev-token (HS256) and real-Clerk (RS256) testing, always start a fresh shell/terminal to avoid inherited env vars silently overriding `.env`.

### Day 9
- 🟡 All Day 9 verification used the local HS256 dev-token path, not real Clerk-issued RS256 tokens. The JWKS-fetch-and-cache code path is implemented but not yet exercised against a live Clerk instance. Do a one-time manual test with a real Clerk token before or during Day 10, since the frontend will produce real tokens and any RS256/JWKS bug should surface before it's tangled up with frontend integration debugging.
- The hard-constraint clamp (Day 9's main fix) was verified by calling the Recommendation agent directly with a mocked LLM, not through a full live Celery + real-LLM run. The logic is deterministic Python so risk is low, but a full end-to-end sanity check is worth doing before Day 13's eval harness relies on this behavior.
- Rate limit test used a temporarily lowered `RATE_LIMIT_PER_USER_PER_HOUR=5` — remember to confirm `.env` has the real value (20/hour per the roadmap default) before Day 14 deployment.
- `.env` now holds both real Clerk production-style values and is overridden locally for HS256 smoke testing — make sure the real Clerk values are what's used in the Day 14 deployed environment, not the local override.

### Day 8
- 🟡 `--pool=solo` means local dev Celery runs tasks sequentially, not concurrently. The Day 8 "concurrent requests" check only proved both requests *eventually* succeed, not that they ran in parallel. Production deployment (Day 14, Linux) should use the `prefork` pool — test real concurrency once deployed, don't assume it from local Windows dev.
- 🟡 The automated integration test (`test_requests_api.py`) bypasses the real Redis broker → Celery worker path by patching `.delay()`. It proves the API layer's logic is correct but does **not** prove the real async queue/pub-sub path works end-to-end — only the manual curl testing did that. Be precise about this distinction if it comes up in interviews or the Day 14 README's testing section.
- Candidate cap (~5 closest to UT) is still hardcoded in the Celery task for cost control, carried over from Day 5–7. Day 9 or later should make this configurable rather than hardcoded, or explicitly document it as an intentional demo-scale limit.
- One `AgentRun` row per trace event (not one row per full run) — this shape needs to be known when building Day 12's observability dashboard (it'll need to `GROUP BY request_id` to get per-run totals).

### Day 7
- 🔴 **Recommendation does not flag hard-constraint violations.** Turn 1's only candidate has an 82.6-minute walk time against a stated 20-minute max, yet it was ranked #1 with score=0.70 and no explicit warning in the rationale — the LLM averaged it into a general score instead of treating it as disqualifying. This will directly fail Day 13's eval harness (constraint-satisfaction metric). Resolve before Day 13, ideally by Day 9: either (a) have the Critic refuse to approve when the only candidate(s) violate a hard constraint and note it explicitly, or (b) require the Recommendation prompt to explicitly call out any unmet hard constraint per candidate rather than silently blending it into the score.
- Truncated `listing_id` matching (judgment call #6) is a workaround, not a real fix — the LLM should be constrained (via tool schema description or stricter prompting) to always return full listing IDs. Worth tightening during Day 9 hardening.
- `AsyncPostgresSaver` requirement means any future code touching the checkpointer must stay in the async path — don't introduce a sync Postgres call near the graph invocation.
- Smoke/demo runs still cap candidates at ~5 closest to UT for cost control — fine for CLI demos, but Day 8's API layer should decide explicitly whether to keep this cap or let real usage set the candidate pool size.

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
