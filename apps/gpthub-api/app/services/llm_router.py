from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import litellm
import structlog

from app.core.config import settings
from app.modules.provider_connections.service import (
    get_enabled_provider_connection,
    list_enabled_provider_connections,
)

logger = structlog.get_logger(__name__)

# Configure LiteLLM
litellm.set_verbose = settings.debug

DEFAULT_MWS_MODEL = "mws-gpt-alpha"
AUTOSELECT_MODEL = "autoselect"
AUTOSELECT_ALIASES = {AUTOSELECT_MODEL, "auto"}
AUTOSELECT_TASK_LABELS = {"CODING", "IMAGE_GENERATION", "VISION", "REASONING", "GENERAL"}
_KEYWORD_LABELS = ("CODING", "IMAGE_GENERATION", "VISION", "REASONING", "GENERAL")
MWS_AVAILABLE_MODELS: Set[str] = {
    "deepseek-r1-distill-qwen-32b",
    "gpt-oss-20b",
    "cotype-pro-vl-32b",
    "llama-3.1-8b-instruct",
    "QwQ-32B",
    "qwen2.5-vl",
    "BAAI/bge-multilingual-gemma2",
    "gemma-3-27b-it",
    "qwen3-embedding-8b",
    "qwen3-vl-30b-a3b-instruct",
    "qwen2.5-72b-instruct",
    "mws-gpt-alpha",
    "qwen3-32b",
    "qwen2.5-vl-72b",
    "bge-m3",
    "gpt-oss-120b",
    "llama-3.3-70b-instruct",
    "kimi-k2-instruct",
    "Qwen3-235B-A22B-Instruct-2507-FP8",
    "whisper-medium",
    "whisper-turbo-local",
    "glm-4.6-357b",
    "qwen3-coder-480b-a35b",
    "T-pro-it-1.0",
    "qwen-image-lightning",
    "qwen-image",
}

MODEL_DESCRIPTIONS: Dict[str, Dict[str, Any]] = {
    "deepseek-r1-distill-qwen-32b": {
        "description": "Reasoning-focused model for complex analysis and step-by-step problem solving.",
        "category": "reasoning",
    },
    "gpt-oss-20b": {"description": "Compact open model for fast and low-cost general text tasks.", "category": "general"},
    "cotype-pro-vl-32b": {
        "description": "Vision-language model for image + text understanding tasks.",
        "category": "vision",
    },
    "llama-3.1-8b-instruct": {
        "description": "Lightweight instruction model for simple conversational tasks.",
        "category": "general",
    },
    "QwQ-32B": {"description": "Reasoning-capable model for analytical and mathematical requests.", "category": "reasoning"},
    "qwen2.5-vl": {"description": "Vision-language model for multimodal understanding (image + text).", "category": "vision"},
    "BAAI/bge-multilingual-gemma2": {
        "description": "Multilingual embedding model for semantic search/vectorization.",
        "category": "embedding",
    },
    "gemma-3-27b-it": {"description": "General instruction model for dialogue and content generation.", "category": "general"},
    "qwen3-embedding-8b": {"description": "Embedding model for retrieval and similarity search.", "category": "embedding"},
    "qwen3-vl-30b-a3b-instruct": {
        "description": "Advanced multimodal model for visual reasoning and image QA.",
        "category": "vision",
    },
    "qwen2.5-72b-instruct": {
        "description": "Large general-purpose model for quality chat and instruction following.",
        "category": "general",
    },
    "mws-gpt-alpha": {"description": "Balanced default MWS model for robust general dialogue and assistant tasks.", "category": "general"},
    "qwen3-32b": {"description": "General model with good balance of quality, speed, and cost.", "category": "general"},
    "qwen2.5-vl-72b": {"description": "High-quality vision-language model for complex image understanding.", "category": "vision"},
    "bge-m3": {"description": "Multilingual embedding model for memory and RAG retrieval.", "category": "embedding"},
    "gpt-oss-120b": {
        "description": "Large open model for high-quality text generation and long-form responses.",
        "category": "general",
    },
    "llama-3.3-70b-instruct": {
        "description": "Strong instruction model for broad conversational and reasoning tasks.",
        "category": "general",
    },
    "kimi-k2-instruct": {"description": "Instruction model optimized for coherent long-context interactions.", "category": "general"},
    "Qwen3-235B-A22B-Instruct-2507-FP8": {
        "description": "Very large premium model for difficult reasoning and high-stakes outputs.",
        "category": "reasoning",
    },
    "whisper-medium": {
        "description": "Speech-to-text ASR model for audio transcription (non-chat endpoint use).",
        "category": "audio",
    },
    "whisper-turbo-local": {
        "description": "Fast speech-to-text model for low-latency transcription (non-chat endpoint use).",
        "category": "audio",
    },
    "glm-4.6-357b": {"description": "Top-tier reasoning model for complex analytical and planning tasks.", "category": "reasoning"},
    "qwen3-coder-480b-a35b": {"description": "Code-specialized model for programming, debugging, and refactoring.", "category": "coding"},
    "T-pro-it-1.0": {"description": "Instruction-tuned model for general conversation and assistant workflows.", "category": "general"},
    "qwen-image-lightning": {"description": "Fast image generation model for creative image requests.", "category": "image_generation"},
    "qwen-image": {"description": "High-quality image generation model for detailed visual outputs.", "category": "image_generation"},
}


def _default_mws_model() -> str:
    configured = str(settings.mws_default_model or "").strip()
    if configured in MWS_AVAILABLE_MODELS:
        return configured
    return DEFAULT_MWS_MODEL


@dataclass(slots=True)
class RoutingTarget:
    provider: str
    connection_slug: str
    requested_model: str
    upstream_model: str
    api_base: str
    api_key: str
    routing_task_type: str = "GENERAL"
    routing_reason: str = ""


@dataclass(slots=True)
class ClassificationResult:
    label: str
    confidence: float
    reason: str


class LLMRouter:
    """Unified LLM router: MWS by default, plus dynamic OpenAI/Ollama upstreams via DB connections."""

    def __init__(self):
        # Global defaults are only for the MWS path.
        litellm.openai_key = settings.openai_api_key
        if settings.openai_base_url:
            litellm.api_base = settings.openai_base_url
            logger.info("Using default MWS API base", url=settings.openai_base_url)

    def _extract_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return " ".join(parts)
        return str(content or "")

    @staticmethod
    def _discover_keyword_dict_path() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "config" / "auto-model-keywords.json"
            if candidate.exists():
                return candidate
        return current.parent / "config" / "auto-model-keywords.json"

    @classmethod
    def _default_keyword_dictionary(cls) -> Dict[str, List[str]]:
        return {
            "CODING": ["code", "код", "debug", "ошибка", "bug", "fix", "refactor", "api", "sql", "docker"],
            "IMAGE_GENERATION": ["generate image", "сгенерируй изображ", "нарисуй", "картинку", "иллюстрац"],
            "VISION": ["ocr", "распознай текст", "что на изображении", "analyze image", "скриншот"],
            "REASONING": ["обоснуй", "пошагово", "докажи", "analyze", "reasoning", "trade-off"],
            "GENERAL": ["привет", "hello", "как дела", "what is", "объясни"],
        }

    @classmethod
    def _load_keyword_dictionary(cls) -> Dict[str, List[str]]:
        path = cls._discover_keyword_dict_path()
        if not path.exists():
            return cls._default_keyword_dictionary()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls._default_keyword_dictionary()

        labels = payload.get("labels") if isinstance(payload, dict) else None
        if not isinstance(labels, dict):
            return cls._default_keyword_dictionary()

        normalized: Dict[str, List[str]] = {}
        for label in _KEYWORD_LABELS:
            bucket = labels.get(label)
            if not isinstance(bucket, dict):
                continue
            values: List[str] = []
            for lang in ("ru", "en"):
                words = bucket.get(lang, [])
                if isinstance(words, list):
                    for item in words:
                        token = str(item or "").strip().lower()
                        if token:
                            values.append(token)
            # allow optional shared list
            shared = bucket.get("shared", [])
            if isinstance(shared, list):
                for item in shared:
                    token = str(item or "").strip().lower()
                    if token:
                        values.append(token)
            if values:
                normalized[label] = sorted(set(values))

        if not normalized:
            return cls._default_keyword_dictionary()
        return normalized

    _keyword_dictionary_cache: Dict[str, List[str]] | None = None

    @classmethod
    def _keyword_dictionary(cls) -> Dict[str, List[str]]:
        if cls._keyword_dictionary_cache is None:
            cls._keyword_dictionary_cache = cls._load_keyword_dictionary()
        return cls._keyword_dictionary_cache

    def _classify_autoselect_by_keywords(self, messages: List[Dict[str, Any]]) -> ClassificationResult:
        user_messages = [m for m in messages if m.get("role") == "user"]
        last_user = user_messages[-1] if user_messages else {}
        text = self._extract_text(last_user.get("content", "")).lower().strip()
        if not text:
            return ClassificationResult(label="GENERAL", confidence=0.0, reason="keyword:empty_input")

        scores: Dict[str, int] = {label: 0 for label in _KEYWORD_LABELS}
        dictionary = self._keyword_dictionary()
        for label, keywords in dictionary.items():
            hits = 0
            for keyword in keywords:
                if keyword in text:
                    hits += 1
            scores[label] = hits

        best_label = max(scores, key=scores.get)
        best_score = scores[best_label]
        second_score = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0

        # Ambiguous or no-signal keyword result -> treat as low-confidence GENERAL.
        if best_score <= 0:
            return ClassificationResult(label="GENERAL", confidence=0.0, reason="keyword:no_match")
        if best_score == second_score:
            return ClassificationResult(label="GENERAL", confidence=0.0, reason="keyword:ambiguous")

        confidence = max(0.0, min(1.0, best_score / max(1.0, best_score + second_score)))
        return ClassificationResult(
            label=best_label,
            confidence=confidence,
            reason=f"keyword:best={best_label},score={best_score},runner_up={second_score}",
        )

    def _autoselect_model_by_keywords(self, messages: List[Dict[str, Any]]) -> Tuple[str, str]:
        user_messages = [m for m in messages if m.get("role") == "user"]
        last_user = user_messages[-1] if user_messages else {}
        last_user_text = self._extract_text(last_user.get("content", "")).lower()

        has_image_input = False
        content = last_user.get("content", "")
        if isinstance(content, list):
            has_image_input = any(
                isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
                for part in content
            )

        image_gen_keywords = [
            "сгенерируй изображ", "создай картин", "нарисуй", "image generation", "generate image", "draw", "illustration", "logo", "баннер",
        ]
        coding_keywords = [
            "code", "coding", "bug", "debug", "refactor", "implementation", "python", "javascript", "typescript", "react", "fastapi", "sql",
            "docker", "api", "backend", "frontend", "тест", "ошибка", "исправь", "код", "программ", "разработ", "архитектур", "миграц",
        ]
        reasoning_keywords = [
            "пошаг", "обоснуй", "докажи", "проанализируй", "стратег", "план", "trade-off", "compare", "математ", "reason", "analyze deeply",
        ]
        continuation_keywords = ["продолж", "дальше", "continue", "добавь", "улучши"]

        if any(k in last_user_text for k in image_gen_keywords):
            return "qwen-image-lightning", "image_generation_request"

        if has_image_input:
            return "qwen2.5-vl-72b", "vision_input_detected"

        if any(k in last_user_text for k in coding_keywords):
            return "qwen3-coder-480b-a35b", "coding_request_detected"

        if any(k in last_user_text for k in continuation_keywords):
            assistant_messages = [m for m in messages if m.get("role") == "assistant"]
            if assistant_messages and "```" in self._extract_text(assistant_messages[-1].get("content", "")):
                return "qwen3-coder-480b-a35b", "code_context_continuation"

        if any(k in last_user_text for k in reasoning_keywords):
            return "glm-4.6-357b", "complex_reasoning_request"

        return _default_mws_model(), "default_general_dialogue"

    @staticmethod
    def _render_classifier_template(template: str, *, user_message: str) -> str:
        rendered = str(template or "")
        rendered = rendered.replace("{{user_message}}", user_message)
        rendered = rendered.replace("{user_message}", user_message)
        return rendered

    @staticmethod
    def _ensure_classifier_user_prompt(*, template: str, rendered_prompt: str, user_message: str) -> str:
        prompt_text = str(rendered_prompt or "").strip()
        user_text = str(user_message or "").strip()

        if not prompt_text:
            return user_text
        if not user_text:
            return prompt_text

        raw_template = str(template or "")
        has_user_placeholder = "{{user_message}}" in raw_template or "{user_message}" in raw_template
        if has_user_placeholder:
            return prompt_text

        # Keep routing resilient when a custom template forgets to include the user message placeholder.
        return f"{prompt_text}\n\nUser request:\n{user_text}"

    @staticmethod
    def _extract_label_from_text(raw: str) -> str:
        normalized = str(raw or "").strip().upper()
        if not normalized:
            return ""
        for token in re.findall(r"[A-Z_]+", normalized):
            if token in AUTOSELECT_TASK_LABELS:
                return token
        return ""

    @staticmethod
    def _extract_confidence_from_text(raw: str) -> Optional[float]:
        match = re.search(r"(?:confidence|score)\s*[:=]\s*([01](?:\.\d+)?)", str(raw or ""), flags=re.IGNORECASE)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, value))

    def _parse_classifier_response(self, raw_response: str) -> ClassificationResult:
        text = str(raw_response or "").strip()
        if not text:
            raise ValueError("Empty classifier response")

        # 1) JSON payload support: {"label":"CODING","confidence":0.92,"reason":"..."}
        payload: Dict[str, Any] = {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}

        if payload:
            label = self._extract_label_from_text(str(payload.get("label", "")))
            confidence_raw = payload.get("confidence")
            try:
                confidence = float(confidence_raw) if confidence_raw is not None else 1.0
            except (TypeError, ValueError):
                confidence = 1.0
            reason = str(payload.get("reason") or "").strip()
            if label:
                return ClassificationResult(
                    label=label,
                    confidence=max(0.0, min(1.0, confidence)),
                    reason=reason,
                )

        # 2) Plain text support (legacy): "CODING", "label=CODING confidence=0.8"
        label = self._extract_label_from_text(text)
        if not label:
            raise ValueError(f"Invalid classifier label: {text!r}")
        confidence = self._extract_confidence_from_text(text)
        return ClassificationResult(
            label=label,
            confidence=1.0 if confidence is None else confidence,
            reason=text[:240],
        )

    def _general_champion_model(self) -> str:
        candidate = str(settings.auto_task_model_general or "").strip()
        if candidate:
            return candidate
        return _default_mws_model()

    def _task_model_from_settings(self, label: str) -> str:
        normalized = str(label or "").strip().upper()
        mapping: Dict[str, str] = {
            "GENERAL": str(settings.auto_task_model_general or "").strip(),
            "CODING": str(settings.auto_task_model_coding or "").strip(),
            "REASONING": str(settings.auto_task_model_reasoning or "").strip(),
            "VISION": str(settings.auto_task_model_vision or "").strip(),
            "IMAGE_GENERATION": str(settings.auto_task_model_image_generation or "").strip(),
        }
        selected = mapping.get(normalized, "")
        return selected or self._general_champion_model()

    async def _classify_autoselect_task(self, messages: List[Dict[str, Any]]) -> ClassificationResult:
        user_messages = [m for m in messages if m.get("role") == "user"]
        last_user = user_messages[-1] if user_messages else {}
        last_user_text = self._extract_text(last_user.get("content", ""))

        content = last_user.get("content", "")
        has_image_input = False
        if isinstance(content, list):
            has_image_input = any(
                isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
                for part in content
            )
        if has_image_input:
            return ClassificationResult(label="VISION", confidence=1.0, reason="vision_input_detected")

        if not last_user_text.strip():
            return ClassificationResult(label="GENERAL", confidence=1.0, reason="empty_user_message")

        classifier_model = str(settings.auto_classifier_model or "").strip()
        if not classifier_model:
            raise ValueError("Classifier model is not configured")

        classifier_system_prompt = self._render_classifier_template(
            str(settings.auto_classifier_system_prompt_template or ""),
            user_message=last_user_text,
        )
        classifier_user_template = str(settings.auto_classifier_user_prompt_template or "")
        classifier_user_prompt = self._render_classifier_template(
            classifier_user_template,
            user_message=last_user_text,
        )
        classifier_user_prompt = self._ensure_classifier_user_prompt(
            template=classifier_user_template,
            rendered_prompt=classifier_user_prompt,
            user_message=last_user_text,
        )

        try:
            response = await asyncio.wait_for(
                self.generate_text(
                    prompt=classifier_user_prompt,
                    model=classifier_model,
                    temperature=float(settings.auto_classifier_temperature),
                    max_tokens=int(settings.auto_classifier_max_tokens),
                    system_prompt=classifier_system_prompt,
                ),
                timeout=float(settings.auto_classifier_timeout_seconds),
            )
            return self._parse_classifier_response(response)
        except Exception as exc:
            raise RuntimeError(f"classifier_failed:{exc}") from exc

    def _task_label_from_model(self, model: str) -> str:
        if model == "qwen3-coder-480b-a35b":
            return "CODING"
        if model in {"qwen-image-lightning", "qwen-image"}:
            return "IMAGE_GENERATION"
        if model in {"qwen2.5-vl-72b", "qwen2.5-vl", "qwen3-vl-30b-a3b-instruct"}:
            return "VISION"
        if model == "glm-4.6-357b":
            return "REASONING"
        return "GENERAL"

    async def _autoselect_model(self, messages: List[Dict[str, Any]]) -> Tuple[str, str]:
        general_champion = self._general_champion_model()
        confidence_threshold = float(settings.auto_classifier_confidence_threshold)

        try:
            classification = await self._classify_autoselect_task(messages)
        except Exception as exc:
            logger.warning("Autoselect classifier failed, trying keyword fallback", error=str(exc))
            keyword_classification = self._classify_autoselect_by_keywords(messages)
            if keyword_classification.confidence > 0:
                selected_model = self._task_model_from_settings(keyword_classification.label)
                return selected_model, (
                    "classifier_failed:keyword_fallback:"
                    f"label={keyword_classification.label},"
                    f"confidence={keyword_classification.confidence:.3f},"
                    f"reason={keyword_classification.reason}"
                )
            logger.warning(
                "Keyword fallback did not produce confident match, fallback to GENERAL champion",
                fallback_model=general_champion,
                keyword_reason=keyword_classification.reason,
            )
            return general_champion, "classifier_failed:keyword_unresolved:fallback_general_champion"

        if classification.confidence < confidence_threshold:
            keyword_classification = self._classify_autoselect_by_keywords(messages)
            if keyword_classification.confidence > 0:
                selected_model = self._task_model_from_settings(keyword_classification.label)
                logger.info(
                    "Autoselect classifier low confidence, using keyword fallback",
                    classifier_label=classification.label,
                    classifier_confidence=classification.confidence,
                    keyword_label=keyword_classification.label,
                    keyword_confidence=keyword_classification.confidence,
                    selected_model=selected_model,
                )
                return selected_model, (
                    "classifier_low_confidence:keyword_fallback:"
                    f"classifier_label={classification.label},"
                    f"classifier_confidence={classification.confidence:.3f},"
                    f"threshold={confidence_threshold:.3f},"
                    f"keyword_label={keyword_classification.label},"
                    f"keyword_confidence={keyword_classification.confidence:.3f},"
                    f"keyword_reason={keyword_classification.reason}"
                )

            logger.info(
                "Autoselect confidence below threshold, fallback to GENERAL champion",
                label=classification.label,
                confidence=classification.confidence,
                threshold=confidence_threshold,
                fallback_model=general_champion,
            )
            return general_champion, (
                f"classifier_low_confidence:"
                f"label={classification.label},confidence={classification.confidence:.3f},"
                f"threshold={confidence_threshold:.3f}"
            )

        selected_model = self._task_model_from_settings(classification.label)
        reason_tail = classification.reason or "ok"
        return selected_model, (
            f"classifier_success:"
            f"label={classification.label},confidence={classification.confidence:.3f},reason={reason_tail}"
        )

    def _parse_custom_model(self, raw_model: str) -> tuple[str, str, str] | None:
        # Format: <provider>/<connection-slug>/<upstream-model-id>
        for provider in ("openai", "ollama"):
            prefix = f"{provider}/"
            if raw_model.startswith(prefix):
                parts = raw_model.split("/", 2)
                if len(parts) == 3 and parts[1] and parts[2]:
                    return provider, parts[1], parts[2]
        return None

    async def _resolve_target(
        self,
        model: Optional[str],
        messages: Optional[List[Dict[str, Any]]] = None,
        forced_task_type: Optional[str] = None,
    ) -> RoutingTarget:
        raw_model = (model or "").strip()

        # Auto and plain models are always MWS-routed.
        if not raw_model or raw_model.lower() in AUTOSELECT_ALIASES:
            forced_label = str(forced_task_type or "").strip().upper()
            if forced_label in AUTOSELECT_TASK_LABELS:
                selected_model = self._task_model_from_settings(forced_label)
                routing_task_type = forced_label
                reason = (
                    "manual_task_type_override:"
                    f"label={forced_label},selected_model={selected_model},source=user_override"
                )
            else:
                selected_model, reason = await self._autoselect_model(messages or [])
                routing_task_type = "GENERAL"
                if "label=CODING" in reason:
                    routing_task_type = "CODING"
                elif "label=IMAGE_GENERATION" in reason:
                    routing_task_type = "IMAGE_GENERATION"
                elif "label=VISION" in reason:
                    routing_task_type = "VISION"
                elif "label=REASONING" in reason:
                    routing_task_type = "REASONING"
            logger.info(
                "Autoselect model decision",
                requested_model=model or AUTOSELECT_MODEL,
                selected_model=selected_model,
                reason=reason,
            )
            return RoutingTarget(
                provider="mws",
                connection_slug="default",
                requested_model=AUTOSELECT_MODEL,
                upstream_model=selected_model,
                api_base=settings.openai_base_url,
                api_key=settings.openai_api_key,
                routing_task_type=routing_task_type,
                routing_reason=reason,
            )

        # Support explicit mws/<model> alias.
        if raw_model.startswith("mws/"):
            raw_model = raw_model.split("/", 1)[1]

        custom = self._parse_custom_model(raw_model)
        if custom is not None:
            provider, connection_slug, upstream_model = custom
            connection = await get_enabled_provider_connection(provider=provider, slug=connection_slug)
            if connection is None:
                logger.warning("Custom provider connection not found or disabled", provider=provider, slug=connection_slug)
                fallback_model = _default_mws_model()
                return RoutingTarget(
                    provider="mws",
                    connection_slug="default",
                    requested_model=model or "",
                    upstream_model=fallback_model,
                    api_base=settings.openai_base_url,
                    api_key=settings.openai_api_key,
                    routing_task_type="GENERAL",
                    routing_reason="fallback:missing_connection",
                )
            return RoutingTarget(
                provider=provider,
                connection_slug=connection_slug,
                requested_model=model or "",
                upstream_model=upstream_model,
                api_base=connection.base_url,
                api_key=connection.api_key,
                routing_task_type="GENERAL",
                routing_reason="explicit_provider_model",
            )

        # Backward-compatible MWS models (with optional openai/ prefix from old code).
        if raw_model.startswith("openai/"):
            raw_model = raw_model.split("/", 1)[1]

        if raw_model in MWS_AVAILABLE_MODELS:
            return RoutingTarget(
                provider="mws",
                connection_slug="default",
                requested_model=model or raw_model,
                upstream_model=raw_model,
                api_base=settings.openai_base_url,
                api_key=settings.openai_api_key,
                routing_task_type="GENERAL",
                routing_reason="explicit_mws_model",
            )

        fallback_model = _default_mws_model()
        logger.warning(
            "Unsupported model requested, using fallback",
            requested_model=model,
            fallback_model=fallback_model,
        )
        return RoutingTarget(
            provider="mws",
            connection_slug="default",
            requested_model=model or "",
            upstream_model=fallback_model,
            api_base=settings.openai_base_url,
            api_key=settings.openai_api_key,
            routing_task_type="GENERAL",
            routing_reason="fallback:unsupported_model",
        )

    def resolve_model(self, model: Optional[str], messages: Optional[List[Dict[str, Any]]] = None) -> str:
        """Best-effort sync resolver used by pre-routing logic; provider models are passed through."""
        raw_model = (model or "").strip()
        if not raw_model:
            selected_model, _ = self._autoselect_model_by_keywords(messages or [])
            return selected_model
        if raw_model.lower() in AUTOSELECT_ALIASES:
            selected_model, _ = self._autoselect_model_by_keywords(messages or [])
            return selected_model
        if self._parse_custom_model(raw_model) is not None:
            return raw_model
        if raw_model.startswith("mws/"):
            raw_model = raw_model.split("/", 1)[1]
        if raw_model.startswith("openai/"):
            raw_model = raw_model.split("/", 1)[1]
        if raw_model in MWS_AVAILABLE_MODELS:
            return raw_model
        return _default_mws_model()

    async def resolve_model_async(
        self,
        model: Optional[str],
        messages: Optional[List[Dict[str, Any]]] = None,
        forced_task_type: Optional[str] = None,
    ) -> str:
        target = await self._resolve_target(model=model, messages=messages, forced_task_type=forced_task_type)
        return target.upstream_model

    async def resolve_target_async(
        self,
        model: Optional[str],
        messages: Optional[List[Dict[str, Any]]] = None,
        forced_task_type: Optional[str] = None,
    ) -> RoutingTarget:
        return await self._resolve_target(model=model, messages=messages, forced_task_type=forced_task_type)

    def get_model_profile(self, model_id: str) -> Dict[str, Any]:
        profile = MODEL_DESCRIPTIONS.get(model_id, {})
        if not profile:
            return {}
        return {
            "description": profile.get("description", ""),
            "category": profile.get("category", "general"),
        }

    def get_autoselect_model_entry(self) -> Dict[str, Any]:
        return {
            "id": AUTOSELECT_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "mws",
            "description": "Automatic model routing by task type (coding / vision / image generation / chat).",
            "category": "router",
            "profile_image_url": str(settings.default_model_avatar_url),
        }

    @staticmethod
    def _model_avatar(item: Dict[str, Any] | None = None) -> str:
        if item and isinstance(item, dict):
            existing = str(item.get("profile_image_url") or item.get("avatar_url") or "").strip()
            if existing:
                return existing
        return str(settings.default_model_avatar_url)

    async def _fetch_openai_models(self, base_url: str, api_key: str) -> List[Dict[str, Any]]:
        url = f"{base_url.rstrip('/')}/models"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()

        models = payload.get("data", []) if isinstance(payload, dict) else []
        return models if isinstance(models, list) else []

    async def _fetch_ollama_models(self, base_url: str) -> List[Dict[str, Any]]:
        url = f"{base_url.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()

        models = payload.get("models", []) if isinstance(payload, dict) else []
        return models if isinstance(models, list) else []

    async def list_available_models(self) -> List[Dict[str, Any]]:
        # 1) Base MWS models
        merged: List[Dict[str, Any]] = []
        for model_id in sorted(MWS_AVAILABLE_MODELS):
            merged.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "mws",
                    "profile_image_url": self._model_avatar(),
                    **self.get_model_profile(model_id),
                }
            )

        # 2) Dynamic provider connections (OpenAI/Ollama) routed through gpthub-api.
        connections = await list_enabled_provider_connections()
        for connection in connections:
            try:
                if connection.provider == "openai":
                    upstream_models = await self._fetch_openai_models(connection.base_url, connection.api_key)
                    for item in upstream_models:
                        if not isinstance(item, dict):
                            continue
                        upstream_id = str(item.get("id", "")).strip()
                        if not upstream_id:
                            continue
                        merged.append(
                            {
                                "id": f"openai/{connection.slug}/{upstream_id}",
                                "object": "model",
                                "created": 0,
                                "owned_by": f"openai:{connection.slug}",
                                "description": f"OpenAI upstream via {connection.display_name}",
                                "category": "external_openai",
                                "profile_image_url": self._model_avatar(item),
                                "metadata": {
                                    "provider": "openai",
                                    "connection_slug": connection.slug,
                                    "upstream_model": upstream_id,
                                },
                            }
                        )
                elif connection.provider == "ollama":
                    upstream_models = await self._fetch_ollama_models(connection.base_url)
                    for item in upstream_models:
                        if not isinstance(item, dict):
                            continue
                        upstream_id = str(item.get("model") or item.get("name") or "").strip()
                        if not upstream_id:
                            continue
                        merged.append(
                            {
                                "id": f"ollama/{connection.slug}/{upstream_id}",
                                "object": "model",
                                "created": 0,
                                "owned_by": f"ollama:{connection.slug}",
                                "description": f"Ollama upstream via {connection.display_name}",
                                "category": "external_ollama",
                                "profile_image_url": self._model_avatar(item),
                                "metadata": {
                                    "provider": "ollama",
                                    "connection_slug": connection.slug,
                                    "upstream_model": upstream_id,
                                },
                            }
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch provider models",
                    provider=connection.provider,
                    connection_slug=connection.slug,
                    error=str(exc),
                )

        return merged

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            requested_model = model if model is not None else _default_mws_model()
            target = await self._resolve_target(model=requested_model, messages=messages)
            if target.provider == "ollama":
                provider_model = (
                    target.upstream_model if target.upstream_model.startswith("ollama/") else f"ollama/{target.upstream_model}"
                )
            else:
                provider_model = (
                    target.upstream_model if "/" in target.upstream_model else f"openai/{target.upstream_model}"
                )

            logger.info(
                "Calling LLM",
                provider=target.provider,
                connection_slug=target.connection_slug,
                requested_model=target.requested_model,
                upstream_model=target.upstream_model,
                num_messages=len(messages),
                temperature=temperature,
            )

            try:
                response = await litellm.acompletion(
                    model=provider_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_base=target.api_base or None,
                    api_key=target.api_key or None,
                    **kwargs,
                )
            except Exception as primary_error:
                # Fallback only for MWS path
                fallback_model = _default_mws_model()
                if target.provider == "mws" and target.upstream_model != fallback_model:
                    logger.warning(
                        "Primary model failed, retrying with fallback",
                        selected_model=target.upstream_model,
                        fallback_model=fallback_model,
                        error=str(primary_error),
                    )
                    response = await litellm.acompletion(
                        model=f"openai/{fallback_model}",
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_base=settings.openai_base_url if settings.openai_base_url else None,
                        api_key=settings.openai_api_key if settings.openai_api_key else None,
                        **kwargs,
                    )
                    target.upstream_model = fallback_model
                else:
                    raise

            if response is None:
                raise ValueError("LLM returned None response")

            response_dict = response.model_dump() if hasattr(response, "model_dump") else dict(response)
            response_dict["model"] = target.upstream_model

            logger.info(
                "LLM response received",
                provider=target.provider,
                connection_slug=target.connection_slug,
                model=target.upstream_model,
                prompt_tokens=response_dict.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=response_dict.get("usage", {}).get("completion_tokens", 0),
            )
            return response_dict

        except Exception as exc:
            logger.error("LLM call failed", error=str(exc), model=model)
            raise

    async def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = await self.chat_completion(
            messages=messages,
            model=model if model is not None else _default_mws_model(),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not response:
            raise ValueError("Empty response from LLM")

        choices = response.get("choices", [])
        if not choices:
            raise ValueError("No choices in LLM response")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content:
            logger.warning("Empty content in LLM response", response=response)

        return content


llm_router = LLMRouter()
