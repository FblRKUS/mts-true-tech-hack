from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import uuid4

from app.core.config import settings
from app.core.errors import AppError
from app.modules.media_gallery.model import MediaGalleryItem
from app.modules.media_gallery.repository import media_gallery_repository
from app.modules.media_gallery.schemas import (
    MediaGalleryDeleteResponse,
    MediaGalleryIngestItem,
    MediaGalleryItemRecord,
    MediaGalleryListResponse,
)


def _enabled_or_raise() -> None:
    if not settings.media_gallery_enabled:
        raise AppError(
            code="feature_disabled",
            message="Media gallery is disabled",
            status_code=403,
        )


def _normalize_url(value: str | None) -> str:
    return str(value or "").strip()


def _sanitize_int(value: int | None) -> int | None:
    if value is None:
        return None
    return value if value >= 0 else None


def _validate_owner_id(owner_id: str) -> str:
    owner = str(owner_id or "").strip()
    if not owner:
        raise AppError(code="validation_error", message="owner_id is required", status_code=422)
    return owner


def _effective_date_from(date_from: datetime | None) -> datetime:
    now = datetime.now(timezone.utc)
    retention_days = max(1, int(settings.media_gallery_retention_days))
    retention_floor = now - timedelta(days=retention_days)
    if date_from is None:
        return retention_floor
    normalized = date_from if date_from.tzinfo is not None else date_from.replace(tzinfo=timezone.utc)
    return max(normalized, retention_floor)


async def ingest_media_gallery_items(owner_id: str, items: Iterable[MediaGalleryIngestItem]) -> int:
    if not settings.media_gallery_enabled:
        return 0
    owner = str(owner_id or "").strip()
    if not owner:
        return 0

    inserted = 0
    for entry in items:
        media_url = _normalize_url(entry.media_url)
        if not media_url:
            continue

        duplicate = await media_gallery_repository.find_duplicate(
            owner_id=owner,
            kind=entry.kind,
            media_url=media_url,
            chat_id=entry.chat_id,
            message_id=entry.message_id,
        )
        if duplicate is not None:
            continue

        model = MediaGalleryItem(
            id=uuid4().hex,
            owner_id=owner,
            kind=entry.kind,
            media_url=media_url,
            thumbnail_url=_normalize_url(entry.thumbnail_url) or None,
            chat_id=str(entry.chat_id).strip() if entry.chat_id else None,
            message_id=str(entry.message_id).strip() if entry.message_id else None,
            thread_id=str(entry.thread_id).strip() if entry.thread_id else None,
            prompt_text=str(entry.prompt_text or "")[:12000],
            model_id=str(entry.model_id or "")[:128],
            provider=str(entry.provider or "")[:64],
            width=_sanitize_int(entry.width),
            height=_sanitize_int(entry.height),
            mime_type=str(entry.mime_type or "")[:128],
            size_bytes=_sanitize_int(entry.size_bytes),
            source_ref=_normalize_url(entry.source_ref)[:20000],
        )
        await media_gallery_repository.insert(model)
        inserted += 1
    return inserted


async def list_media_gallery_items(
    owner_id: str,
    *,
    page: int = 1,
    page_size: int | None = None,
    kind: str | None = None,
    search: str | None = None,
    model_id: str | None = None,
    chat_id: str | None = None,
    thread_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> MediaGalleryListResponse:
    _enabled_or_raise()
    owner = _validate_owner_id(owner_id)
    normalized_page = max(1, int(page))
    requested_page_size = int(page_size) if page_size is not None else int(settings.media_gallery_page_size)
    normalized_page_size = max(6, min(120, requested_page_size))

    filters_count = sum(
        [
            bool(kind),
            bool((search or "").strip()),
            bool(model_id),
            bool(chat_id),
            bool(thread_id),
            date_from is not None,
            date_to is not None,
        ]
    )
    if filters_count > int(settings.media_gallery_max_filters):
        raise AppError(
            code="validation_error",
            message="Too many gallery filters requested",
            details={"max_filters": int(settings.media_gallery_max_filters)},
            status_code=422,
        )

    effective_from = _effective_date_from(date_from)
    effective_to = date_to if (date_to is None or date_to.tzinfo is not None) else date_to.replace(tzinfo=timezone.utc)
    rows, total = await media_gallery_repository.list_items(
        owner,
        page=normalized_page,
        page_size=normalized_page_size,
        kind=(kind or "").strip() or None,
        search=(search or "").strip() or None,
        model_id=(model_id or "").strip() or None,
        chat_id=(chat_id or "").strip() or None,
        thread_id=(thread_id or "").strip() or None,
        created_from=effective_from,
        created_to=effective_to,
    )
    return MediaGalleryListResponse(
        items=[MediaGalleryItemRecord.model_validate(row) for row in rows],
        total=total,
        page=normalized_page,
        page_size=normalized_page_size,
    )


async def get_media_gallery_item(owner_id: str, item_id: str) -> MediaGalleryItemRecord:
    _enabled_or_raise()
    owner = _validate_owner_id(owner_id)
    row = await media_gallery_repository.get(item_id)
    if row is None or row.owner_id != owner:
        raise AppError(code="not_found", message="Gallery item not found", status_code=404)
    return MediaGalleryItemRecord.model_validate(row)


async def delete_media_gallery_item(owner_id: str, item_id: str) -> MediaGalleryDeleteResponse:
    _enabled_or_raise()
    owner = _validate_owner_id(owner_id)
    deleted = await media_gallery_repository.delete_by_owner(owner, item_id)
    return MediaGalleryDeleteResponse(deleted=deleted, item_id=item_id)
