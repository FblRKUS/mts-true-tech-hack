from __future__ import annotations

import structlog

from app.core.config import settings
from app.modules.auto_model.schemas import AutoModelRequest, AutoModelResponse, ModelCandidate, TaskDomain
from app.services.llm_router import llm_router

AUTOSELECT_MODEL_ID = "autoselect"
DEFAULT_MODEL_ID = "mws-gpt-alpha"
AUTO_MODEL_CLASSIFIER = "gpt-oss-20b"
_CLASSIFIER_LABEL_TO_DOMAIN: dict[str, TaskDomain] = {
    "CODING": "coding",
    "ANALYSIS": "analysis",
    "CREATIVE": "creative",
    "DOCUMENT": "document",
    "OCR": "ocr",
    "SUPPORT": "support",
    "GENERAL": "general",
}

logger = structlog.get_logger(__name__)

MODEL_PROFILES: dict[str, dict[str, str | float]] = {
    "mws-gpt-alpha": {"domain": "general", "quality": 0.9, "speed": 0.74, "context": "64k"},
    "qwen3-coder-480b-a35b": {"domain": "coding", "quality": 0.94, "speed": 0.66, "context": "64k"},
    "qwen2.5-vl-72b": {"domain": "ocr", "quality": 0.91, "speed": 0.63, "context": "32k"},
    "glm-4.6-357b": {"domain": "analysis", "quality": 0.95, "speed": 0.58, "context": "64k"},
    "qwen-image-lightning": {
        "domain": "creative",
        "quality": 0.86,
        "speed": 0.89,
        "context": "generation",
    },
    "qwen3-32b": {"domain": "support", "quality": 0.84, "speed": 0.84, "context": "32k"},
}

DOMAIN_KEYWORDS: dict[TaskDomain, tuple[str, ...]] = {
    "coding": (
        "code",
        "coding",
        "bug",
        "debug",
        "refactor",
        "implementation",
        "python",
        "javascript",
        "typescript",
        "react",
        "fastapi",
        "sql",
        "docker",
        "api",
        "backend",
        "frontend",
        "тест",
        "ошибка",
        "исправь",
        "код",
        "программ",
        "разработ",
        "архитектур",
        "миграц",
    ),
    "analysis": ("пошаг", "обоснуй", "докажи", "проанализируй", "стратег", "план", "trade-off", "compare"),
    "creative": ("сгенерируй изображ", "создай картин", "нарисуй", "generate image", "draw", "logo"),
    "document": ("pdf", "документ", "архив", "файл", "страница"),
    "ocr": ("ocr", "распознай", "текст на фото", "скрин"),
    "support": ("инструкц", "как", "помоги", "настроить"),
    "general": tuple(),
}
DOMAIN_PRIORITY: tuple[TaskDomain, ...] = ("creative", "coding", "analysis", "document", "ocr", "support")


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _default_model_id() -> str:
    configured = str(settings.mws_default_model or "").strip()
    if configured in MODEL_PROFILES:
        return configured
    return DEFAULT_MODEL_ID


def _provider_namespace(model_id: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return "mws"


def _infer_domain_by_keywords(message: str, input_type: str, explicit: TaskDomain | None) -> TaskDomain:
    if explicit:
        return explicit

    lowered = message.lower().strip()
    if input_type == "image":
        return "ocr"
    if input_type == "file":
        return "document"
    if input_type == "audio":
        return "support"

    for domain in DOMAIN_PRIORITY:
        if _contains_any(lowered, DOMAIN_KEYWORDS[domain]):
            return domain
    return "general"


async def infer_domain(message: str, input_type: str, explicit: TaskDomain | None) -> TaskDomain:
    if explicit or input_type in {"image", "file", "audio"}:
        return _infer_domain_by_keywords(message, input_type, explicit)

    if settings.mws_stub_mode or not settings.openai_api_key:
        return _infer_domain_by_keywords(message, input_type, explicit)

    prompt = f"""User request:
{message}

Classify this task into exactly one label:
- CODING
- ANALYSIS
- CREATIVE (image generation)
- DOCUMENT
- OCR
- SUPPORT
- GENERAL

Return only one label from the list."""
    try:
        response = await llm_router.generate_text(
            prompt=prompt,
            model=AUTO_MODEL_CLASSIFIER,
            temperature=0.0,
            max_tokens=8,
            system_prompt="You are a routing classifier. Output one label only.",
        )
        if isinstance(response, str):
            parts = response.strip().upper().split()
            if parts:
                label = parts[0].strip(".,:;\"'`")
                inferred = _CLASSIFIER_LABEL_TO_DOMAIN.get(label)
                if inferred:
                    return inferred
    except Exception as exc:
        logger.warning("Auto-model classifier failed, using keyword fallback", error=str(exc))

    return _infer_domain_by_keywords(message, input_type, explicit)


def pick_tool(domain: TaskDomain, input_type: str) -> str:
    if input_type == "image" or domain == "ocr":
        return "chat_completion"
    if input_type == "file" or domain == "document":
        return "chat_completion"
    if input_type == "audio":
        return "speech_pipeline"
    if domain == "creative":
        return "image_generation"
    return "chat_completion"


def _pick_model(domain: TaskDomain, input_type: str, message: str) -> tuple[str, str]:
    if settings.auto_enforce_model_profile:
        if domain == "creative":
            selected_model = "qwen-image-lightning"
            router_reason = "image_generation_request"
        elif input_type == "image" or domain == "ocr":
            selected_model = "qwen2.5-vl-72b"
            router_reason = "vision_input_detected"
        elif domain == "coding":
            selected_model = "qwen3-coder-480b-a35b"
            router_reason = "coding_request_detected"
        elif domain == "analysis":
            selected_model = "glm-4.6-357b"
            router_reason = "complex_reasoning_request"
        elif domain == "support":
            selected_model = "qwen3-32b"
            router_reason = "support_request_detected"
        else:
            selected_model = _default_model_id()
            router_reason = "default_general_dialogue"
    else:
        selected_model = _default_model_id()
        router_reason = "profile_enforcement_disabled"

    if settings.auto_auto_downgrade_on_latency and len(message.strip()) > 900:
        candidates = [
            model_id
            for model_id, profile in MODEL_PROFILES.items()
            if not settings.auto_enforce_model_profile or str(profile["domain"]) == domain
        ]
        if not candidates:
            candidates = list(MODEL_PROFILES.keys())
        fastest = max(candidates, key=lambda model_id: float(MODEL_PROFILES[model_id]["speed"]))
        if fastest != selected_model:
            selected_model = fastest
            router_reason = f"{router_reason}; latency_auto_downgrade"

    return selected_model, router_reason


def _score_candidates(domain: TaskDomain) -> list[tuple[str, float, str]]:
    scored: list[tuple[str, float, str]] = []
    for model_id, profile in MODEL_PROFILES.items():
        quality = float(profile["quality"])
        speed = float(profile["speed"])
        model_domain = str(profile["domain"])
        domain_bonus = 0.16 if model_domain == domain else 0.04
        score = max(0.0, min(1.0, 0.6 * quality + 0.3 * speed + domain_bonus))
        reason = f"domain={model_domain}, quality={quality:.2f}, speed={speed:.2f}, context={profile['context']}"
        scored.append((model_id, score, reason))

    return sorted(scored, key=lambda item: item[1], reverse=True)


async def route_request(payload: AutoModelRequest) -> AutoModelResponse:
    explicit_domain = payload.task_domain if settings.auto_enable_domain_hint else None
    domain = await infer_domain(payload.message, payload.input_type, explicit_domain)
    selected_tool = pick_tool(domain, payload.input_type)
    reasons: list[str] = []

    if payload.manual_model and not settings.auto_enable_manual_override:
        reasons.append("Ручной выбор модели отключен настройкой auto_enable_manual_override.")

    if payload.manual_model and settings.auto_enable_manual_override:
        manual_reasons = ["Пользователь выбрал модель вручную."]
        if not settings.auto_show_routing_reason:
            manual_reasons = []
        return AutoModelResponse(
            mode="manual",
            selected_model=payload.manual_model,
            selected_tool=selected_tool,
            inferred_domain=domain,
            confidence=1.0,
            reasons=manual_reasons,
            alternatives=[],
        )

    selected_model, router_reason = _pick_model(domain, payload.input_type, payload.message)
    ranked = _score_candidates(domain)

    if not settings.auto_allow_provider_mixing:
        selected_provider = _provider_namespace(selected_model)
        filtered_ranked = [item for item in ranked if _provider_namespace(item[0]) == selected_provider]
        if filtered_ranked:
            ranked = filtered_ranked

    score_map = {model_id: score for model_id, score, _ in ranked}
    reason_map = {model_id: reason for model_id, _, reason in ranked}
    selected_score = score_map.get(selected_model, 0.75)
    threshold = float(settings.auto_low_confidence_threshold)

    if selected_score < threshold:
        fallback_model = _default_model_id()
        if fallback_model != selected_model:
            selected_model = fallback_model
            router_reason = f"{router_reason}; low_confidence_fallback"
            selected_score = score_map.get(selected_model, selected_score)
        reasons.append(f"Уверенность ниже порога ({selected_score:.2f} < {threshold:.2f}), применен fallback.")

    alternatives = [
        ModelCandidate(model_id=model_id, score=round(score, 3), reason=reason)
        for model_id, score, reason in ranked
        if model_id != selected_model
    ][:2]

    reasons.extend(
        [
            f"Определен домен задачи: {domain}.",
            f"Роутинг: {router_reason}.",
            f"Профиль выбранной модели: {reason_map.get(selected_model, 'n/a')}.",
            f"Выбран инструмент: {selected_tool}.",
        ]
    )
    if payload.task_domain and not settings.auto_enable_domain_hint:
        reasons.append("Пользовательский domain_hint проигнорирован (auto_enable_domain_hint=false).")
    if settings.auto_show_latency_badge:
        speed = MODEL_PROFILES.get(selected_model, {}).get("speed")
        if isinstance(speed, (int, float)):
            reasons.append(f"Latency profile: speed={float(speed):.2f}.")
    if not settings.auto_allow_provider_mixing:
        reasons.append("Смешивание провайдеров отключено (auto_allow_provider_mixing=false).")
    if not settings.auto_show_routing_reason:
        reasons = []

    return AutoModelResponse(
        mode="auto",
        selected_model=selected_model,
        selected_tool=selected_tool,
        inferred_domain=domain,
        confidence=round(max(0.0, min(1.0, selected_score)), 3),
        reasons=reasons,
        alternatives=alternatives,
    )
