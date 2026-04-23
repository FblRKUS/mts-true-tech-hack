from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    id: str
    user_id: str
    thread_id: str = ""
    role: Literal["system", "user", "assistant", "tool", "function"] = "user"
    content: str
    source: str = "chat"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MemoryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    thread_id: str = ""
    role: Literal["system", "user", "assistant", "tool", "function"] = "user"
    source: str = "chat"
    tags: list[str] = Field(default_factory=list)


class MemoryRecallRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    thread_id: str | None = None


class MemoryRecallResponse(BaseModel):
    items: list[MemoryRecord]
    query: str


class MemoryDeleteResponse(BaseModel):
    deleted: bool
    memory_id: str


class ThreadSummaryRecord(BaseModel):
    user_id: str
    thread_id: str
    summary: str
    message_count: int
    created_at: datetime
    updated_at: datetime
