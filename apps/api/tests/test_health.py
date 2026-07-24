"""Integration test for GET /health.

Requires Docker services (postgres, redis) to be running.
Uses the real database and redis connections — no mocks.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_all_services_up(client: AsyncClient) -> None:
    """With Docker infra running, /health returns 200 with both checks ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"
