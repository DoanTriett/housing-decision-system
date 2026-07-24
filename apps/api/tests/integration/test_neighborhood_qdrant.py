"""Integration tests for Qdrant neighborhood vector search."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from src.config import settings
from src.tools.vector_search import QdrantVectorSearchProvider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safe_quiet_query_returns_scored_docs() -> None:
    client = QdrantClient(url=settings.qdrant_url)
    provider = QdrantVectorSearchProvider(client=client, collection=settings.qdrant_collection)

    docs = await provider.search("safe quiet area near university", top_k=3)

    assert len(docs) >= 1
    assert docs[0].score > 0.4
    assert docs[0].neighborhood.strip() != ""
    assert docs[0].content.strip() != ""
