from __future__ import annotations

from math import sqrt
import re
from typing import Any

import httpx
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.core.config import settings

logger = structlog.get_logger(__name__)
_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _normalize(vector: list[float]) -> list[float]:
    norm = sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


def _pseudo_embedding(text: str, dim: int = 128) -> list[float]:
    vector = [0.0] * dim
    tokens = _TOKEN_RE.findall(text.lower())
    for token in tokens:
        idx = hash(token) % dim
        vector[idx] += 1.0
    return _normalize(vector)


class MemoryRAGService:
    def __init__(self) -> None:
        self._client: AsyncQdrantClient | None = None
        self._collection_ready = False
        self._vector_size = settings.memory_embedding_dimensions

    def _enabled(self) -> bool:
        return settings.memory_vector_backend.lower() == "qdrant"

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url,
                timeout=10.0,
            )
        return self._client

    async def _ensure_collection(self, vector_size: int) -> None:
        if not self._enabled() or self._collection_ready:
            return
        client = self._get_client()
        collection_name = settings.memory_vector_collection
        collections = await client.get_collections()
        exists = any(item.name == collection_name for item in collections.collections)
        if not exists:
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        self._collection_ready = True
        logger.info("Memory vector collection ready", collection=collection_name, size=vector_size)

    async def embed_text(self, text: str) -> list[float]:
        if settings.mws_stub_mode or not settings.openai_api_key:
            return _pseudo_embedding(text, dim=settings.memory_embedding_dimensions)

        payload = {"model": settings.memory_embedding_model, "input": text}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.openai_api_key}"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{settings.openai_base_url.rstrip('/')}/embeddings", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        vectors = data.get("data", [])
        if not vectors or "embedding" not in vectors[0]:
            raise ValueError("Embedding response has no vector data")
        embedding = vectors[0]["embedding"]
        if not isinstance(embedding, list):
            raise TypeError("Embedding payload is not a list")
        vector = [float(item) for item in embedding]
        return _normalize(vector)

    async def upsert_memory(
        self,
        *,
        memory_id: str,
        user_id: str,
        thread_id: str,
        content: str,
        tags: list[str],
    ) -> None:
        if not self._enabled():
            return
        vector = await self.embed_text(content)
        vector_size = len(vector) or self._vector_size
        await self._ensure_collection(vector_size=vector_size)
        client = self._get_client()
        await client.upsert(
            collection_name=settings.memory_vector_collection,
            points=[
                PointStruct(
                    id=memory_id,
                    vector=vector,
                    payload={"user_id": user_id, "thread_id": thread_id, "tags": tags},
                )
            ],
        )

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
    ) -> dict[str, float]:
        if not self._enabled():
            return {}
        query_vector = await self.embed_text(query)
        await self._ensure_collection(vector_size=len(query_vector) or self._vector_size)
        client = self._get_client()
        hits = await client.search(
            collection_name=settings.memory_vector_collection,
            query_vector=query_vector,
            limit=limit,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))],
            ),
            with_payload=False,
            with_vectors=False,
        )
        result: dict[str, float] = {}
        for hit in hits:
            result[str(hit.id)] = float(hit.score)
        return result


memory_rag_service = MemoryRAGService()
