from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class WorkspaceRecord(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeCreate(BaseModel):
    parent_id: str | None = None
    node_type: Literal["file", "directory"] = "file"
    name: str = Field(..., min_length=1, max_length=255)
    content: str = ""
    mime_type: str = "text/plain"


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    mime_type: str | None = None
    parent_id: str | None = None


class NodeRecord(BaseModel):
    id: str
    workspace_id: str
    parent_id: str | None
    node_type: str
    name: str
    path: str
    content: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeDeleteResponse(BaseModel):
    deleted: bool
    node_id: str


class WorkspaceContextResponse(BaseModel):
    workspace_id: str
    files: list[NodeRecord]


class WorkspaceAgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=12000)


class WorkspaceAgentRunRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12000)
    model: str = Field(default="autoselect", min_length=1, max_length=128)
    autopilot: bool = False
    history: list[WorkspaceAgentMessage] = Field(default_factory=list)
    run_id: str | None = Field(default=None, max_length=128)


class WorkspaceAgentRunResponse(BaseModel):
    run_id: str
    response: str
    applied_files: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


class WorkspaceAgentStatusResponse(BaseModel):
    run_id: str
    stage: str = ""
    done: bool = False
    error: str = ""
    steps: list[str] = Field(default_factory=list)
