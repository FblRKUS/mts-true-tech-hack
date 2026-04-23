from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import structlog
from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import AppError
from app.modules.chat_memory.schemas import MemoryCreateRequest
from app.modules.chat_memory.service import (
    count_thread_memories,
    create_memory,
    get_thread_summary,
    list_thread_memories,
    recall_memories,
    upsert_thread_summary,
)
from app.modules.deep_research.service import (
    fetch_webpage_excerpt,
    format_deep_research_answer,
    is_deep_research_enabled,
    normalize_public_web_url,
    run_deep_research,
)
from app.modules.media_gallery.schemas import MediaGalleryIngestItem
from app.modules.media_gallery.service import ingest_media_gallery_items
from app.modules.model_court.service import (
    format_model_court_answer,
    is_model_court_enabled,
    run_model_court,
)
from app.modules.openai_compat.schemas import ChatCompletionRequest, EmbeddingRequest, ImageGenerationRequest
from app.services.llm_router import MWS_AVAILABLE_MODELS, llm_router

logger = structlog.get_logger(__name__)

_MAX_MESSAGE_LENGTH = 128_000
_MAX_MESSAGES = 100
_MAX_TOTAL_PAYLOAD_CHARS = 200_000
_INTENT_CLASSIFIER_MODEL = "gpt-oss-20b"
_DEFAULT_EMBEDDING_MODEL = "bge-m3"
_DEFAULT_IMAGE_MODEL = "qwen-image-lightning"
_DEFAULT_ASR_MODEL = "whisper-medium"
_IMAGE_MODELS = {"qwen-image-lightning", "qwen-image"}
_MAX_CONTEXT_IMAGES = 3
_MAX_GALLERY_IMAGES = 12
_MAX_LINK_CONTEXT_URLS = 3
_VISION_CONTEXT_MODEL = "qwen2.5-vl-72b"
_URL_REGEX = re.compile(r"https?://[^\s<>\"']+", flags=re.IGNORECASE)


def _is_auto_model_requested(model: str | None) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized in {"", "autoselect", "auto"}


def _is_external_provider_model(model: str) -> bool:
    if model.startswith("ollama/"):
        return True
    if model.startswith("openai/") and model.count("/") >= 2:
        return True
    return False


def _should_use_stub_for_model(model: str) -> bool:
    if settings.mws_stub_mode:
        return True
    if _is_external_provider_model(model):
        return False
    return not settings.openai_api_key


def _default_modality_model(modality: str) -> str:
    if modality == "embeddings":
        return _DEFAULT_EMBEDDING_MODEL
    if modality == "image_generation":
        return _DEFAULT_IMAGE_MODEL
    if modality == "audio_transcription":
        return _DEFAULT_ASR_MODEL
    return str(settings.mws_default_model or "mws-gpt-alpha")


def _graph_helpers():
    from app.agents.graph import create_initial_state, get_agent_graph

    return create_initial_state, get_agent_graph


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return " ".join(chunks)
    return str(content or "")


def _extract_image_urls(content: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "")
            if part_type not in {"image_url", "input_image"}:
                continue
            raw_image = part.get("image_url")
            image_url = ""
            if isinstance(raw_image, dict):
                image_url = str(raw_image.get("url") or "").strip()
            elif isinstance(raw_image, str):
                image_url = raw_image.strip()
            if image_url:
                urls.append(image_url)
    return urls


def _last_user_image_urls(payload: ChatCompletionRequest) -> list[str]:
    user_messages_scanned = 0
    for message in reversed(payload.messages):
        if message.role != "user":
            continue
        user_messages_scanned += 1
        urls = _extract_image_urls(message.content)
        if not urls:
            if user_messages_scanned >= 3:
                break
            continue
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
            if len(deduped) >= _MAX_CONTEXT_IMAGES:
                break
        return deduped
    return []


def _last_user_message(payload: ChatCompletionRequest) -> str:
    for message in reversed(payload.messages):
        if message.role == "user":
            return _extract_text(message.content)
    return ""


def _resolve_user_id(payload: ChatCompletionRequest) -> str:
    for candidate in (payload.user, payload.chat_id):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return f"anon_{uuid4().hex[:8]}"


def _resolve_thread_id(payload: ChatCompletionRequest) -> str:
    for candidate in (payload.thread_id, payload.chat_id):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return f"thread_{uuid4().hex}"


def _provider_from_model(model: str) -> str:
    normalized = str(model or "").strip()
    if "/" in normalized:
        return normalized.split("/", 1)[0]
    return "mws"


def _coerce_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _preferred_gallery_media_url(url: str, source_ref: str | None) -> str:
    normalized_url = str(url or "").strip()
    normalized_source = str(source_ref or "").strip()
    if normalized_url.startswith("data:") and normalized_source:
        return normalized_source
    return normalized_url


def _extract_media_payloads_from_last_user_message(payload: ChatCompletionRequest) -> list[dict[str, Any]]:
    for message in reversed(payload.messages):
        if message.role != "user":
            continue
        content = message.content
        if not isinstance(content, list):
            continue
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type not in {"image_url", "input_image"}:
                continue
            part_source_ref = str(part.get("source_ref") or "").strip() or None
            raw_image = part.get("image_url")
            if isinstance(raw_image, dict):
                url = str(raw_image.get("url") or "").strip()
                width = _coerce_non_negative_int(raw_image.get("width"))
                height = _coerce_non_negative_int(raw_image.get("height"))
                source_ref = str(raw_image.get("source_ref") or "").strip() or None
                size_bytes = _coerce_non_negative_int(raw_image.get("size_bytes"))
                nested_mime = str(raw_image.get("mime_type") or "").strip()
            else:
                url = str(raw_image or "").strip()
                width = None
                height = None
                source_ref = None
                size_bytes = None
                nested_mime = ""
            source_ref = part_source_ref or source_ref
            preferred_url = _preferred_gallery_media_url(url, source_ref)
            if not preferred_url or preferred_url in seen:
                continue
            seen.add(preferred_url)
            mime_type = str(part.get("mime_type") or nested_mime).strip()
            size_hint = _coerce_non_negative_int(part.get("size_bytes"))
            source_hint = source_ref
            if not mime_type and url.startswith("data:"):
                mime_type = url.split(";", 1)[0].replace("data:", "").strip()
            items.append(
                {
                    "url": preferred_url,
                    "mime_type": mime_type,
                    "width": width,
                    "height": height,
                    "size_bytes": size_hint if size_hint is not None else size_bytes,
                    "source_ref": source_hint or url,
                }
            )
            if len(items) >= _MAX_GALLERY_IMAGES:
                break
        if items:
            return items
    return []


def _extract_markdown_image_urls(text: str) -> list[str]:
    urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text or "")
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        normalized = str(raw_url or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _is_chat_link_context_enabled() -> bool:
    mode = str(getattr(settings, "deep_research_link_capture_mode", "attach_only") or "").strip().lower()
    return mode == "attach_and_chat_links"


def _extract_chat_link_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_REGEX.findall(text or ""):
        raw_candidate = str(match).strip()
        normalized = normalize_public_web_url(raw_candidate)
        if not normalized:
            parsed = urlparse(raw_candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                normalized = raw_candidate
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
        if len(urls) >= _MAX_LINK_CONTEXT_URLS:
            break
    return urls


async def _build_chat_link_context(user_text: str) -> str:
    if not _is_chat_link_context_enabled():
        return ""
    urls = _extract_chat_link_urls(user_text)
    if not urls:
        return ""

    semaphore = asyncio.Semaphore(min(len(urls), _MAX_LINK_CONTEXT_URLS))

    async def _fetch_with_limit(url: str) -> tuple[str, str]:
        async with semaphore:
            content = await fetch_webpage_excerpt(url)
            return url, content

    fetched = await asyncio.gather(*[_fetch_with_limit(url) for url in urls], return_exceptions=False)
    lines: list[str] = []
    for index, (url, content) in enumerate(fetched, start=1):
        excerpt = _trim_text(str(content or "").strip(), max(120, settings.deep_research_source_char_limit))
        if not excerpt:
            continue
        lines.append(f"[{index}] {url}\n{excerpt}")
    if not lines:
        return ""
    logger.info("chat_link_context.prepared", link_count=len(lines))
    merged = "\n\n".join(lines)
    total_budget = max(120, settings.memory_retrieval_token_budget)
    return "Context from links mentioned in the user message:\n" + _trim_text(merged, total_budget)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) // 2)


def _trim_text(text: str, token_budget: int) -> str:
    words = text.split()
    if len(words) <= token_budget:
        return text
    return " ".join(words[:token_budget])


def _extract_completion_content(completion: dict[str, Any]) -> str:
    return str((completion.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()


def _normalize_message_for_context(message: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(message)
    content = normalized.get("content")
    if isinstance(content, list):
        normalized["content"] = _extract_text(content)
    return normalized


def _trim_history_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_reversed: list[dict[str, Any]] = []
    token_budget = max(100, settings.memory_chat_history_token_budget)
    tokens_used = 0

    for raw_message in reversed(history):
        message = _normalize_message_for_context(raw_message)
        content = _extract_text(message.get("content"))
        msg_tokens = _estimate_tokens(content)
        if selected_reversed and (
            tokens_used + msg_tokens > token_budget or len(selected_reversed) >= settings.memory_max_recent_messages
        ):
            break
        selected_reversed.append(message)
        tokens_used += msg_tokens

    return list(reversed(selected_reversed))


def _build_memory_message(memory_items: list[str]) -> str:
    if not memory_items:
        return ""
    lines: list[str] = []
    used_tokens = 0
    budget = max(80, settings.memory_retrieval_token_budget)
    for item in memory_items:
        line = f"- {item}"
        line_tokens = _estimate_tokens(line)
        if lines and used_tokens + line_tokens > budget:
            break
        lines.append(line)
        used_tokens += line_tokens
    return "Relevant context from long-term memory:\n" + "\n".join(lines)


def _ghost_call(user_text: str) -> bool:
    ghost_keywords = (
        "### task:",
        "generate a concise",
        "relevant follow-up",
        "create a title",
        "generate tags",
        "suggest questions",
        "summarize the conversation",
    )
    lowered = user_text.lower()
    return any(keyword in lowered for keyword in ghost_keywords)


async def _classify_intent(user_text: str) -> str:
    if _ghost_call(user_text):
        return "SIMPLE"

    lowered = user_text.lower()
    heuristic_complex = (
        "code" in lowered
        or "backend" in lowered
        or "frontend" in lowered
        or "архитект" in lowered
        or "рефактор" in lowered
        or "программ" in lowered
        or "implement" in lowered
        or "debug" in lowered
    )
    if _should_use_stub_for_model(_INTENT_CLASSIFIER_MODEL):
        return "COMPLEX" if heuristic_complex else "SIMPLE"

    prompt = f"""User query: {user_text}

Determine if this is a software-development task that should run through an agentic coding workflow
(code generation, debugging, architecture, refactoring, implementation planning).
If the request is image generation, OCR/vision, general QA, or any non-coding task, return SIMPLE.
Respond with exactly one word: COMPLEX or SIMPLE."""
    try:
        response = await llm_router.generate_text(
            prompt=prompt,
            model=_INTENT_CLASSIFIER_MODEL,
            temperature=0.0,
            max_tokens=10,
            system_prompt="You are an intent classifier. Output only COMPLEX or SIMPLE.",
        )
    except Exception as exc:
        logger.warning("Intent classifier failed, using heuristic fallback", error=str(exc))
        return "COMPLEX" if heuristic_complex else "SIMPLE"

    if not isinstance(response, str):
        return "COMPLEX" if heuristic_complex else "SIMPLE"
    normalized = response.strip().upper()
    if normalized not in {"COMPLEX", "SIMPLE"}:
        return "COMPLEX" if heuristic_complex else "SIMPLE"
    return normalized


def _is_autopilot_enabled(payload: ChatCompletionRequest) -> bool:
    if payload.autopilot:
        return True
    if isinstance(payload.features, dict):
        return bool(payload.features.get("autopilot"))
    return False


_AUTOPILOT_RISKY_PATTERNS = (
    "rm -rf",
    "drop database",
    "truncate table",
    "delete all records",
    "shutdown production",
    "format disk",
    "wipe server",
)


def _is_risky_autopilot_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(marker in lowered for marker in _AUTOPILOT_RISKY_PATTERNS)


def _autopilot_guardrail_message(payload: ChatCompletionRequest, user_text: str) -> str | None:
    if not _is_autopilot_enabled(payload):
        return None

    if settings.autopilot_enable_cost_guard:
        prompt_tokens = sum(_estimate_tokens(_extract_text(message.content)) for message in payload.messages)
        if prompt_tokens > 1800:
            return (
                "Autopilot cost guard is enabled: this request is too large for safe agentic execution. "
                "Please reduce scope or split the task into smaller steps."
            )

    if settings.autopilot_enable_risk_guard and _is_risky_autopilot_request(user_text):
        if settings.autopilot_enable_human_handoff:
            return (
                "Risk guard blocked autonomous execution for this request. "
                "Please review this task manually or explicitly approve a human handoff."
            )
        return "Risk guard blocked this autopilot request."

    return None


async def _build_visual_context(payload: ChatCompletionRequest) -> str:
    image_urls = _last_user_image_urls(payload)
    if not image_urls:
        return ""

    extracted_chunks: list[str] = []
    per_image_budget = max(40, settings.memory_retrieval_token_budget // 2)

    for idx, image_url in enumerate(image_urls, start=1):
        try:
            completion = await llm_router.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You analyze images for downstream chat context. "
                            "Return plain concise text about visible objects, scene, layout, and non-text details. "
                            "If readable text exists, mention it briefly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the image for assistant context."},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
                model=_VISION_CONTEXT_MODEL,
                temperature=0.0,
                max_tokens=220,
            )
        except Exception as exc:
            logger.warning("Visual context extraction failed for attachment", index=idx, error=str(exc))
            continue

        text = _trim_text(_extract_completion_content(completion), per_image_budget)
        if not text:
            continue
        extracted_chunks.append(f"[image {idx}] {text}")

    if not extracted_chunks:
        return ""

    logger.info("Visual context prepared", image_count=len(image_urls), extracted_count=len(extracted_chunks))
    merged = "\n".join(f"- {chunk}" for chunk in extracted_chunks)
    total_budget = max(80, settings.memory_retrieval_token_budget)
    return "Visual context from attached images:\n" + _trim_text(merged, total_budget)


async def _build_prompt_context(
    payload: ChatCompletionRequest,
    *,
    user_id: str,
    thread_id: str,
    user_text: str,
) -> list[dict[str, Any]]:
    history = [message.model_dump() for message in payload.messages]
    trimmed_history = _trim_history_messages(history)

    summary_record = await get_thread_summary(user_id=user_id, thread_id=thread_id)
    summary_text = summary_record.summary if summary_record else ""
    summary_text = _trim_text(summary_text, max(40, settings.memory_summary_token_budget))

    memory_items = await recall_memories(
        user_id=user_id,
        query=user_text,
        top_k=max(settings.memory_recall_top_k, 3),
        thread_id=thread_id,
    )
    memory_message = _build_memory_message([item.content for item in memory_items])
    visual_message, link_message = await asyncio.gather(
        _build_visual_context(payload),
        _build_chat_link_context(user_text),
    )

    context_messages: list[dict[str, Any]] = []
    if summary_text:
        context_messages.append({"role": "system", "content": f"Thread summary:\n{summary_text}"})
    if memory_message:
        context_messages.append({"role": "system", "content": memory_message})
    if visual_message:
        context_messages.append({"role": "system", "content": visual_message})
    if link_message:
        context_messages.append({"role": "system", "content": link_message})
    context_messages.extend(trimmed_history)

    _MAX_TOTAL_CONTEXT_CHARS = 120_000
    total_chars = sum(len(_extract_text(m.get("content"))) for m in context_messages)
    while total_chars > _MAX_TOTAL_CONTEXT_CHARS and len(context_messages) > 2:
        removed = context_messages.pop(len([m for m in context_messages if m.get("role") == "system"]))
        total_chars -= len(_extract_text(removed.get("content")))

    return context_messages


def _stub_chat_completion(
    payload: ChatCompletionRequest,
    selected_model: str,
    user_text: str,
    context_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    context_note = ""
    for message in context_messages:
        if message.get("role") == "system" and "long-term memory" in _extract_text(message.get("content")):
            context_note = "\nLong-term memory was applied."
            break
    content = f"Stub response. model={selected_model}. Request: {user_text[:240]}{context_note}"
    prompt_tokens = sum(_estimate_tokens(_extract_text(message.content)) for message in payload.messages)
    completion_tokens = _estimate_tokens(content)
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": selected_model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": None, "function_call": None},
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _image_payload_to_markdown(image_payload: dict[str, Any]) -> str:
    items = image_payload.get("data", []) if isinstance(image_payload, dict) else []
    if not isinstance(items, list):
        items = []
    blocks: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            blocks.append(f"![generated image {idx}]({url.strip()})")
            continue
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64.strip():
            blocks.append(f"Generated image {idx}: base64 payload received ({len(b64)} chars).")
    if not blocks:
        return "Image generation completed."
    return "\n\n".join(blocks)


def _chat_completion_from_text(selected_model: str, user_messages: list[dict[str, Any]], content: str) -> dict[str, Any]:
    prompt_tokens = sum(_estimate_tokens(_extract_text(message.get("content"))) for message in user_messages)
    completion_tokens = _estimate_tokens(content)
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": selected_model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": None, "function_call": None},
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def _post_json_with_routing(
    *,
    path: str,
    requested_model: str | None,
    payload: dict[str, Any],
    messages: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    target = await llm_router.resolve_target_async(model=requested_model, messages=messages)
    request_payload = {**payload, "model": target.upstream_model}
    headers = {"Content-Type": "application/json"}
    if target.api_key:
        headers["Authorization"] = f"Bearer {target.api_key}"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{target.api_base.rstrip('/')}{path}", headers=headers, json=request_payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        raise AppError(
            code="upstream_error",
            message=f"Upstream request failed for {path}",
            details={"status_code": exc.response.status_code, "response": detail},
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise AppError(
            code="upstream_unreachable",
            message=f"Failed to reach upstream endpoint {path}",
            details={"error": str(exc)},
            status_code=502,
        ) from exc

    if isinstance(body, dict) and "model" not in body:
        body["model"] = target.upstream_model
    return target.upstream_model, body


async def _post_multipart_with_routing(
    *,
    path: str,
    requested_model: str | None,
    fields: dict[str, Any],
    file: UploadFile,
) -> tuple[str, dict[str, Any]]:
    target = await llm_router.resolve_target_async(model=requested_model, messages=None)
    headers: dict[str, str] = {}
    if target.api_key:
        headers["Authorization"] = f"Bearer {target.api_key}"

    file_bytes = await file.read()
    multipart = {"file": (file.filename or "audio.wav", file_bytes, file.content_type or "application/octet-stream")}
    data = {k: v for k, v in fields.items() if v is not None}
    data["model"] = target.upstream_model

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{target.api_base.rstrip('/')}{path}", headers=headers, data=data, files=multipart)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        raise AppError(
            code="upstream_error",
            message=f"Upstream request failed for {path}",
            details={"status_code": exc.response.status_code, "response": detail},
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise AppError(
            code="upstream_unreachable",
            message=f"Failed to reach upstream endpoint {path}",
            details={"error": str(exc)},
            status_code=502,
        ) from exc

    if isinstance(body, dict) and "model" not in body:
        body["model"] = target.upstream_model
    return target.upstream_model, body


async def _simple_response(
    payload: ChatCompletionRequest,
    selected_model: str,
    context_messages: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if _should_use_stub_for_model(selected_model):
        completion = _stub_chat_completion(
            payload=payload,
            selected_model=selected_model,
            user_text=_last_user_message(payload),
            context_messages=context_messages,
        )
        return completion["choices"][0]["message"]["content"], completion

    if selected_model in _IMAGE_MODELS:
        prompt = _last_user_message(payload).strip() or "Generate an image."
        routed_model, image_payload = await _post_json_with_routing(
            path="/images/generations",
            requested_model=selected_model,
            payload={"prompt": prompt, "n": 1},
            messages=context_messages,
        )
        assistant_text = _image_payload_to_markdown(image_payload)
        completion = _chat_completion_from_text(
            selected_model=routed_model,
            user_messages=[message.model_dump() for message in payload.messages],
            content=assistant_text,
        )
        return assistant_text, completion

    completion = await llm_router.chat_completion(
        messages=context_messages,
        model=selected_model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    assistant_text = completion["choices"][0]["message"]["content"]
    return assistant_text, completion


async def _complex_response(
    payload: ChatCompletionRequest,
    selected_model: str,
    user_id: str,
    thread_id: str,
    user_text: str,
    context_messages: list[dict[str, Any]],
) -> str:
    if _should_use_stub_for_model(selected_model):
        return _stub_chat_completion(payload, selected_model, user_text, context_messages)["choices"][0]["message"]["content"]

    max_attempts = 2 if settings.autopilot_enable_auto_retry else 1
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            create_initial_state, get_agent_graph = _graph_helpers()
            graph = await get_agent_graph()
            graph_input = create_initial_state(
                user_request=user_text,
                user_id=user_id,
                thread_id=thread_id,
                request_model=selected_model,
                messages=context_messages,
                memory_context="",
            )
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": settings.langgraph_recursion_limit}

            final_state = None
            async for state in graph.astream(graph_input, config):
                final_state = state

            if not final_state:
                return "Task completed."
            graph_output = list(final_state.values())[-1]
            if not isinstance(graph_output, dict):
                return "Task completed."
            return graph_output.get("final_response", "Task completed.")
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                logger.warning(
                    "Autopilot attempt failed, retrying",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(exc),
                )
                continue
            raise

    if last_error is not None:
        raise last_error
    return "Task completed."


async def _refresh_thread_summary(
    *,
    user_id: str,
    thread_id: str,
    selected_model: str,
) -> None:
    message_count = await count_thread_memories(user_id=user_id, thread_id=thread_id)
    if message_count < settings.memory_summary_min_messages:
        return
    if message_count % settings.memory_summary_interval != 0:
        return

    recent_memories = await list_thread_memories(
        user_id=user_id,
        thread_id=thread_id,
        limit=max(4, settings.memory_summary_window_messages),
    )
    if not recent_memories:
        return

    previous = await get_thread_summary(user_id=user_id, thread_id=thread_id)
    previous_summary = previous.summary if previous else ""

    condensed_messages = "\n".join(
        f"{memory.role}: {_trim_text(memory.content, 120)}" for memory in reversed(recent_memories)
    )

    if _should_use_stub_for_model(selected_model):
        merged = (previous_summary + "\n" + condensed_messages).strip()
        summary_text = _trim_text(merged, settings.memory_summary_token_budget * 2)
    else:
        prompt = f"""Summarize this thread for future context retrieval.
Keep only durable facts, decisions, constraints, and unresolved tasks.

Previous summary:
{previous_summary}

Recent dialogue:
{condensed_messages}
"""
        summary_text = await llm_router.generate_text(
            prompt=prompt,
            model=selected_model,
            temperature=0.2,
            max_tokens=max(200, settings.memory_summary_token_budget),
            system_prompt="You are a memory compressor. Output concise factual summary only.",
        )

    summary_text = _trim_text(summary_text, max(100, settings.memory_summary_token_budget * 2))
    await upsert_thread_summary(
        user_id=user_id,
        thread_id=thread_id,
        summary_text=summary_text,
        message_count=message_count,
    )


async def _persist_messages(
    *,
    user_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    selected_model: str,
) -> None:
    tags = ["chat", f"thread:{thread_id}"]
    if user_text:
        await create_memory(
            user_id=user_id,
            payload=MemoryCreateRequest(
                content=user_text,
                thread_id=thread_id,
                role="user",
                source="chat",
                tags=tags,
            ),
        )
    if assistant_text:
        await create_memory(
            user_id=user_id,
            payload=MemoryCreateRequest(
                content=assistant_text,
                thread_id=thread_id,
                role="assistant",
                source="chat",
                tags=tags,
            ),
        )
    await _refresh_thread_summary(user_id=user_id, thread_id=thread_id, selected_model=selected_model)


async def _ingest_media_gallery(
    *,
    payload: ChatCompletionRequest,
    user_id: str,
    thread_id: str,
    selected_model: str,
    user_text: str,
    assistant_text: str,
) -> None:
    uploads = _extract_media_payloads_from_last_user_message(payload)
    generated_urls = _extract_markdown_image_urls(assistant_text) if selected_model in _IMAGE_MODELS else []
    if not uploads and not generated_urls:
        return

    items: list[MediaGalleryIngestItem] = []
    for media in uploads:
        media_url = str(media.get("url") or "").strip()
        if not media_url:
            continue
        try:
            items.append(
                MediaGalleryIngestItem(
                    kind="upload",
                    media_url=media_url,
                    chat_id=payload.chat_id,
                    message_id=payload.parent_id,
                    thread_id=thread_id,
                    prompt_text=user_text,
                    model_id=selected_model,
                    provider=_provider_from_model(selected_model),
                    width=_coerce_non_negative_int(media.get("width")),
                    height=_coerce_non_negative_int(media.get("height")),
                    mime_type=str(media.get("mime_type") or "").strip(),
                    size_bytes=_coerce_non_negative_int(media.get("size_bytes")),
                    source_ref=str(media.get("source_ref") or media_url).strip(),
                )
            )
        except Exception as exc:
            logger.warning("media_gallery.upload_item_skipped", error=str(exc))
    for media_url in generated_urls:
        items.append(
            MediaGalleryIngestItem(
                kind="generated",
                media_url=media_url,
                thumbnail_url=media_url,
                chat_id=payload.chat_id,
                message_id=payload.id,
                thread_id=thread_id,
                prompt_text=user_text,
                model_id=selected_model,
                provider=_provider_from_model(selected_model),
                source_ref=media_url,
            )
        )
    if not items:
        return

    inserted = await ingest_media_gallery_items(user_id, items)
    if inserted:
        logger.info("media_gallery.ingested", inserted=inserted, owner_id=user_id)


def _validate_request(payload: ChatCompletionRequest) -> None:
    if len(payload.messages) > _MAX_MESSAGES:
        raise AppError(
            code="validation_error",
            message=f"Too many messages: maximum {_MAX_MESSAGES} allowed",
            details={"max_messages": _MAX_MESSAGES},
            status_code=422,
        )
    total_chars = 0
    for message in payload.messages:
        content = _extract_text(message.content)
        total_chars += len(content)
        if len(content) > _MAX_MESSAGE_LENGTH:
            raise AppError(
                code="validation_error",
                message=f"Message exceeds maximum length {_MAX_MESSAGE_LENGTH}",
                details={"max_message_length": _MAX_MESSAGE_LENGTH},
                status_code=422,
            )
    if total_chars > _MAX_TOTAL_PAYLOAD_CHARS:
        raise AppError(
            code="validation_error",
            message=f"Total payload size {total_chars} exceeds maximum {_MAX_TOTAL_PAYLOAD_CHARS} characters",
            details={"total_chars": total_chars, "max_total_chars": _MAX_TOTAL_PAYLOAD_CHARS},
            status_code=422,
        )


def validate_chat_completion_request(payload: ChatCompletionRequest) -> None:
    _validate_request(payload)


def _resolve_forced_task_type(payload: ChatCompletionRequest) -> str:
    top_level_direct = str(payload.auto_task_type_override or "").strip().upper()
    if top_level_direct:
        return top_level_direct

    top_level = ""
    if isinstance(payload.features, dict):
        top_level = str(payload.features.get("auto_task_type_override") or "").strip().upper()
        if top_level:
            return top_level

    metadata_features: dict[str, Any] | None = None
    if isinstance(payload.metadata, dict):
        raw_features = payload.metadata.get("features")
        if isinstance(raw_features, dict):
            metadata_features = raw_features
    if isinstance(metadata_features, dict):
        return str(metadata_features.get("auto_task_type_override") or "").strip().upper()
    return ""


async def chat_completion(payload: ChatCompletionRequest) -> dict[str, Any]:
    _validate_request(payload)

    request_messages_payload = [message.model_dump() for message in payload.messages]
    forced_task_type = _resolve_forced_task_type(payload)
    if forced_task_type:
        logger.info("Auto task type override received", forced_task_type=forced_task_type)
    routing_target = await llm_router.resolve_target_async(
        payload.model,
        request_messages_payload,
        forced_task_type=forced_task_type or None,
    )
    selected_model = routing_target.upstream_model
    routing_task_type = routing_target.routing_task_type
    routing_reason = routing_target.routing_reason
    user_id = _resolve_user_id(payload)
    thread_id = _resolve_thread_id(payload)
    user_text = _last_user_message(payload)
    context_messages = await _build_prompt_context(payload, user_id=user_id, thread_id=thread_id, user_text=user_text)
    autopilot_enabled = _is_autopilot_enabled(payload)
    model_court_enabled = (
        is_model_court_enabled(
            payload_model_court=bool(payload.model_court),
            features=payload.features if isinstance(payload.features, dict) else None,
            autopilot_enabled=autopilot_enabled,
        )
        and selected_model not in _IMAGE_MODELS
    )
    deep_research_requested = is_deep_research_enabled(
        payload_deep_research=bool(payload.deep_research),
        features=payload.features if isinstance(payload.features, dict) else None,
        autopilot_enabled=autopilot_enabled,
        model_court_enabled=model_court_enabled,
    )
    if deep_research_requested and selected_model in _IMAGE_MODELS:
        selected_model = _default_modality_model("chat")
    deep_research_enabled = deep_research_requested and selected_model not in _IMAGE_MODELS
    if autopilot_enabled:
        intent = "SIMPLE" if _ghost_call(user_text) else "COMPLEX"
        should_use_agentic = intent == "COMPLEX"
    else:
        intent = await _classify_intent(user_text=user_text)
        should_use_agentic = False
    if intent == "COMPLEX" and not should_use_agentic and _is_auto_model_requested(payload.model):
        selected_model = "qwen3-coder-480b-a35b"
    guardrail_message = _autopilot_guardrail_message(payload, user_text) if should_use_agentic else None
    if guardrail_message:
        should_use_agentic = False

    if not should_use_agentic:
        if guardrail_message:
            assistant_text = guardrail_message
            completion = _chat_completion_from_text(
                selected_model=selected_model,
                user_messages=[message.model_dump() for message in payload.messages],
                content=assistant_text,
            )
        elif deep_research_enabled:
            research_result = await run_deep_research(
                selected_model=selected_model,
                user_text=user_text,
                max_tokens=payload.max_tokens,
            )
            assistant_text = format_deep_research_answer(research_result)
            completion = _chat_completion_from_text(
                selected_model=selected_model,
                user_messages=request_messages_payload,
                content=assistant_text,
            )
        elif model_court_enabled:
            verdict = await run_model_court(
                selected_model=selected_model,
                request_messages=request_messages_payload,
                context_messages=context_messages,
                user_text=user_text,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            selected_model = verdict.winner_model
            assistant_text = format_model_court_answer(
                verdict.final_answer,
                verdict.rationale,
                winner_model=verdict.winner_model,
            )
            completion = _chat_completion_from_text(
                selected_model=selected_model,
                user_messages=request_messages_payload,
                content=assistant_text,
            )
        else:
            assistant_text, completion = await _simple_response(
                payload=payload,
                selected_model=selected_model,
                context_messages=context_messages,
            )
    else:
        assistant_text = await _complex_response(
            payload=payload,
            selected_model=selected_model,
            user_id=user_id,
            thread_id=thread_id,
            user_text=user_text,
            context_messages=context_messages,
        )
        prompt_tokens = sum(_estimate_tokens(_extract_text(message.content)) for message in payload.messages)
        completion_tokens = _estimate_tokens(assistant_text)
        completion = {
            "id": f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": selected_model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": assistant_text},
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    await _persist_messages(
        user_id=user_id,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        selected_model=selected_model,
    )
    try:
        await _ingest_media_gallery(
            payload=payload,
            user_id=user_id,
            thread_id=thread_id,
            selected_model=selected_model,
            user_text=user_text,
            assistant_text=assistant_text,
        )
    except Exception as exc:
        logger.warning("media_gallery.ingest_failed", error=str(exc))
    if settings.auto_show_routing_reason and _is_auto_model_requested(payload.model):
        completion["routing_task_type"] = routing_task_type
        completion["routing_reason"] = routing_reason
        completion["selected_model_id"] = selected_model
        completion["task_override_prompt_template"] = str(settings.auto_task_override_prompt_template)

    return completion


async def stream_chat_completion(payload: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    _validate_request(payload)

    completion_id = f"chatcmpl-{uuid4().hex[:12]}"
    created = int(time.time())
    selected_model = payload.model or "autoselect"
    routing_task_type = "GENERAL"
    routing_reason = ""
    assistant_text = ""
    agent_status_visible = False

    def _agent_status_chunk(*, description: str | None = None, hidden: bool = False) -> dict[str, Any]:
        status_data: dict[str, Any] = {"action": "agent_working"}
        if hidden:
            status_data["hidden"] = True
        elif description:
            status_data["description"] = description

        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": selected_model,
            "event": {"type": "status", "data": status_data},
        }

    try:
        request_messages_payload = [message.model_dump() for message in payload.messages]
        forced_task_type = _resolve_forced_task_type(payload)
        if forced_task_type:
            logger.info("Auto task type override received (stream)", forced_task_type=forced_task_type)
        routing_target = await llm_router.resolve_target_async(
            payload.model,
            request_messages_payload,
            forced_task_type=forced_task_type or None,
        )
        selected_model = routing_target.upstream_model
        routing_task_type = routing_target.routing_task_type
        routing_reason = routing_target.routing_reason
        user_id = _resolve_user_id(payload)
        thread_id = _resolve_thread_id(payload)
        user_text = _last_user_message(payload)
        context_messages = await _build_prompt_context(payload, user_id=user_id, thread_id=thread_id, user_text=user_text)

        autopilot_enabled = _is_autopilot_enabled(payload)
        model_court_enabled = (
            is_model_court_enabled(
                payload_model_court=bool(payload.model_court),
                features=payload.features if isinstance(payload.features, dict) else None,
                autopilot_enabled=autopilot_enabled,
            )
            and selected_model not in _IMAGE_MODELS
        )
        deep_research_requested = is_deep_research_enabled(
            payload_deep_research=bool(payload.deep_research),
            features=payload.features if isinstance(payload.features, dict) else None,
            autopilot_enabled=autopilot_enabled,
            model_court_enabled=model_court_enabled,
        )
        if deep_research_requested and selected_model in _IMAGE_MODELS:
            selected_model = _default_modality_model("chat")
        deep_research_enabled = deep_research_requested and selected_model not in _IMAGE_MODELS
        if autopilot_enabled:
            intent = "SIMPLE" if _ghost_call(user_text) else "COMPLEX"
            should_use_agentic = intent == "COMPLEX"
        else:
            intent = await _classify_intent(user_text=user_text)
            should_use_agentic = False
        if intent == "COMPLEX" and not should_use_agentic and _is_auto_model_requested(payload.model):
            selected_model = "qwen3-coder-480b-a35b"
        guardrail_message = _autopilot_guardrail_message(payload, user_text) if should_use_agentic else None
        if guardrail_message:
            should_use_agentic = False

        if not should_use_agentic:
            if guardrail_message:
                assistant_text = guardrail_message
            elif deep_research_enabled:
                agent_status_visible = True
                yield f"data: {json.dumps(_agent_status_chunk(description='🔎 Deep Research in progress...'), ensure_ascii=False)}\n\n"
                research_result = await run_deep_research(
                    selected_model=selected_model,
                    user_text=user_text,
                    max_tokens=payload.max_tokens,
                )
                assistant_text = format_deep_research_answer(research_result)
            elif model_court_enabled:
                verdict = await run_model_court(
                    selected_model=selected_model,
                    request_messages=request_messages_payload,
                    context_messages=context_messages,
                    user_text=user_text,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                )
                selected_model = verdict.winner_model
                assistant_text = format_model_court_answer(
                    verdict.final_answer,
                    verdict.rationale,
                    winner_model=verdict.winner_model,
                )
            else:
                assistant_text, _ = await _simple_response(
                    payload=payload,
                    selected_model=selected_model,
                    context_messages=context_messages,
                )
        else:
            if _should_use_stub_for_model(selected_model):
                assistant_text = _stub_chat_completion(payload, selected_model, user_text, context_messages)["choices"][0]["message"][
                    "content"
                ]
            else:
                publish_steps = settings.autopilot_enable_stream_steps and settings.autopilot_enable_partial_result_publish
                label_map = {
                    "designer": "🎨 UX/UI Designer",
                    "frontend_dev": "💻 Frontend Developer",
                    "backend_dev": "⚙️ Backend Developer",
                    "devops": "🐳 DevOps Engineer",
                    "qa_tester": "✅ QA Tester",
                }
                if publish_steps and settings.autopilot_enable_plan_preview:
                    agent_status_visible = True
                    yield f"data: {json.dumps(_agent_status_chunk(description='🧭 Planning autopilot execution...'), ensure_ascii=False)}\n\n"

                max_attempts = 2 if settings.autopilot_enable_auto_retry else 1
                final_state = None
                for attempt in range(1, max_attempts + 1):
                    announced_agent = None
                    try:
                        create_initial_state, get_agent_graph = _graph_helpers()
                        graph = await get_agent_graph()
                        graph_input = create_initial_state(
                            user_request=user_text,
                            user_id=user_id,
                            thread_id=thread_id,
                            request_model=selected_model,
                            messages=context_messages,
                            memory_context="",
                        )
                        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": settings.langgraph_recursion_limit}

                        final_state = None
                        async for state_update in graph.astream(graph_input, config):
                            final_state = state_update
                            if not state_update:
                                continue
                            node_name, node_state = next(iter(state_update.items()))
                            if not isinstance(node_state, dict):
                                continue

                            if not publish_steps:
                                continue

                            # Stream status immediately when supervisor assigns next agent.
                            # This avoids delayed updates that only appear after the previous agent finished.
                            next_agent = node_state.get("next_agent") if node_name == "supervisor" else None
                            active_agent = next_agent or node_state.get("current_agent")
                            if active_agent and active_agent not in {"FINISH", "end", "supervisor"} and active_agent != announced_agent:
                                announced_agent = active_agent
                                status_chunk = _agent_status_chunk(
                                    description=f"{label_map.get(active_agent, active_agent)} is working..."
                                )
                                agent_status_visible = True
                                yield f"data: {json.dumps(status_chunk, ensure_ascii=False)}\n\n"
                        break
                    except Exception as exc:
                        if attempt < max_attempts:
                            logger.warning(
                                "Autopilot stream attempt failed, retrying",
                                attempt=attempt,
                                max_attempts=max_attempts,
                                error=str(exc),
                            )
                            continue
                        raise

                if final_state:
                    output = list(final_state.values())[-1]
                    assistant_text = output.get("final_response", "Task completed.") if isinstance(output, dict) else "Task completed."
                else:
                    assistant_text = "Task completed."

    except Exception as exc:
        logger.error("stream_chat_completion failed", error=str(exc), error_type=exc.__class__.__name__)
        error_text = f"\n\n⚠️ Error: {exc.__class__.__name__}: {exc}"
        error_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": selected_model,
            "choices": [{"index": 0, "delta": {"content": error_text}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    if agent_status_visible:
        yield f"data: {json.dumps(_agent_status_chunk(hidden=True), ensure_ascii=False)}\n\n"

    for idx in range(0, len(assistant_text), 80):
        text_chunk = assistant_text[idx : idx + 80]
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": selected_model,
            "choices": [{"index": 0, "delta": {"content": text_chunk}, "finish_reason": None}],
        }
        if settings.auto_show_routing_reason and _is_auto_model_requested(payload.model):
            chunk["routing_task_type"] = routing_task_type
            chunk["routing_reason"] = routing_reason
            chunk["selected_model_id"] = selected_model
            chunk["task_override_prompt_template"] = str(settings.auto_task_override_prompt_template)
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": selected_model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    if settings.auto_show_routing_reason and _is_auto_model_requested(payload.model):
        final_chunk["routing_task_type"] = routing_task_type
        final_chunk["routing_reason"] = routing_reason
        final_chunk["selected_model_id"] = selected_model
        final_chunk["task_override_prompt_template"] = str(settings.auto_task_override_prompt_template)
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"

    await _persist_messages(
        user_id=user_id,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        selected_model=selected_model,
    )
    try:
        await _ingest_media_gallery(
            payload=payload,
            user_id=user_id,
            thread_id=thread_id,
            selected_model=selected_model,
            user_text=user_text,
            assistant_text=assistant_text,
        )
    except Exception as exc:
        logger.warning("media_gallery.ingest_failed", error=str(exc))


async def embeddings(payload: EmbeddingRequest) -> dict[str, Any]:
    requested_model = (payload.model or "").strip()
    if _is_auto_model_requested(requested_model):
        requested_model = _default_modality_model("embeddings")
    _, response = await _post_json_with_routing(
        path="/embeddings",
        requested_model=requested_model,
        payload={"input": payload.input, "user": payload.user},
        messages=None,
    )
    return response


async def images_generation(payload: ImageGenerationRequest) -> dict[str, Any]:
    requested_model = (payload.model or "").strip()
    if _is_auto_model_requested(requested_model):
        requested_model = _default_modality_model("image_generation")
    _, response = await _post_json_with_routing(
        path="/images/generations",
        requested_model=requested_model,
        payload={
            "prompt": payload.prompt,
            "n": payload.n,
            "size": payload.size,
            "response_format": payload.response_format,
            "user": payload.user,
        },
        messages=None,
    )
    return response


async def audio_transcription(
    *,
    file: UploadFile,
    model: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
    response_format: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    requested_model = (model or "").strip()
    if _is_auto_model_requested(requested_model):
        requested_model = _default_modality_model("audio_transcription")
    _, response = await _post_multipart_with_routing(
        path="/audio/transcriptions",
        requested_model=requested_model,
        file=file,
        fields={
            "language": language,
            "prompt": prompt,
            "response_format": response_format,
            "temperature": temperature,
        },
    )
    return response


async def list_models() -> dict[str, Any]:
    autoselect_entry = llm_router.get_autoselect_model_entry()
    models = await llm_router.list_available_models()
    if models:
        return {"object": "list", "data": [autoselect_entry, *models]}
    fallback_models = [
        {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "mws",
            "profile_image_url": str(settings.default_model_avatar_url),
            **llm_router.get_model_profile(model_id),
        }
        for model_id in sorted(MWS_AVAILABLE_MODELS)
    ]
    return {"object": "list", "data": [autoselect_entry, *fallback_models]}
