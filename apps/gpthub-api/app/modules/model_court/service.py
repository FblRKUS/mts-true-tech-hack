from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import structlog

from app.core.config import settings
from app.modules.model_court.schemas import ModelCourtCandidateResult, ModelCourtVerdict
from app.services.llm_router import llm_router

logger = structlog.get_logger(__name__)

_MODEL_COURT_IMAGE_MODELS = {"qwen-image-lightning", "qwen-image"}
_MODEL_COURT_VISION_POOL = ["qwen2.5-vl-72b", "qwen3-vl-30b-a3b-instruct", "glm-4.6-357b"]
_MODEL_COURT_CODING_POOL = ["qwen3-coder-480b-a35b", "glm-4.6-357b", "mws-gpt-alpha"]
_MODEL_COURT_REASONING_POOL = ["glm-4.6-357b", "qwen2.5-72b-instruct", "mws-gpt-alpha"]
_MODEL_COURT_GENERAL_POOL = ["mws-gpt-alpha", "qwen2.5-72b-instruct", "glm-4.6-357b"]
_JUDGE_LABELS = ("A", "B", "C", "D", "E", "F")


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return " ".join(parts).strip()
    return str(content or "")


def _has_image_input(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "") in {"image_url", "input_image"}:
                return True
        return False
    return False


def _detect_task_profile(user_text: str, messages: list[dict[str, Any]]) -> str:
    lowered = user_text.lower()
    if _has_image_input(messages):
        return "vision"
    if any(
        marker in lowered
        for marker in (
            "code",
            "coding",
            "debug",
            "refactor",
            "python",
            "javascript",
            "typescript",
            "backend",
            "frontend",
            "api",
            "sql",
            "исправ",
            "код",
            "реализ",
            "программ",
        )
    ):
        return "coding"
    if any(
        marker in lowered
        for marker in (
            "analyze",
            "reason",
            "compare",
            "trade-off",
            "strategy",
            "обоснуй",
            "проанализ",
            "сравни",
            "план",
        )
    ):
        return "reasoning"
    return "general"


def is_model_court_enabled(
    *,
    payload_model_court: bool,
    features: dict[str, Any] | None,
    autopilot_enabled: bool,
) -> bool:
    if autopilot_enabled:
        return False
    if not settings.model_court_enabled:
        return False
    if payload_model_court:
        return True
    if isinstance(features, dict):
        return bool(features.get("model_court"))
    return False


def select_candidate_models(
    *,
    selected_model: str,
    user_text: str,
    request_messages: list[dict[str, Any]],
) -> list[str]:
    target_count = max(2, int(settings.model_court_candidates_count))
    profile = _detect_task_profile(user_text=user_text, messages=request_messages)

    if profile == "vision":
        pool = _MODEL_COURT_VISION_POOL
    elif profile == "coding":
        pool = _MODEL_COURT_CODING_POOL
    elif profile == "reasoning":
        pool = _MODEL_COURT_REASONING_POOL
    else:
        pool = _MODEL_COURT_GENERAL_POOL

    ordered = [selected_model, *pool]
    candidates: list[str] = []
    seen: set[str] = set()
    for model_id in ordered:
        if not model_id or model_id in seen or model_id in _MODEL_COURT_IMAGE_MODELS:
            continue
        seen.add(model_id)
        candidates.append(model_id)
        if len(candidates) >= target_count:
            break

    return candidates


async def _run_candidate(
    *,
    label: str,
    model_id: str,
    context_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> ModelCourtCandidateResult:
    started = time.perf_counter()
    try:
        completion = await asyncio.wait_for(
            llm_router.chat_completion(
                messages=context_messages,
                model=model_id,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            timeout=float(settings.model_court_candidate_timeout_seconds),
        )
        response_text = str((completion.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if not response_text:
            raise ValueError("empty candidate response")
        return ModelCourtCandidateResult(
            label=label,
            model=model_id,
            response=response_text,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return ModelCourtCandidateResult(
            label=label,
            model=model_id,
            response="",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )


def _trim_candidate_text(text: str, max_chars: int = 5000) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _judge_prompt(
    *,
    user_text: str,
    candidates: list[ModelCourtCandidateResult],
    anonymous: bool,
) -> str:
    blocks: list[str] = []
    for candidate in candidates:
        header = f"Candidate {candidate.label}"
        if not anonymous:
            header += f" ({candidate.model})"
        blocks.append(f"{header}:\n{_trim_candidate_text(candidate.response)}")

    joined = "\n\n".join(blocks)
    return f"""You are an impartial model-judge.
Choose the best candidate answer for the user request.

User request:
{user_text}

Candidates:
{joined}

Evaluation criteria (priority order):
1) correctness and relevance,
2) completeness,
3) clarity and actionability,
4) safety and non-hallucination.

Return strict JSON only:
{{"winner_label":"A","rationale":"short explanation (1-2 sentences)"}}
"""


def _parse_judge_result(raw: str) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, ""

    def _winner_from_text(fallback_text: str) -> str | None:
        patterns = (
            r"(?i)\bwinner_label\b\s*[:=]\s*['\"]?([A-F])['\"]?",
            r"(?i)\b(?:winner|winning candidate|best candidate)\b[^\n]{0,80}?\b([A-F])\b",
            r"(?i)\b(?:победител[ья]|лучший кандидат)\b[^\n]{0,80}?\b([A-F])\b",
        )
        for pattern in patterns:
            match = re.search(pattern, fallback_text)
            if match:
                label = str(match.group(1) or "").strip().upper()
                if label in _JUDGE_LABELS:
                    return label
        return None

    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\{[\s\S]*?\}", text)
        if not match:
            winner = _winner_from_text(text)
            return winner, text[:220]
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            winner = _winner_from_text(text)
            return winner, text[:220]

    winner = str(parsed.get("winner_label") or "").strip().upper()
    rationale = str(parsed.get("rationale") or "").strip()
    if winner in _JUDGE_LABELS:
        return winner, rationale or text[:220]

    winner = _winner_from_text(text)
    if winner:
        return winner, rationale or text[:220]
    return None, rationale or text[:220]


def _sanitize_rationale(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    if "<think>" in text.lower():
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:220]


def _parse_winner_label(raw: str, labels_in_order: list[str] | None = None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    labels = labels_in_order or list(_JUDGE_LABELS)
    normalized = (
        text.replace("А", "A")
        .replace("а", "a")
        .replace("В", "B")
        .replace("в", "b")
        .replace("С", "C")
        .replace("с", "c")
        .replace("Е", "E")
        .replace("е", "e")
        .replace("Б", "B")
        .replace("б", "b")
    )
    compact = re.sub(r"[^A-Za-z]", "", normalized).upper()
    if len(compact) == 1 and compact in _JUDGE_LABELS:
        return compact
    numeric = re.search(r"\b([1-9])\b", normalized)
    if numeric:
        idx = int(numeric.group(1)) - 1
        if 0 <= idx < len(labels):
            return labels[idx]
    for pattern in (
        r"(?i)\bwinner_label\b\s*[:=]\s*['\"]?([A-F])['\"]?",
        r"(?i)\b(?:winner|winning candidate|best candidate|candidate|победител[ья]|кандидат)\b[^\n]{0,80}?\b([A-F])\b",
        r"\b([A-F])\b",
    ):
        match = re.search(pattern, normalized)
        if match:
            label = str(match.group(1) or "").strip().upper()
            if label in _JUDGE_LABELS:
                return label
    return None


def _fallback_winner(candidates: list[ModelCourtCandidateResult]) -> ModelCourtCandidateResult:
    return max(candidates, key=lambda item: (len(item.response), -item.latency_ms))


async def _judge_candidates(
    *,
    judge_model: str,
    user_text: str,
    candidates: list[ModelCourtCandidateResult],
) -> tuple[ModelCourtCandidateResult, str]:
    if len(candidates) == 1:
        return candidates[0], "Выбран единственный валидный кандидат."

    anonymous = bool(settings.model_court_enable_anonymous_judging)
    prompt = _judge_prompt(user_text=user_text, candidates=candidates, anonymous=anonymous)
    by_label = {candidate.label: candidate for candidate in candidates}
    candidate_labels = ", ".join(candidate.label for candidate in candidates)

    try:
        raw = await llm_router.generate_text(
            prompt=prompt,
            model=judge_model,
            temperature=0.0,
            max_tokens=320,
            system_prompt="You are a strict evaluator. Output JSON only.",
        )
        winner_label, rationale = _parse_judge_result(str(raw or ""))
        if winner_label:
            winner = by_label.get(winner_label)
            if winner is not None:
                clean_rationale = _sanitize_rationale(rationale)
                return winner, clean_rationale or "Победитель выбран судьей по качеству и релевантности."
        logger.warning(
            "Model court judge returned unparsable verdict",
            judge_model=judge_model,
            preview=str(raw or "")[:240],
        )

        # Recovery path: ask judge for label-only response to avoid JSON formatting failures.
        label_prompt = (
            f"Pick one best candidate label for the user request.\n"
            f"Allowed labels: {candidate_labels}\n"
            f"User request:\n{user_text}\n\n"
            f"Candidates:\n"
            + "\n\n".join(
                f"Candidate {candidate.label}:\n{_trim_candidate_text(candidate.response, max_chars=2200)}"
                for candidate in candidates
            )
            + "\n\nReturn ONLY one uppercase label (one character), nothing else."
        )

        for recovery_model in dict.fromkeys([judge_model, "mws-gpt-alpha"]):
            try:
                raw_label = await llm_router.generate_text(
                    prompt=label_prompt,
                    model=recovery_model,
                    temperature=0.0,
                    max_tokens=8,
                    system_prompt="Return exactly one uppercase label and nothing else.",
                )
                recovered_label = _parse_winner_label(
                    str(raw_label or ""),
                    labels_in_order=[candidate.label for candidate in candidates],
                )
                if recovered_label:
                    recovered_winner = by_label.get(recovered_label)
                    if recovered_winner is not None:
                        return recovered_winner, "Победитель выбран судьей (label-only recovery)."
                logger.warning(
                    "Model court label-only recovery unparsable",
                    judge_model=recovery_model,
                    preview=str(raw_label or "")[:120],
                )
            except Exception as recovery_exc:
                logger.warning(
                    "Model court label-only recovery failed",
                    judge_model=recovery_model,
                    error=str(recovery_exc),
                )
    except Exception as exc:
        logger.warning("Model court judge failed", error=str(exc), judge_model=judge_model)

    fallback = _fallback_winner(candidates)
    return fallback, "Судья недоступен или вернул невалидный вердикт: выбран лучший кандидат по fallback-эвристике."


def format_model_court_answer(final_answer: str, rationale: str, winner_model: str | None = None) -> str:
    winner_part = f"Победитель: `{winner_model}`. " if winner_model else ""
    return f"{final_answer}\n\n---\n**Model Court:** {winner_part}{rationale}"


async def run_model_court(
    *,
    selected_model: str,
    request_messages: list[dict[str, Any]],
    context_messages: list[dict[str, Any]],
    user_text: str,
    temperature: float,
    max_tokens: int | None,
) -> ModelCourtVerdict:
    candidate_models = select_candidate_models(
        selected_model=selected_model,
        user_text=user_text,
        request_messages=request_messages,
    )
    labels = list(_JUDGE_LABELS)
    tasks = [
        _run_candidate(
            label=labels[idx],
            model_id=model_id,
            context_messages=context_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for idx, model_id in enumerate(candidate_models)
    ]
    results = await asyncio.gather(*tasks)
    valid_results = [result for result in results if result.response]
    if not valid_results:
        errors = [f"{result.model}: {result.error or 'unknown error'}" for result in results]
        raise RuntimeError("All model court candidates failed: " + "; ".join(errors))

    winner, rationale = await _judge_candidates(
        judge_model=str(settings.model_court_judge_model or "glm-4.6-357b"),
        user_text=user_text,
        candidates=valid_results,
    )
    logger.info(
        "Model court completed",
        contender_count=len(candidate_models),
        valid_count=len(valid_results),
        winner_model=winner.model,
        winner_label=winner.label,
    )
    return ModelCourtVerdict(
        winner_label=winner.label,
        winner_model=winner.model,
        final_answer=winner.response,
        rationale=rationale or "Победитель выбран по качеству ответа.",
        candidates=results,
    )
