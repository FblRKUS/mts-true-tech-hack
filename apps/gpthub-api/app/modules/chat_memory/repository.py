from __future__ import annotations

from sqlalchemy import delete, desc, func, select

from app.core.database import db_manager
from app.modules.chat_memory.model import ChatMemory, ChatThreadSummary


class ChatMemoryRepository:
    async def list_by_user(self, user_id: str) -> list[ChatMemory]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ChatMemory).where(ChatMemory.user_id == user_id).order_by(desc(ChatMemory.created_at))
            )
            return list(result.scalars().all())

    async def list_by_thread(self, user_id: str, thread_id: str, limit: int) -> list[ChatMemory]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ChatMemory)
                .where(ChatMemory.user_id == user_id, ChatMemory.thread_id == thread_id)
                .order_by(desc(ChatMemory.created_at))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def count_by_thread(self, user_id: str, thread_id: str) -> int:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(func.count(ChatMemory.id)).where(ChatMemory.user_id == user_id, ChatMemory.thread_id == thread_id)
            )
            return int(result.scalar_one())

    async def insert(self, memory: ChatMemory) -> ChatMemory:
        async with db_manager.get_session() as session:
            session.add(memory)
            await session.flush()
            await session.refresh(memory)
            return memory

    async def get_by_ids(self, user_id: str, memory_ids: list[str]) -> list[ChatMemory]:
        if not memory_ids:
            return []
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ChatMemory).where(ChatMemory.user_id == user_id, ChatMemory.id.in_(memory_ids))
            )
            return list(result.scalars().all())

    async def delete_by_id(self, user_id: str, memory_id: str) -> bool:
        async with db_manager.get_session() as session:
            result = await session.execute(
                delete(ChatMemory).where(ChatMemory.user_id == user_id, ChatMemory.id == memory_id)
            )
            return (result.rowcount or 0) > 0

    async def search_candidates(self, user_id: str, limit: int) -> list[ChatMemory]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ChatMemory).where(ChatMemory.user_id == user_id).order_by(desc(ChatMemory.updated_at)).limit(limit)
            )
            return list(result.scalars().all())


class ChatThreadSummaryRepository:
    async def get(self, user_id: str, thread_id: str) -> ChatThreadSummary | None:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ChatThreadSummary).where(
                    ChatThreadSummary.user_id == user_id,
                    ChatThreadSummary.thread_id == thread_id,
                )
            )
            return result.scalar_one_or_none()

    async def upsert(self, summary: ChatThreadSummary) -> ChatThreadSummary:
        async with db_manager.get_session() as session:
            existing_result = await session.execute(
                select(ChatThreadSummary).where(
                    ChatThreadSummary.user_id == summary.user_id,
                    ChatThreadSummary.thread_id == summary.thread_id,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing is None:
                session.add(summary)
                await session.flush()
                await session.refresh(summary)
                return summary
            existing.summary = summary.summary
            existing.message_count = summary.message_count
            await session.flush()
            await session.refresh(existing)
            return existing


memory_repository = ChatMemoryRepository()
thread_summary_repository = ChatThreadSummaryRepository()
