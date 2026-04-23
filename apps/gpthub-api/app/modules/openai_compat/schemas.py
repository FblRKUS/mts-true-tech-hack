from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Any = ""


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="autoselect")
    messages: list[ChatMessage]
    temperature: float = 0.6
    max_tokens: int | None = 4096
    stream: bool = False
    user: str | None = None
    thread_id: str | None = None
    chat_id: str | None = None
    id: str | None = None
    parent_id: str | None = None
    features: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    auto_task_type_override: str | None = None
    autopilot: bool = False
    model_court: bool = False
    deep_research: bool = False


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "mws"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    model: str = Field(default="autoselect")
    input: Any
    user: str | None = None


class ImageGenerationRequest(BaseModel):
    model: str = Field(default="autoselect")
    prompt: str = Field(min_length=1)
    n: int = 1
    size: str | None = None
    response_format: Literal["url", "b64_json"] | None = None
    user: str | None = None
