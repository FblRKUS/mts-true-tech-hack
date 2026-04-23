from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.modules.media_gallery.schemas import (
    MediaGalleryDeleteResponse,
    MediaGalleryItemRecord,
    MediaGalleryListResponse,
)
from app.modules.media_gallery.service import (
    delete_media_gallery_item,
    get_media_gallery_item,
    list_media_gallery_items,
)

router = APIRouter(prefix="/features/media-gallery", tags=["feature:media-gallery"])


@router.get(
    "/{owner_id}",
    response_model=MediaGalleryListResponse,
    summary="List gallery items",
    description="Возвращает медиа-галерею пользователя с пагинацией и фильтрами.",
)
async def list_items(
    owner_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    kind: str | None = Query(default=None),
    search: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    chat_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> MediaGalleryListResponse:
    return await list_media_gallery_items(
        owner_id,
        page=page,
        page_size=page_size,
        kind=kind,
        search=search,
        model_id=model_id,
        chat_id=chat_id,
        thread_id=thread_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/{owner_id}/{item_id}",
    response_model=MediaGalleryItemRecord,
    summary="Get gallery item",
    description="Возвращает запись медиа-галереи по идентификатору.",
)
async def get_item(owner_id: str, item_id: str) -> MediaGalleryItemRecord:
    return await get_media_gallery_item(owner_id, item_id)


@router.delete(
    "/{owner_id}/{item_id}",
    response_model=MediaGalleryDeleteResponse,
    summary="Delete gallery item",
    description="Удаляет запись из галереи пользователя.",
)
async def delete_item(owner_id: str, item_id: str) -> MediaGalleryDeleteResponse:
    return await delete_media_gallery_item(owner_id, item_id)
