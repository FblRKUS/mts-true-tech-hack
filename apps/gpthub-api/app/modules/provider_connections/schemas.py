from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderLiteral = Literal["openai", "ollama"]


class ProviderConnectionCreateRequest(BaseModel):
    provider: ProviderLiteral
    slug: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=2, max_length=128)
    base_url: str = Field(min_length=8, max_length=512)
    api_key: str = Field(default="", max_length=1024)
    is_enabled: bool = True


class ProviderConnectionUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=128)
    base_url: str | None = Field(default=None, min_length=8, max_length=512)
    api_key: str | None = Field(default=None, max_length=1024)
    is_enabled: bool | None = None


class ProviderConnectionRecord(BaseModel):
    id: str
    provider: ProviderLiteral
    slug: str
    display_name: str
    base_url: str
    api_key_masked: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class ProviderConnectionDeleteResponse(BaseModel):
    deleted: bool
    id: str
