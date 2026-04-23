from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import uuid4

import structlog

from app.core.config import settings
from app.core.errors import AppError
from app.modules.chat_memory.model import ChatMemory, ChatThreadSummary
from app.modules.chat_memory.rag import memory_rag_service
from app.modules.chat_memory.repository import memory_repository, thread_summary_repository
from app.modules.chat_memory.schemas import MemoryCreateRequest, MemoryRecord, ThreadSummaryRecord

logger = structlog.get_logger(__name__)
_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _to_record(model: ChatMemory) -> MemoryRecord:
    tags = [tag for tag in model.tags.split(",") if tag]
    return MemoryRecord(
        id=model.id,
        user_id=model.user_id,
        thread_id=model.thread_id or "",
        role=model.role,  # type: ignore[arg-type]
        content=model.content,
        source=model.source,
        tags=tags,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_summary_record(model: ChatThreadSummary) -> ThreadSummaryRecord:
    return ThreadSummaryRecord(
        user_id=model.user_id,
        thread_id=model.thread_id,
        summary=model.summary,
        message_count=model.message_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


async def list_memories(user_id: str) -> list[MemoryRecord]:
    rows = await memory_repository.list_by_user(user_id)
    return [_to_record(row) for row in rows]


async def list_thread_memories(user_id: str, thread_id: str, limit: int) -> list[MemoryRecord]:
    bounded_limit = max(1, min(limit, 200))
    rows = await memory_repository.list_by_thread(user_id=user_id, thread_id=thread_id, limit=bounded_limit)
    return [_to_record(row) for row in rows]


async def count_thread_memories(user_id: str, thread_id: str) -> int:
    return await memory_repository.count_by_thread(user_id=user_id, thread_id=thread_id)


async def create_memory(user_id: str, payload: MemoryCreateRequest) -> MemoryRecord:
    model = ChatMemory(
        id=str(uuid4()),
        user_id=user_id,
        thread_id=payload.thread_id,
        role=payload.role,
        content=payload.content,
        source=payload.source,
        tags=",".join(payload.tags),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    created = await memory_repository.insert(model)

    try:
        await memory_rag_service.upsert_memory(
            memory_id=created.id,
            user_id=created.user_id,
            thread_id=created.thread_id,
            content=created.content,
            tags=payload.tags,
        )
    except Exception as exc:
        logger.error("Vector memory upsert failed", memory_id=created.id, error=str(exc))

    return _to_record(created)


async def recall_memories(
    user_id: str,
    query: str,
    top_k: int,
    thread_id: str | None = None,
) -> list[MemoryRecord]:
    bounded_top_k = max(1, min(top_k, 10))
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    lexical_candidates = await memory_repository.search_candidates(
        user_id=user_id,
        limit=max(settings.memory_lexical_candidates, bounded_top_k),
    )

    lexical_scores: dict[str, float] = {}
    candidate_by_id: dict[str, ChatMemory] = {}

    for item in lexical_candidates:
        content_tokens = _tokenize(item.content)
        tags_tokens = _tokenize(item.tags)
        lexical = float(len(query_tokens & content_tokens) + len(query_tokens & tags_tokens))
        if lexical <= 0:
            continue
        if thread_id and item.thread_id == thread_id:
            lexical += settings.memory_thread_boost
        lexical_scores[item.id] = lexical
        candidate_by_id[item.id] = item

    vector_scores: dict[str, float] = {}
    try:
        vector_scores = await memory_rag_service.search(
            user_id=user_id,
            query=query,
            limit=max(bounded_top_k * 4, settings.memory_recall_top_k),
        )
    except Exception as exc:
        logger.error("Vector memory search failed", user_id=user_id, error=str(exc))

    missing_ids = [memory_id for memory_id in vector_scores.keys() if memory_id not in candidate_by_id]
    if missing_ids:
        vector_only_candidates = await memory_repository.get_by_ids(user_id=user_id, memory_ids=missing_ids)
        for item in vector_only_candidates:
            candidate_by_id[item.id] = item

    if not candidate_by_id:
        return []

    max_lexical = max(lexical_scores.values(), default=1.0)
    max_vector = max(vector_scores.values(), default=1.0)
    ranked: list[tuple[float, ChatMemory]] = []

    for memory_id, item in candidate_by_id.items():
        lexical_component = lexical_scores.get(memory_id, 0.0) / (max_lexical or 1.0)
        vector_component = vector_scores.get(memory_id, 0.0) / (max_vector or 1.0)
        thread_boost = settings.memory_thread_boost if thread_id and item.thread_id == thread_id else 0.0
        score = 0.55 * lexical_component + 0.45 * vector_component + thread_boost
        ranked.append((score, item))

    ranked.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
    selected = [item for score, item in ranked if score > 0][:bounded_top_k]
    return [_to_record(row) for row in selected]


async def delete_memory(user_id: str, memory_id: str) -> bool:
    deleted = await memory_repository.delete_by_id(user_id=user_id, memory_id=memory_id)
    if not deleted:
        raise AppError(
            code="memory_not_found",
            message="Memory entry not found",
            details={"user_id": user_id, "memory_id": memory_id},
            status_code=404,
        )
    return True


async def get_thread_summary(user_id: str, thread_id: str) -> ThreadSummaryRecord | None:
    summary = await thread_summary_repository.get(user_id=user_id, thread_id=thread_id)
    if summary is None:
        return None
    return _to_summary_record(summary)


async def upsert_thread_summary(user_id: str, thread_id: str, summary_text: str, message_count: int) -> ThreadSummaryRecord:
    model = ChatThreadSummary(
        id=str(uuid4()),
        user_id=user_id,
        thread_id=thread_id,
        summary=summary_text,
        message_count=message_count,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    updated = await thread_summary_repository.upsert(model)
    return _to_summary_record(updated)
