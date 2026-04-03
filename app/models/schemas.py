from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime


class ChatMessage(BaseModel):
    """Single message in chat conversation (OpenAI format)."""
    role: Literal["system", "user", "assistant", "function"]
    content: str
    name: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None


class ChatCompletionRequest(BaseModel):
    """Request body for /v1/chat/completions endpoint."""
    model: str = Field(default="gpt-4", description="Model identifier")
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: bool = Field(default=False)
    user: Optional[str] = Field(default=None, description="User ID for tracking")
    
    # Custom fields for thread management
    thread_id: Optional[str] = Field(default=None, description="Thread ID for conversation persistence")


class UsageInfo(BaseModel):
    """Token usage information."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatChoice(BaseModel):
    """Single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    """Response from /v1/chat/completions endpoint."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: UsageInfo
    
    # Custom fields
    thread_id: Optional[str] = None


class AgentState(BaseModel):
    """State shared across LangGraph nodes."""
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    user_request: str = ""
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    memory_context: str = ""
    
    # Agent routing
    next_agent: Optional[str] = None
    current_agent: Optional[str] = None
    current_task_description: str = ""
    supervisor_reasoning: str = ""
    
    # Task decomposition
    task_plan: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    
    # Shared Workspace (Critical: prevents context overload)
    # Key: file path (e.g., "src/App.jsx", "requirements.txt")
    # Value: file content (code/text)
    workspace: Dict[str, str] = Field(
        default_factory=dict,
        description="Shared file workspace. Agents save code here instead of in messages."
    )
    
    # Legacy artifacts (deprecated, use workspace instead)
    design_artifacts: Dict[str, Any] = Field(default_factory=dict)
    frontend_code: Dict[str, str] = Field(default_factory=dict)
    backend_code: Dict[str, str] = Field(default_factory=dict)
    devops_configs: Dict[str, str] = Field(default_factory=dict)
    
    # QA feedback loop
    qa_iteration: int = 0
    qa_feedback: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Structured QA feedback with patches"
    )
    e2b_test_results: Optional[Dict[str, Any]] = None
    
    # Final output
    is_completed: bool = False
    final_response: Optional[str] = None


class StreamChunk(BaseModel):
    """SSE chunk for streaming responses (OpenAI format)."""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    
    
class QAPatch(BaseModel):
    """Structured patch recommendation from QA."""
    file_path: str
    line_number: Optional[int] = None
    old_code: Optional[str] = None
    new_code: str
    reason: str
