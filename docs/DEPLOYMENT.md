# Day 14 Production Deployment Checklist

This file is a production runbook. Do not commit real secrets or pasted dashboard credentials.

## Cloud Resources

| Service | Create | Required environment |
| --- | --- | --- |
| Neon | Free Postgres project | `DATABASE_URL` |
| Upstash | Redis instance | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| Qdrant Cloud | Free vector cluster | `QDRANT_URL`, optional `QDRANT_API_KEY` if enabled later |
| Railway | API service | all backend env vars, `PROCESS_TYPE=api` |
| Railway | Celery worker service | same backend env vars, `PROCESS_TYPE=worker` |
| Vercel | Next.js app from `apps/web` | frontend Clerk keys, `NEXT_PUBLIC_API_BASE_URL` |
| LangSmith | Project + API key | `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` |
| Clerk | Production app | API JWKS/issuer and frontend publishable/secret keys |

## Backend Secrets

Set these through the platform secret manager:

```text
ENVIRONMENT=production
DATABASE_URL=...
REDIS_URL=...
CELERY_BROKER_URL=...
CELERY_RESULT_BACKEND=...
QDRANT_URL=...
OPENAI_API_KEY=...
VOYAGE_API_KEY=...
GOOGLE_MAPS_API_KEY=...
CLERK_JWKS_URL=...
CLERK_ISSUER=...
RATE_LIMIT_PER_USER_PER_HOUR=20
CORS_ORIGINS=https://<vercel-domain>
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=housing-decision-system
```

Use production Clerk keys where possible (`pk_live_` / `sk_live_`). Do not deploy with the local `CLERK_JWKS_URL=local` dev-token path.

## Database Migration and Seed

Run against production after `DATABASE_URL`, `QDRANT_URL`, and API keys are set locally in a temporary shell:

```bash
cd apps/api
uv run alembic upgrade head
uv run python scripts/seed_db.py
uv run python scripts/seed_vector_db.py
```

Confirm:

- Postgres contains 200 seeded listings.
- Qdrant has the `neighborhoods` collection.
- Qdrant contains the seeded neighborhood vectors.

## Railway Shape

Production is deployed on Railway as two services:

- API: `https://housing-decision-system-production.up.railway.app`
- Worker: separate Railway service using the same Docker image.

Both services deploy `apps/api` as the root with its Dockerfile. The Docker `CMD` switches on `PROCESS_TYPE`:

```bash
railway up apps/api --path-as-root --service <api-service> --environment production
railway up apps/api --path-as-root --service <worker-service> --environment production
```

The worker uses Linux Celery prefork with `CELERY_CONCURRENCY=2`. Production logs confirmed `concurrency: 2 (prefork)`.

Upstash Redis uses two URL forms:

- `REDIS_URL`: `rediss://...?...ssl_cert_reqs=required` for `redis.asyncio`.
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`: `rediss://...?...ssl_cert_reqs=CERT_REQUIRED` for Celery.

## Frontend Deployment

Deploy `apps/web` to Vercel and set:

```text
NEXT_PUBLIC_API_BASE_URL=https://<api-domain>
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=...
CLERK_SECRET_KEY=...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/request
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/request
```

## Production Smoke Test

Run this against the live URLs, not localhost:

1. Sign up as a new user.
2. Submit a full-constraint request.
3. Watch the live agent visualization.
4. Open results, map, ranked cards, and trade-off table.
5. Open history and confirm the request is present.
6. Open observability and confirm the request contributes to cost/latency numbers.
7. Submit a second minimal request and confirm fewer specialists run.

Record both production `request_id` values.

## LangSmith Verification

Submit one production request with tracing enabled. Confirm a LangSmith trace appears under `LANGCHAIN_PROJECT`. Save the trace link or screenshot for the README/demo assets.

## Concurrency Verification

This resolves the Day 8 open question. Submit two production requests at the same time, then prove overlap from one of:

- worker logs with overlapping task start/finish timestamps;
- `AgentRun.started_at` / `finished_at` rows for different request IDs that overlap;
- hosting metrics showing concurrent worker processes.

If tasks only run sequentially, leave the limitation open and document the worker/process configuration.

## Release Tag

Only tag after production smoke, tracing, concurrency check, README review, and local tests pass.

```bash
git tag -a v1.0 -m "Multi-Agent Housing Decision System v1.0 - full 14-day build complete"
git push origin v1.0
```
