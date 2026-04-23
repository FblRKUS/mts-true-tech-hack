from fastapi import APIRouter

from app.modules.chat_memory.schemas import (
    MemoryCreateRequest,
    MemoryDeleteResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryRecord,
)
from app.modules.chat_memory.service import create_memory, delete_memory, list_memories, recall_memories

router = APIRouter(prefix="/features/chat-memory", tags=["feature:chat-memory"])


@router.get(
    "/{user_id}",
    response_model=list[MemoryRecord],
    summary="List user memories",
    description="Возвращает все записи памяти пользователя, отсортированные по времени.",
)
async def get_memories(user_id: str) -> list[MemoryRecord]:
    return await list_memories(user_id)


@router.post(
    "/{user_id}",
    response_model=MemoryRecord,
    summary="Create memory record",
    description="Сохраняет новую запись долговременной памяти для пользователя.",
)
async def add_memory(user_id: str, payload: MemoryCreateRequest) -> MemoryRecord:
    return await create_memory(user_id, payload)


@router.post(
    "/{user_id}/recall",
    response_model=MemoryRecallResponse,
    summary="Recall relevant memories",
    description="Возвращает top-k релевантных записей памяти по текстовому запросу.",
)
async def recall_memory(user_id: str, payload: MemoryRecallRequest) -> MemoryRecallResponse:
    return MemoryRecallResponse(
        query=payload.query,
        items=await recall_memories(
            user_id=user_id,
            query=payload.query,
            top_k=payload.top_k,
            thread_id=payload.thread_id,
        ),
    )


@router.delete(
    "/{user_id}/{memory_id}",
    response_model=MemoryDeleteResponse,
    summary="Delete memory record",
    description="Удаляет запись памяти по идентификатору.",
)
async def remove_memory(user_id: str, memory_id: str) -> MemoryDeleteResponse:
    return MemoryDeleteResponse(deleted=await delete_memory(user_id=user_id, memory_id=memory_id), memory_id=memory_id)
