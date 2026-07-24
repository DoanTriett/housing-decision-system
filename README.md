# Multi-Agent Housing Decision System

> A decision-intelligence system where a planner agent dynamically routes a housing request to specialist agents, runs them in parallel, reflects via a critic agent, and produces a ranked recommendation with explicit trade-off reasoning.

---

## Day 1 — What exists today

- **FastAPI** backend (`apps/api`) with a real `/health` endpoint that checks Postgres + Redis connectivity
- **Docker Compose** infra: Postgres 16, Redis 7, Qdrant (all with healthchecks)
- **Typed config** via `pydantic-settings`, **structured logging** via `structlog`
- **Linting/typing**: `ruff` + `mypy` (strict), wired to `pre-commit`
- **Integration test** for `/health`
- **GitHub Actions CI**: lint → type-check → test

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.12 |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.11 |
| Docker + Docker Compose | ≥ 24 |

---

## Quick start

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd housing-decision-system

# Copy env template and set local values (defaults work out of the box)
cp .env.example apps/api/.env
```

### 2. Start infrastructure

```bash
docker compose -f infra/docker-compose.yml up -d
# Wait for all three services to be healthy (~20 s)
docker compose -f infra/docker-compose.yml ps
```

### 3. Install dependencies and run the API

```bash
cd apps/api
uv sync
uv run uvicorn src.main:app --reload
```

The API is now live at `http://localhost:8000`.

### 4. Verify the health endpoint

```bash
# Healthy — all services up
curl http://localhost:8000/health

# Expected: HTTP 200
# {"status":"ok","checks":{"database":{"status":"ok"},"redis":{"status":"ok"}}}

# Simulate a failure — stop postgres, hit health again
docker compose -f infra/docker-compose.yml stop postgres
curl http://localhost:8000/health

# Expected: HTTP 503
# {"status":"degraded","checks":{"database":{"status":"error","detail":"..."},"redis":{"status":"ok"}}}
```

---

## Development

### Linting & type-checking

```bash
cd apps/api
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy src              # type-check
```

### Tests

```bash
cd apps/api
# Requires Docker infra running (integration test hits real DB + Redis)
uv run pytest -v
```

### Pre-commit hooks

```bash
pip install pre-commit        # or: uv tool install pre-commit
pre-commit install
pre-commit run --all-files
```

### Build the Docker image

```bash
docker build -f apps/api/Dockerfile apps/api
```

---

## Project structure

```
housing-decision-system/
├── apps/api/
│   ├── src/
│   │   ├── __init__.py
│   │   ├── config.py        # pydantic-settings configuration
│   │   └── main.py          # FastAPI app + /health endpoint
│   ├── tests/
│   │   ├── conftest.py      # AsyncClient fixture
│   │   └── test_health.py   # /health integration test
│   ├── pyproject.toml       # uv project, ruff/mypy/pytest config
│   ├── uv.lock
│   └── Dockerfile           # multi-stage uv build
├── infra/
│   └── docker-compose.yml   # postgres, redis, qdrant
├── .github/
│   └── workflows/
│       └── ci.yml           # lint → type-check → test
├── .pre-commit-config.yaml
├── .env.example
├── .gitignore
└── README.md
```
