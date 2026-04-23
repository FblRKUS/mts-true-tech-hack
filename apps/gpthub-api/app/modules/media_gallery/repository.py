from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, or_, select

from app.core.database import db_manager
from app.modules.media_gallery.model import MediaGalleryItem


class MediaGalleryRepository:
    async def list_items(
        self,
        owner_id: str,
        *,
        page: int,
        page_size: int,
        kind: str | None = None,
        search: str | None = None,
        model_id: str | None = None,
        chat_id: str | None = None,
        thread_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[MediaGalleryItem], int]:
        filters = [MediaGalleryItem.owner_id == owner_id]
        if kind:
            filters.append(MediaGalleryItem.kind == kind)
        if model_id:
            filters.append(MediaGalleryItem.model_id == model_id)
        if chat_id:
            filters.append(MediaGalleryItem.chat_id == chat_id)
        if thread_id:
            filters.append(MediaGalleryItem.thread_id == thread_id)
        if created_from is not None:
            filters.append(MediaGalleryItem.created_at >= created_from)
        if created_to is not None:
            filters.append(MediaGalleryItem.created_at <= created_to)
        if search:
            term = f"%{search}%"
            filters.append(
                or_(
                    MediaGalleryItem.prompt_text.ilike(term),
                    MediaGalleryItem.media_url.ilike(term),
                    MediaGalleryItem.source_ref.ilike(term),
                )
            )

        offset = max(0, (page - 1) * page_size)

        async with db_manager.get_session() as session:
            count_result = await session.execute(select(func.count()).select_from(MediaGalleryItem).where(*filters))
            total = int(count_result.scalar_one() or 0)

            result = await session.execute(
                select(MediaGalleryItem)
                .where(*filters)
                .order_by(MediaGalleryItem.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            return list(result.scalars().all()), total

    async def get(self, item_id: str) -> MediaGalleryItem | None:
        async with db_manager.get_session() as session:
            result = await session.execute(select(MediaGalleryItem).where(MediaGalleryItem.id == item_id))
            return result.scalar_one_or_none()

    async def insert(self, item: MediaGalleryItem) -> MediaGalleryItem:
        async with db_manager.get_session() as session:
            session.add(item)
            await session.flush()
            await session.refresh(item)
            return item

    async def delete_by_owner(self, owner_id: str, item_id: str) -> bool:
        async with db_manager.get_session() as session:
            result = await session.execute(
                delete(MediaGalleryItem).where(
                    MediaGalleryItem.owner_id == owner_id,
                    MediaGalleryItem.id == item_id,
                )
            )
            return (result.rowcount or 0) > 0

    async def find_duplicate(
        self,
        *,
        owner_id: str,
        kind: str,
        media_url: str,
        chat_id: str | None,
        message_id: str | None,
    ) -> MediaGalleryItem | None:
        stmt = select(MediaGalleryItem).where(
            MediaGalleryItem.owner_id == owner_id,
            MediaGalleryItem.kind == kind,
            MediaGalleryItem.media_url == media_url,
        )
        if chat_id is None:
            stmt = stmt.where(MediaGalleryItem.chat_id.is_(None))
        else:
            stmt = stmt.where(MediaGalleryItem.chat_id == chat_id)
        if message_id is None:
            stmt = stmt.where(MediaGalleryItem.message_id.is_(None))
        else:
            stmt = stmt.where(MediaGalleryItem.message_id == message_id)
        async with db_manager.get_session() as session:
            result = await session.execute(stmt.limit(1))
            return result.scalar_one_or_none()


media_gallery_repository = MediaGalleryRepository()
