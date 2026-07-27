"""Day 2 end-to-end smoke-test.

Run from apps/api/:
    uv run python scripts/verify_day2.py

Prints PASS/FAIL for each check.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import traceback
from collections.abc import Callable

import psycopg
import voyageai
from qdrant_client import QdrantClient

from src.config import settings

EXPECTED_TABLES = {"listings", "user_requests", "agent_runs", "recommendations", "user_profiles"}
COLLECTION_NAME = "neighborhoods"
VOYAGE_MODEL = "voyage-3"
SCORE_THRESHOLD = 0.5

results: list[tuple[str, bool, str]] = []


def check(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        results.append((name, True, ""))
    except Exception:
        results.append((name, False, traceback.format_exc().strip().splitlines()[-1]))


# ---------------------------------------------------------------------------
# Check 1: Postgres connection
# ---------------------------------------------------------------------------
def chk_postgres_connection() -> None:
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg.connect(url, connect_timeout=5)
    conn.execute("SELECT 1")
    conn.close()


# ---------------------------------------------------------------------------
# Check 2: All 5 tables exist
# ---------------------------------------------------------------------------
def chk_tables_exist() -> None:
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    found = {r[0] for r in rows}
    missing = EXPECTED_TABLES - found
    if missing:
        raise AssertionError(f"Missing tables: {missing}")


# ---------------------------------------------------------------------------
# Check 3: Listings has >= 200 rows
# ---------------------------------------------------------------------------
def chk_listings_count() -> None:
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(url) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    if count < 200:
        raise AssertionError(f"Only {count} listings (expected >= 200)")


# ---------------------------------------------------------------------------
# Check 4: Qdrant 'neighborhoods' collection exists with >= 15 vectors
# ---------------------------------------------------------------------------
def chk_qdrant_collection() -> None:
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    collections = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in collections:
        raise AssertionError(f"Collection '{COLLECTION_NAME}' not found in Qdrant")
    info = client.get_collection(COLLECTION_NAME)
    count = info.points_count
    if count is None or count < 15:
        raise AssertionError(f"Collection has only {count} vectors (expected >= 15)")


# ---------------------------------------------------------------------------
# Check 5: Semantic query returns at least 1 result with score > 0.5
# ---------------------------------------------------------------------------
def chk_semantic_query() -> None:
    if not settings.voyage_api_key:
        raise AssertionError("VOYAGE_API_KEY not set")
    vo = voyageai.Client(api_key=settings.voyage_api_key)
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )

    q_result = vo.embed(
        ["safe quiet neighborhood near university"],
        model=VOYAGE_MODEL,
        input_type="query",
    )
    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=q_result.embeddings[0],
        limit=3,
    ).points

    if not hits:
        raise AssertionError("No results returned from semantic query")
    if hits[0].score < SCORE_THRESHOLD:
        raise AssertionError(f"Top result score {hits[0].score:.4f} < threshold {SCORE_THRESHOLD}")


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Day 2 smoke-test")
    print("=" * 60)

    check("Postgres connection", chk_postgres_connection)
    check("All 5 tables exist", chk_tables_exist)
    check("Listings table has >= 200 rows", chk_listings_count)
    check("Qdrant 'neighborhoods' collection (>= 15 vectors)", chk_qdrant_collection)
    check("Semantic query returns score > 0.5", chk_semantic_query)

    print()
    all_pass = True
    for name, passed, err in results:
        status = "PASS" if passed else "FAIL"
        line = f"  [{status}] {name}"
        if not passed:
            line += f"\n         {err}"
            all_pass = False
        print(line)

    print()
    if all_pass:
        print("All checks passed.")
    else:
        print("One or more checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
