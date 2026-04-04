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
from app.services.llm_router import llm_router
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
    
    With intelligent routing:
    - SIMPLE queries: Direct LLM response (fast, no graph overhead)
    - COMPLEX queries: Full multi-agent LangGraph pipeline
    """
    try:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        
        # Extract user context
        user_id = request.user or f"anon_{uuid.uuid4().hex[:8]}"
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        
        # Handle multimodal content (Vision API support)
        if user_messages:
            last_msg_content = user_messages[-1].content
            # If content is list (multimodal), extract text part
            if isinstance(last_msg_content, list):
                text_parts = [part.get("text", "") for part in last_msg_content if part.get("type") == "text"]
                last_user_message = " ".join(text_parts)
            else:
                last_user_message = last_msg_content
        else:
            last_user_message = ""
        
        logger.info(
            "Starting streaming chat completion",
            thread_id=thread_id,
            user_id=user_id,
            has_multimodal=isinstance(user_messages[-1].content if user_messages else "", list)
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
        
        # INTENT ROUTING with FAST HEURISTICS (prevents OpenWebUI ghost calls)
        # OpenWebUI sends background requests for titles, tags, follow-ups after main response
        ghost_keywords = [
            "### Task:",
            "Generate a concise",
            "relevant follow-up",
            "create a title",
            "generate tags",
            "suggest questions",
            "summarize the conversation"
        ]
        
        # FAST PATH: Detect OpenWebUI service requests (no LLM call needed)
        is_ghost_call = any(keyword.lower() in last_user_message.lower() for keyword in ghost_keywords)
        
        if is_ghost_call:
            intent = "SIMPLE"
            logger.info("Ghost call detected (OpenWebUI service request)", query_preview=last_user_message[:80])
        else:
            # LLM-based intent classification
            intent_prompt = f"""User query: {last_user_message}

Determine if this requires multi-agent software development (code generation, architecture, system design).

CRITICAL RULES:
- If the query asks to generate titles, tags, summaries, or follow-up questions: ALWAYS respond SIMPLE
- If the query is metadata generation for UI (titles, tags, etc.): ALWAYS respond SIMPLE
- Only respond COMPLEX if the user explicitly requests code generation, architecture, or system design

Respond with EXACTLY one word:
- COMPLEX: if query requires code generation, architecture design, system planning, or multi-step development
- SIMPLE: if it's a question, conversation, explanation, metadata generation, or simple task"""

            try:
                intent_response = await llm_router.generate_text(
                    prompt=intent_prompt,
                    model=request.model,
                    temperature=0.1,
                    max_tokens=10,
                    system_prompt="You are an intent classifier. Respond with only COMPLEX or SIMPLE. NEVER return COMPLEX for title/tag/summary generation."
                )
                
                intent = intent_response.strip().upper()
                logger.info("Intent classification", intent=intent, query_preview=last_user_message[:50])
                
            except Exception as e:
                logger.warning("Intent classification failed, defaulting to COMPLEX", error=str(e))
                intent = "COMPLEX"
        
        # Route based on intent
        if intent == "SIMPLE":
            # SIMPLE PATH: Direct LLM response without graph overhead
            logger.info("Using simple path (direct LLM)")
            
            # Build messages with context
            messages_with_context = []
            
            if memory_context:
                messages_with_context.append({
                    "role": "system",
                    "content": f"Context from previous conversations:\n{memory_context}"
                })
            
            # Add conversation history
            for msg in request.messages:
                messages_with_context.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            # Call LLM directly and stream response
            response = await llm_router.chat_completion(
                messages=messages_with_context,
                model=request.model,
                temperature=0.7,
                max_tokens=2000
            )
            
            assistant_message = response["choices"][0]["message"]["content"]
            
            # Stream in chunks
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
            
            # Send final chunk
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
            
            # Store in memory (async, don't block)
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
                metadata={"thread_id": thread_id, "routing": "simple"}
            )
            
            logger.info("Simple path completed", thread_id=thread_id)
            return
        
        # COMPLEX PATH: Full multi-agent LangGraph pipeline
        logger.info("Using complex path (LangGraph multi-agent)")
        
        # Get graph
        graph = await get_agent_graph()
        
        graph_input = {
            "messages": [msg.model_dump() for msg in request.messages],
            "user_request": last_user_message,
            "thread_id": thread_id,
            "user_id": user_id,
            "memory_context": memory_context,
            "request_model": request.model,  # Pass user's model choice
            # Initialize all required state fields
            "next_agent": "",
            "current_agent": "",
            "current_task_description": "",
            "supervisor_reasoning": "",
            "task_plan": [],
            "completed_tasks": [],
            "design_artifacts": {},
            "frontend_code": {},
            "backend_code": {},
            "devops_configs": {},
            "qa_iteration": 0,
            "qa_feedback": [],
            "e2b_test_results": {},
            "is_completed": False,
            "final_response": ""
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
        
        # Extract last node's state (dict with node_name: state structure)
        graph_output = list(final_state.values())[-1] if final_state else {}
        
        # Ensure graph_output is a dict before accessing
        if not isinstance(graph_output, dict):
            logger.warning("Graph output is not a dict", output_type=type(graph_output))
            graph_output = {}
        
        # === НАЧАЛО БЛОКА ПРОКЛЕЙКИ ФАЙЛОВ ===
        final_text = graph_output.get("final_response", "Task completed.")
        
        workspace = graph_output.get("workspace", {})
        if workspace:
            logger.info("Adding workspace files to response", num_files=len(workspace))
            
            # 1. Рисуем дерево проекта
            final_text += "\n\n---\n\n### 📁 Структура проекта:\n```text\n"
            for file_path in sorted(workspace.keys()):
                final_text += f"├── {file_path}\n"
            final_text += "```\n\n"

            # 2. Выводим содержимое каждого файла
            final_text += "### 💻 Исходный код:\n"
            for file_path, content in workspace.items():
                # Определяем язык для подсветки синтаксиса
                ext = file_path.split('.')[-1].lower() if '.' in file_path else 'text'
                lang_map = {
                    'py': 'python', 'js': 'javascript', 'jsx': 'jsx', 'ts': 'typescript', 
                    'tsx': 'tsx', 'html': 'html', 'css': 'css', 'json': 'json', 
                    'yml': 'yaml', 'yaml': 'yaml', 'md': 'markdown', 'sh': 'bash',
                    'Dockerfile': 'dockerfile'
                }
                lang = lang_map.get(ext, 'text')
                if file_path == 'Dockerfile':
                    lang = 'dockerfile'
                
                final_text += f"\n**`{file_path}`**\n"
                final_text += f"```{lang}\n{content}\n```\n"
        # === КОНЕЦ БЛОКА ПРОКЛЕЙКИ ФАЙЛОВ ===

        # Теперь стримим этот огромный текст с кодом пользователю
        chunk_size = 50
        for i in range(0, len(final_text), chunk_size):
            text_chunk = final_text[i:i+chunk_size]
            
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
            await asyncio.sleep(0.01)
        
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
    
    With intelligent routing:
    - SIMPLE queries: Direct LLM response
    - COMPLEX queries: Full multi-agent LangGraph pipeline
    """
    try:
        user_id = request.user or f"anon_{uuid.uuid4().hex[:8]}"
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        
        # Handle multimodal content (Vision API support)
        if user_messages:
            last_msg_content = user_messages[-1].content
            if isinstance(last_msg_content, list):
                text_parts = [part.get("text", "") for part in last_msg_content if part.get("type") == "text"]
                last_user_message = " ".join(text_parts)
            else:
                last_user_message = last_msg_content
        else:
            last_user_message = ""
        
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
        
        # INTENT ROUTING with FAST HEURISTICS
        ghost_keywords = [
            "### Task:",
            "Generate a concise",
            "relevant follow-up",
            "create a title",
            "generate tags",
            "suggest questions",
            "summarize the conversation"
        ]
        
        # FAST PATH: Detect OpenWebUI service requests
        is_ghost_call = any(keyword.lower() in last_user_message.lower() for keyword in ghost_keywords)
        
        if is_ghost_call:
            intent = "SIMPLE"
            logger.info("Ghost call detected (OpenWebUI service request)", query_preview=last_user_message[:80])
        else:
            # LLM-based intent classification
            intent_prompt = f"""User query: {last_user_message}

Determine if this requires multi-agent software development (code generation, architecture, system design).

CRITICAL RULES:
- If the query asks to generate titles, tags, summaries, or follow-up questions: ALWAYS respond SIMPLE
- If the query is metadata generation for UI (titles, tags, etc.): ALWAYS respond SIMPLE
- Only respond COMPLEX if the user explicitly requests code generation, architecture, or system design

Respond with EXACTLY one word:
- COMPLEX: if query requires code generation, architecture design, system planning, or multi-step development
- SIMPLE: if it's a question, conversation, explanation, metadata generation, or simple task"""

            try:
                intent_response = await llm_router.generate_text(
                    prompt=intent_prompt,
                    model=request.model,
                    temperature=0.1,
                    max_tokens=10,
                    system_prompt="You are an intent classifier. Respond with only COMPLEX or SIMPLE. NEVER return COMPLEX for title/tag/summary generation."
                )
                
                intent = intent_response.strip().upper()
                logger.info("Intent classification", intent=intent, query_preview=last_user_message[:50])
                
            except Exception as e:
                logger.warning("Intent classification failed, defaulting to COMPLEX", error=str(e))
                intent = "COMPLEX"
        
        # Route based on intent
        if intent == "SIMPLE":
            # SIMPLE PATH: Direct LLM response
            logger.info("Using simple path (direct LLM)")
            
            messages_with_context = []
            
            if memory_context:
                messages_with_context.append({
                    "role": "system",
                    "content": f"Context from previous conversations:\n{memory_context}"
                })
            
            for msg in request.messages:
                messages_with_context.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            response = await llm_router.chat_completion(
                messages=messages_with_context,
                model=request.model,
                temperature=0.7,
                max_tokens=2000
            )
            
            assistant_message = response["choices"][0]["message"]["content"]
            
            # Store in memory
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
                metadata={"thread_id": thread_id, "routing": "simple"}
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
        
        # COMPLEX PATH: LangGraph multi-agent
        logger.info("Using complex path (LangGraph multi-agent)")
        
        graph = await get_agent_graph()
        
        graph_input = {
            "messages": [msg.model_dump() for msg in request.messages],
            "user_request": last_user_message,
            "thread_id": thread_id,
            "user_id": user_id,
            "memory_context": memory_context,
            "request_model": request.model,  # Pass user's model choice
            # Initialize all required state fields
            "next_agent": "",
            "current_agent": "",
            "current_task_description": "",
            "supervisor_reasoning": "",
            "task_plan": [],
            "completed_tasks": [],
            "design_artifacts": {},
            "frontend_code": {},
            "backend_code": {},
            "devops_configs": {},
            "qa_iteration": 0,
            "qa_feedback": [],
            "e2b_test_results": {},
            "is_completed": False,
            "final_response": ""
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
        
        # Extract last node's state (dict with node_name: state structure)
        graph_output = list(final_state.values())[-1] if final_state else {}
        
        # Ensure graph_output is a dict before accessing
        if not isinstance(graph_output, dict):
            logger.warning("Graph output is not a dict", output_type=type(graph_output))
            graph_output = {}
        
        # === НАЧАЛО БЛОКА ПРОКЛЕЙКИ ФАЙЛОВ (NON-STREAMING) ===
        assistant_message = graph_output.get("final_response", "Task completed.")
        
        workspace = graph_output.get("workspace", {})
        if workspace:
            logger.info("Appending workspace files to response", num_files=len(workspace))
            
            # 1. Рисуем дерево проекта
            assistant_message += "\n\n---\n\n### 📁 Структура проекта:\n```text\n"
            for file_path in sorted(workspace.keys()):
                assistant_message += f"├── {file_path}\n"
            assistant_message += "```\n\n"
            
            # 2. Выводим содержимое каждого файла
            assistant_message += "### 💻 Исходный код:\n"
            for file_path, file_content in workspace.items():
                # Определяем язык для подсветки синтаксиса
                extension = file_path.split('.')[-1] if '.' in file_path else 'txt'
                
                lang_map = {
                    'py': 'python', 'js': 'javascript', 'jsx': 'jsx',
                    'ts': 'typescript', 'tsx': 'tsx', 'html': 'html',
                    'css': 'css', 'json': 'json', 'yml': 'yaml',
                    'yaml': 'yaml', 'md': 'markdown', 'sh': 'bash',
                    'Dockerfile': 'dockerfile'
                }
                
                lang = lang_map.get(extension, extension)
                if file_path == 'Dockerfile':
                    lang = 'dockerfile'
                
                assistant_message += f"\n**`{file_path}`**\n"
                assistant_message += f"```{lang}\n{file_content}\n```\n"
        # === КОНЕЦ БЛОКА ПРОКЛЕЙКИ ФАЙЛОВ (NON-STREAMING) ===
        
        # Store conversation in memory
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
                "id": "openai/qwen3-235b-a22b-2507",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mts-agentic"
            },
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
