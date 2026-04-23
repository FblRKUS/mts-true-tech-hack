from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MediaKind = Literal["upload", "generated"]


class MediaGalleryItemRecord(BaseModel):
    id: str
    owner_id: str
    kind: MediaKind
    media_url: str
    thumbnail_url: str | None
    chat_id: str | None
    message_id: str | None
    thread_id: str | None
    prompt_text: str
    model_id: str
    provider: str
    width: int | None
    height: int | None
    mime_type: str
    size_bytes: int | None
    source_ref: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MediaGalleryListResponse(BaseModel):
    items: list[MediaGalleryItemRecord]
    total: int
    page: int
    page_size: int


class MediaGalleryDeleteResponse(BaseModel):
    deleted: bool
    item_id: str


class MediaGalleryIngestItem(BaseModel):
    kind: MediaKind
    media_url: str = Field(min_length=1, max_length=20000)
    thumbnail_url: str | None = Field(default=None, max_length=20000)
    chat_id: str | None = Field(default=None, max_length=128)
    message_id: str | None = Field(default=None, max_length=128)
    thread_id: str | None = Field(default=None, max_length=128)
    prompt_text: str = Field(default="", max_length=12000)
    model_id: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=64)
    width: int | None = None
    height: int | None = None
    mime_type: str = Field(default="", max_length=128)
    size_bytes: int | None = None
    source_ref: str = Field(default="", max_length=20000)
