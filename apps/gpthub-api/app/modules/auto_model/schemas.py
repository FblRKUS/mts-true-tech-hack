from typing import Literal

from pydantic import BaseModel, Field

InputType = Literal["text", "image", "audio", "file", "mixed"]
TaskDomain = Literal[
    "coding",
    "analysis",
    "creative",
    "document",
    "ocr",
    "support",
    "general",
]


class AutoModelRequest(BaseModel):
    message: str = Field(..., min_length=1)
    input_type: InputType = "text"
    task_domain: TaskDomain | None = None
    manual_model: str | None = None


class ModelCandidate(BaseModel):
    model_id: str
    score: float
    reason: str


class AutoModelResponse(BaseModel):
    mode: Literal["auto", "manual"]
    selected_model: str
    selected_tool: str
    inferred_domain: TaskDomain
    confidence: float
    reasons: list[str]
    alternatives: list[ModelCandidate]
