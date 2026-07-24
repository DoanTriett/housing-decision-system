"""Vector search adapter — abstract interface + Qdrant + Voyage AI implementation."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import voyageai
from qdrant_client import QdrantClient

from src.config import settings
from src.schemas.agents import NeighborhoodDoc

VOYAGE_MODEL = "voyage-3"


class VectorSearchProvider(ABC):
    """Abstract interface for neighborhood document retrieval."""

    @abstractmethod
    async def search(self, query: str, top_k: int) -> list[NeighborhoodDoc]:
        """Return top-k neighborhood docs for a natural-language query."""


class QdrantVectorSearchProvider(VectorSearchProvider):
    """Embed with Voyage AI voyage-3, then query Qdrant."""

    def __init__(self, client: QdrantClient, collection: str) -> None:
        self._client = client
        self._collection = collection
        self._voyage = voyageai.Client(api_key=settings.voyage_api_key)  # type: ignore[attr-defined]
        # Cache identical (query, top_k) within a process — agents call search per
        # candidate with the same preference query.
        self._cache: dict[tuple[str, int], list[NeighborhoodDoc]] = {}

    def _embed_query(self, query: str) -> list[float]:
        result = self._voyage.embed([query], model=VOYAGE_MODEL, input_type="query")
        return list(result.embeddings[0])

    def _query_qdrant(self, vector: list[float], top_k: int) -> list[NeighborhoodDoc]:
        hits = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
        ).points

        docs: list[NeighborhoodDoc] = []
        for hit in hits:
            payload = hit.payload or {}
            docs.append(
                NeighborhoodDoc(
                    neighborhood=str(payload.get("neighborhood", "")),
                    content=str(payload.get("content", "")),
                    score=float(hit.score or 0.0),
                )
            )
        return docs

    async def search(self, query: str, top_k: int) -> list[NeighborhoodDoc]:
        cache_key = (query, top_k)
        if cache_key in self._cache:
            return self._cache[cache_key]

        vector = await asyncio.to_thread(self._embed_query, query)
        docs = await asyncio.to_thread(self._query_qdrant, vector, top_k)
        self._cache[cache_key] = docs
        return docs
