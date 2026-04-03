from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import Dict, Any, AsyncGenerator
import uuid
import time
import json
import structlog

from app.models.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatChoice,
    ChatMessage,
    UsageInfo
)
from app.services.memory import memory_service
from app.agents.graph import get_agent_graph

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completions endpoint with SSE streaming support.
    
    CRITICAL: Returns StreamingResponse to prevent frontend timeouts.
    Streams agent status updates in real-time as OpenAI SSE chunks.
    
    Workflow:
    1. Extract user_id and thread_id from request
    2. Retrieve long-term memory context using Mem0
    3. Stream LangGraph execution with real-time status updates
    4. Store conversation in long-term memory
    5. Return response in OpenAI SSE format (stream=true) or regular format
    """
    
    # Route to streaming or non-streaming based on request
    if request.stream:
        return StreamingResponse(
            stream_chat_completion(request),
            media_type="text/event-stream"
        )
    else:
        return await non_streaming_chat_completion(request)


async def stream_chat_completion(request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """
    Stream chat completion with real-time agent status updates (SSE format).
    
    CRITICAL: Prevents OpenWebUI timeouts by streaming progress updates.
    Format: data: {JSON}\n\n (OpenAI SSE format)
    """
    try:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        
        # Extract user context
        user_id = request.user or f"anon_{uuid.uuid4().hex[:8]}"
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        last_user_message = user_messages[-1].content if user_messages else ""
        
        logger.info(
            "Starting streaming chat completion",
            thread_id=thread_id,
            user_id=user_id
        )
        
        # Retrieve memories
        memories = await memory_service.search_memory(
            query=last_user_message,
            user_id=user_id,
            limit=5
        )
        
        memory_context = ""
        if memories:
            memory_context = "Relevant context from previous conversations:\n"
            for mem in memories:
                memory_context += f"- {mem.get('memory', '')}\n"
        
        # Get graph
        graph = await get_agent_graph()
        
        graph_input = {
            "messages": [msg.model_dump() for msg in request.messages],
            "user_request": last_user_message,
            "thread_id": thread_id,
            "user_id": user_id,
            "memory_context": memory_context
        }
        
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 50
        }
        
        # Stream status updates as graph executes
        current_agent = None
        final_state = None
        
        async for state_update in graph.astream(graph_input, config):
            final_state = state_update
            
            # Extract node name from state update (dict with single key: node_name)
            node_name = list(state_update.keys())[0] if state_update else None
            node_state = list(state_update.values())[0] if state_update else {}
            
            # Detect agent transitions
            new_agent = node_state.get("current_agent")
            
            if new_agent and new_agent != current_agent:
                current_agent = new_agent
                
                # Map agent names to user-friendly labels
                agent_labels = {
                    "supervisor": "🧠 Project Manager",
                    "designer": "🎨 UX/UI Designer",
                    "frontend_dev": "💻 Frontend Developer",
                    "backend_dev": "⚙️ Backend Developer",
                    "devops": "🐳 DevOps Engineer",
                    "qa_tester": "✅ QA Tester"
                }
                
                label = agent_labels.get(new_agent, new_agent)
                status_message = f"\n*⚙️ {label} is working...*\n"
                
                # Send status chunk in OpenAI SSE format
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request.model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": status_message},
                        "finish_reason": None
                    }]
                }
                
                yield f"data: {json.dumps(chunk)}\n\n"
        
        # Extract final response
        if final_state is None:
            raise ValueError("Graph execution produced no output")
        
        graph_output = list(final_state.values())[-1]
        assistant_message = graph_output.get("final_response", "Task completed.")
        
        # Stream final message in chunks (simulate typing effect)
        chunk_size = 50
        for i in range(0, len(assistant_message), chunk_size):
            text_chunk = assistant_message[i:i+chunk_size]
            
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": text_chunk},
                    "finish_reason": None
                }]
            }
            
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # Send final chunk with finish_reason
        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": request.model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"
        
        # Store in long-term memory (async, don't block stream)
        conversation_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]
        conversation_messages.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        await memory_service.add_memory(
            messages=conversation_messages,
            user_id=user_id,
            metadata={"thread_id": thread_id}
        )
        
        logger.info(
            "Streaming chat completion successful",
            thread_id=thread_id,
            user_id=user_id
        )
    
    except Exception as e:
        logger.error("Streaming chat completion failed", error=str(e), exc_info=True)
        
        # Send error in SSE format
        error_chunk = {
            "id": "error",
            "object": "error",
            "error": {
                "message": str(e),
                "type": "server_error"
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


async def non_streaming_chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    Non-streaming chat completion (legacy mode).
    Use streaming mode for production to prevent timeouts.
    """
    try:
        user_id = request.user or f"anon_{uuid.uuid4().hex[:8]}"
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        last_user_message = user_messages[-1].content if user_messages else ""
        
        memories = await memory_service.search_memory(
            query=last_user_message,
            user_id=user_id,
            limit=5
        )
        
        memory_context = ""
        if memories:
            memory_context = "Relevant context from previous conversations:\n"
            for mem in memories:
                memory_context += f"- {mem.get('memory', '')}\n"
        
        graph = await get_agent_graph()
        
        graph_input = {
            "messages": [msg.model_dump() for msg in request.messages],
            "user_request": last_user_message,
            "thread_id": thread_id,
            "user_id": user_id,
            "memory_context": memory_context
        }
        
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 50
        }
        
        final_state = None
        async for state in graph.astream(graph_input, config):
            final_state = state
        
        if final_state is None:
            raise ValueError("Graph execution produced no output")
        
        graph_output = list(final_state.values())[-1]
        assistant_message = graph_output.get("final_response", "Task completed.")
        
        conversation_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]
        conversation_messages.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        await memory_service.add_memory(
            messages=conversation_messages,
            user_id=user_id,
            metadata={"thread_id": thread_id}
        )
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            object="chat.completion",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=assistant_message
                    ),
                    finish_reason="stop"
                )
            ],
            usage=UsageInfo(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0
            ),
            thread_id=thread_id
        )
    
    except Exception as e:
        logger.error("Non-streaming chat completion failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat completion: {str(e)}"
        )


@router.get("/models")
async def list_models():
    """List available models (OpenAI-compatible endpoint)."""
    return {
        "object": "list",
        "data": [
            {
                "id": "gpt-4",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mts-agentic"
            },
            {
                "id": "gpt-3.5-turbo",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mts-agentic"
            }
        ]
    }
