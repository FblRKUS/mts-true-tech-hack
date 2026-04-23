from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.modules.feature_settings.repository import feature_settings_repository
from app.modules.feature_settings.schemas import (
    ApplyClassifierWinnerPayload,
    BenchmarkHistoryEntry,
    BenchmarkHistoryResult,
    ClassifierBenchmarkEntry,
    ClassifierBenchmarkResult,
    FeatureSettingsPatchPayload,
    FeatureSettingsPayload,
    TextTournamentBenchmarkResult,
    TextBenchmarkEntry,
    TextBenchmarkResult,
    TournamentMatch,
    TournamentRound,
)
from app.services.llm_router import llm_router
from fastapi import UploadFile

_NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "langgraph_recursion_limit": (10, 200),
    "max_qa_iterations": (1, 12),
    "memory_recall_top_k": (1, 50),
    "memory_lexical_candidates": (50, 2000),
    "memory_thread_boost": (0.0, 2.0),
    "memory_chat_history_token_budget": (200, 16000),
    "memory_retrieval_token_budget": (100, 4000),
    "memory_summary_token_budget": (100, 4000),
    "memory_max_recent_messages": (4, 200),
    "memory_summary_interval": (1, 50),
    "memory_summary_window_messages": (4, 200),
    "memory_summary_min_messages": (1, 50),
    "auto_low_confidence_threshold": (0.5, 0.99),
    "auto_classifier_temperature": (0.0, 1.2),
    "auto_classifier_max_tokens": (4, 128),
    "auto_classifier_timeout_seconds": (3, 60),
    "auto_classifier_confidence_threshold": (0.0, 1.0),
    "model_court_candidates_count": (2, 6),
    "model_court_candidate_timeout_seconds": (10, 180),
    "deep_research_max_queries": (1, 8),
    "deep_research_max_sources": (1, 20),
    "deep_research_fetch_timeout_seconds": (3, 60),
    "deep_research_source_char_limit": (400, 12000),
    "deep_research_max_output_tokens": (200, 4000),
    "media_gallery_page_size": (6, 120),
    "media_gallery_max_filters": (1, 50),
    "media_gallery_retention_days": (1, 3650),
    "workspace_max_files_per_workspace": (100, 10000),
}

_INT_SETTINGS: set[str] = {
    "langgraph_recursion_limit",
    "max_qa_iterations",
    "memory_recall_top_k",
    "memory_lexical_candidates",
    "memory_chat_history_token_budget",
    "memory_retrieval_token_budget",
    "memory_summary_token_budget",
    "memory_max_recent_messages",
    "memory_summary_interval",
    "memory_summary_window_messages",
    "memory_summary_min_messages",
    "auto_classifier_max_tokens",
    "auto_classifier_timeout_seconds",
    "model_court_candidates_count",
    "model_court_candidate_timeout_seconds",
    "deep_research_max_queries",
    "deep_research_max_sources",
    "deep_research_fetch_timeout_seconds",
    "deep_research_source_char_limit",
    "deep_research_max_output_tokens",
    "media_gallery_page_size",
    "media_gallery_max_filters",
    "media_gallery_retention_days",
    "workspace_max_files_per_workspace",
}

_BOOL_SETTINGS: set[str] = {
    "mws_stub_mode",
    "auto_enable_manual_override",
    "auto_show_routing_reason",
    "auto_enable_domain_hint",
    "auto_enforce_model_profile",
    "auto_auto_downgrade_on_latency",
    "auto_show_latency_badge",
    "auto_allow_provider_mixing",
    "autopilot_enable_stream_steps",
    "autopilot_enable_auto_retry",
    "autopilot_enable_risk_guard",
    "autopilot_enable_partial_result_publish",
    "autopilot_enable_cost_guard",
    "autopilot_enable_plan_preview",
    "autopilot_enable_human_handoff",
    "model_court_enabled",
    "model_court_enable_anonymous_judging",
    "deep_research_enabled",
    "media_gallery_enabled",
    "workspace_enable_shared_workspaces",
    "workspace_enable_file_tree_sync",
    "workspace_enable_workspace_scoping",
    "workspace_enable_diff_preview",
    "workspace_enable_conflict_guards",
    "workspace_enable_session_locks",
    "workspace_enable_workspace_templates",
}

def _discover_config_path(filename: str) -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "config" / filename
        if candidate.exists():
            return candidate
    return current.parent / "config" / filename


_AUTO_MODEL_DEFAULTS_PATH = _discover_config_path("auto-model-defaults.json")
_CLASSIFIER_BENCHMARK_PATH = _discover_config_path("auto-model-classifier-benchmark.json")
_TEXT_BENCHMARK_PATH = _discover_config_path("auto-model-text-benchmark.json")
_AVATAR_DIR = Path(__file__).resolve().parents[2] / "assets" / "model_avatars"
_DEFAULT_AVATAR_BASENAME = "default_model_avatar_uploaded"
_DEFAULT_AVATAR_ROUTE = "/v1/assets/model-avatars/default"
_ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".svg"}


def _parse_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return fallback
    if isinstance(value, (int, float)):
        return bool(value)
    return fallback


def _clamp(key: str, value: Any) -> Any:
    if key in _NUMERIC_BOUNDS:
        lo, hi = _NUMERIC_BOUNDS[key]
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return getattr(settings, key)
        return max(lo, min(hi, numeric))
    return value


def _normalize_setting(key: str, value: Any) -> Any:
    if key in _NUMERIC_BOUNDS:
        clamped = _clamp(key, value)
        if key in _INT_SETTINGS:
            try:
                return int(float(clamped))
            except (TypeError, ValueError):
                return int(getattr(settings, key))
        return float(clamped)

    if key in _BOOL_SETTINGS:
        return _parse_bool(value, bool(getattr(settings, key)))

    if key == "mws_default_model":
        candidate = str(value or "").strip()
        return candidate or str(settings.mws_default_model)

    if key == "model_court_judge_model":
        candidate = str(value or "").strip()
        return candidate or str(settings.model_court_judge_model)

    if key in {
        "auto_classifier_model",
        "auto_task_model_general",
        "auto_task_model_coding",
        "auto_task_model_reasoning",
        "auto_task_model_vision",
        "auto_task_model_image_generation",
        "multimodal_stt_model",
    }:
        candidate = str(value or "").strip()
        fallback = str(getattr(settings, key))
        return candidate or fallback

    if key in {"auto_classifier_system_prompt_template", "auto_classifier_user_prompt_template"}:
        candidate = str(value or "").strip()
        fallback = str(getattr(settings, key))
        return candidate or fallback

    if key == "auto_task_override_prompt_template":
        candidate = str(value or "").strip()
        fallback = str(getattr(settings, key))
        return candidate or fallback

    if key == "default_model_avatar_url":
        candidate = str(value or "").strip()
        return candidate or str(settings.default_model_avatar_url)

    if key == "auto_model_type_overrides_json":
        candidate = str(value or "").strip()
        return candidate or str(settings.auto_model_type_overrides_json)

    if key == "deep_research_link_capture_mode":
        candidate = str(value or "").strip().lower()
        if candidate in {"attach_only", "attach_and_chat_links"}:
            return candidate
        return str(getattr(settings, key))

    return value


def _apply_setting(key: str, value: Any) -> None:
    if not hasattr(settings, key):
        return
    setattr(settings, key, value)


def _current_settings() -> FeatureSettingsPayload:
    return FeatureSettingsPayload(
        mws_stub_mode=bool(settings.mws_stub_mode),
        mws_default_model=str(settings.mws_default_model),
        langgraph_recursion_limit=int(settings.langgraph_recursion_limit),
        max_qa_iterations=int(settings.max_qa_iterations),
        memory_recall_top_k=int(settings.memory_recall_top_k),
        memory_lexical_candidates=int(settings.memory_lexical_candidates),
        memory_thread_boost=float(settings.memory_thread_boost),
        memory_chat_history_token_budget=int(settings.memory_chat_history_token_budget),
        memory_retrieval_token_budget=int(settings.memory_retrieval_token_budget),
        memory_summary_token_budget=int(settings.memory_summary_token_budget),
        memory_max_recent_messages=int(settings.memory_max_recent_messages),
        memory_summary_interval=int(settings.memory_summary_interval),
        memory_summary_window_messages=int(settings.memory_summary_window_messages),
        memory_summary_min_messages=int(settings.memory_summary_min_messages),
        auto_enable_manual_override=bool(settings.auto_enable_manual_override),
        auto_show_routing_reason=bool(settings.auto_show_routing_reason),
        auto_enable_domain_hint=bool(settings.auto_enable_domain_hint),
        auto_enforce_model_profile=bool(settings.auto_enforce_model_profile),
        auto_auto_downgrade_on_latency=bool(settings.auto_auto_downgrade_on_latency),
        auto_show_latency_badge=bool(settings.auto_show_latency_badge),
        auto_allow_provider_mixing=bool(settings.auto_allow_provider_mixing),
        auto_low_confidence_threshold=float(settings.auto_low_confidence_threshold),
        auto_classifier_temperature=float(settings.auto_classifier_temperature),
        auto_classifier_max_tokens=int(settings.auto_classifier_max_tokens),
        auto_classifier_timeout_seconds=int(settings.auto_classifier_timeout_seconds),
        auto_classifier_confidence_threshold=float(settings.auto_classifier_confidence_threshold),
        auto_classifier_system_prompt_template=str(settings.auto_classifier_system_prompt_template),
        auto_classifier_user_prompt_template=str(settings.auto_classifier_user_prompt_template),
        auto_classifier_model=str(settings.auto_classifier_model),
        auto_task_model_general=str(settings.auto_task_model_general),
        auto_task_model_coding=str(settings.auto_task_model_coding),
        auto_task_model_reasoning=str(settings.auto_task_model_reasoning),
        auto_task_model_vision=str(settings.auto_task_model_vision),
        auto_task_model_image_generation=str(settings.auto_task_model_image_generation),
        auto_model_type_overrides_json=str(settings.auto_model_type_overrides_json),
        auto_task_override_prompt_template=str(settings.auto_task_override_prompt_template),
        default_model_avatar_url=str(settings.default_model_avatar_url),
        multimodal_stt_model=str(settings.multimodal_stt_model),
        autopilot_enable_stream_steps=bool(settings.autopilot_enable_stream_steps),
        autopilot_enable_auto_retry=bool(settings.autopilot_enable_auto_retry),
        autopilot_enable_risk_guard=bool(settings.autopilot_enable_risk_guard),
        autopilot_enable_partial_result_publish=bool(settings.autopilot_enable_partial_result_publish),
        autopilot_enable_cost_guard=bool(settings.autopilot_enable_cost_guard),
        autopilot_enable_plan_preview=bool(settings.autopilot_enable_plan_preview),
        autopilot_enable_human_handoff=bool(settings.autopilot_enable_human_handoff),
        model_court_enabled=bool(settings.model_court_enabled),
        model_court_candidates_count=int(settings.model_court_candidates_count),
        model_court_candidate_timeout_seconds=int(settings.model_court_candidate_timeout_seconds),
        model_court_judge_model=str(settings.model_court_judge_model),
        model_court_enable_anonymous_judging=bool(settings.model_court_enable_anonymous_judging),
        deep_research_enabled=bool(settings.deep_research_enabled),
        deep_research_max_queries=int(settings.deep_research_max_queries),
        deep_research_max_sources=int(settings.deep_research_max_sources),
        deep_research_fetch_timeout_seconds=int(settings.deep_research_fetch_timeout_seconds),
        deep_research_source_char_limit=int(settings.deep_research_source_char_limit),
        deep_research_max_output_tokens=int(settings.deep_research_max_output_tokens),
        deep_research_link_capture_mode=str(settings.deep_research_link_capture_mode),
        media_gallery_enabled=bool(settings.media_gallery_enabled),
        media_gallery_page_size=int(settings.media_gallery_page_size),
        media_gallery_max_filters=int(settings.media_gallery_max_filters),
        media_gallery_retention_days=int(settings.media_gallery_retention_days),
        workspace_enable_shared_workspaces=bool(settings.workspace_enable_shared_workspaces),
        workspace_enable_file_tree_sync=bool(settings.workspace_enable_file_tree_sync),
        workspace_enable_workspace_scoping=bool(settings.workspace_enable_workspace_scoping),
        workspace_enable_diff_preview=bool(settings.workspace_enable_diff_preview),
        workspace_enable_conflict_guards=bool(settings.workspace_enable_conflict_guards),
        workspace_enable_session_locks=bool(settings.workspace_enable_session_locks),
        workspace_enable_workspace_templates=bool(settings.workspace_enable_workspace_templates),
        workspace_max_files_per_workspace=int(settings.workspace_max_files_per_workspace),
    )


async def load_feature_settings_overrides() -> FeatureSettingsPayload:
    await _apply_bootstrap_defaults()
    rows = await feature_settings_repository.list_all()
    for row in rows:
        key = row.key
        value = row.value.get("value") if isinstance(row.value, dict) else row.value
        if value is None:
            continue
        value = _normalize_setting(key, value)
        _apply_setting(key, value)
    return _current_settings()


async def get_feature_settings() -> FeatureSettingsPayload:
    return _current_settings()


async def update_feature_settings(payload: FeatureSettingsPatchPayload) -> FeatureSettingsPayload:
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        value = _normalize_setting(key, value)
        await feature_settings_repository.upsert(key=key, value={"value": value})
        _apply_setting(key, value)
    return _current_settings()


def _read_auto_model_defaults() -> dict[str, Any]:
    if not _AUTO_MODEL_DEFAULTS_PATH.exists():
        return {}
    try:
        parsed = json.loads(_AUTO_MODEL_DEFAULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _parse_model_type_overrides() -> dict[str, str]:
    try:
        parsed = json.loads(str(settings.auto_model_type_overrides_json or "{}"))
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    normalized: dict[str, str] = {}
    for model_id, task_type in parsed.items():
        key = str(model_id or "").strip()
        value = str(task_type or "").strip().upper()
        if key and value:
            normalized[key] = value
    return normalized


def _classifier_candidate_models() -> list[str]:
    overrides = _parse_model_type_overrides()
    candidates = [
        model_id
        for model_id, task_type in overrides.items()
        if task_type in {"GENERAL", "CODING", "REASONING"}
    ]
    if not candidates:
        fallback = str(settings.auto_classifier_model or "").strip()
        if fallback:
            candidates = [fallback]
    return sorted(set(candidates))


def _task_category_candidate_models(category: str) -> list[str]:
    normalized = str(category or "").strip().upper()
    overrides = _parse_model_type_overrides()
    models = [model_id for model_id, task_type in overrides.items() if task_type == normalized]
    if not models:
        fallback_map = {
            "GENERAL": str(settings.auto_task_model_general or "").strip(),
            "CODING": str(settings.auto_task_model_coding or "").strip(),
            "REASONING": str(settings.auto_task_model_reasoning or "").strip(),
        }
        fallback = fallback_map.get(normalized, "")
        if fallback:
            models = [fallback]
    return sorted(set(models))


def _read_classifier_benchmark_dataset() -> list[dict[str, str]]:
    if not _CLASSIFIER_BENCHMARK_PATH.exists():
        return []
    try:
        parsed = json.loads(_CLASSIFIER_BENCHMARK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        label = str(item.get("label") or "").strip().upper()
        if question and label in {"GENERAL", "CODING", "REASONING", "VISION", "IMAGE_GENERATION"}:
            normalized.append({"question": question, "label": label})
    return normalized


def _read_text_benchmark_dataset() -> list[dict[str, str]]:
    if not _TEXT_BENCHMARK_PATH.exists():
        return []
    try:
        parsed = json.loads(_TEXT_BENCHMARK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip().upper()
        prompt = str(item.get("prompt") or "").strip()
        if category in {"GENERAL", "CODING", "REASONING"} and prompt:
            normalized.append({"category": category, "prompt": prompt})
    return normalized


def _extract_classifier_label(response: str) -> str:
    text = str(response or "").upper()
    for token in ("CODING", "IMAGE_GENERATION", "VISION", "REASONING", "GENERAL"):
        if token in text:
            return token
    return ""


def _compute_classifier_metrics(y_true: list[str], y_pred: list[str]) -> tuple[float, float]:
    total = len(y_true)
    if total == 0:
        return 0.0, 0.0
    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    accuracy = correct / total

    labels = sorted(set(y_true) | set(y_pred))
    if not labels:
        return round(accuracy, 4), 0.0
    f1_scores: list[float] = []
    for label in labels:
        tp = sum(1 for a, b in zip(y_true, y_pred) if a == label and b == label)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a != label and b == label)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == label and b != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        if precision + recall == 0:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
        f1_scores.append(f1)
    macro_f1 = sum(f1_scores) / len(f1_scores)
    return round(accuracy, 4), round(macro_f1, 4)


async def run_classifier_benchmark() -> ClassifierBenchmarkResult:
    dataset = _read_classifier_benchmark_dataset()
    candidates = _classifier_candidate_models()
    if not dataset or not candidates:
        return ClassifierBenchmarkResult(entries=[], winner_model_id=None)

    entries: list[ClassifierBenchmarkEntry] = []
    for model_id in candidates:
        y_true: list[str] = []
        y_pred: list[str] = []
        for item in dataset:
            question = item["question"]
            expected = item["label"]
            try:
                response = await llm_router.generate_text(
                    prompt=str(settings.auto_classifier_user_prompt_template).replace("{{user_message}}", question),
                    model=model_id,
                    temperature=float(settings.auto_classifier_temperature),
                    max_tokens=int(settings.auto_classifier_max_tokens),
                    system_prompt=str(settings.auto_classifier_system_prompt_template),
                )
                predicted = _extract_classifier_label(response)
            except Exception:
                predicted = ""
            y_true.append(expected)
            y_pred.append(predicted if predicted else "GENERAL")

        accuracy, macro_f1 = _compute_classifier_metrics(y_true, y_pred)
        correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
        entries.append(
            ClassifierBenchmarkEntry(
                model_id=model_id,
                accuracy=accuracy,
                macro_f1=macro_f1,
                correct=correct,
                total=len(y_true),
            )
        )

    entries.sort(key=lambda e: (e.macro_f1, e.accuracy), reverse=True)
    winner = entries[0].model_id if entries else None
    result = ClassifierBenchmarkResult(entries=entries, winner_model_id=winner)
    await _append_benchmark_history(
        benchmark_type="classifier",
        summary={
            "winner_model_id": winner,
            "entries_count": len(entries),
            "top_accuracy": entries[0].accuracy if entries else 0.0,
            "top_macro_f1": entries[0].macro_f1 if entries else 0.0,
        },
    )
    return result


async def apply_classifier_winner(payload: ApplyClassifierWinnerPayload) -> FeatureSettingsPayload:
    model_id = str(payload.model_id or "").strip()
    if not model_id:
        return _current_settings()
    normalized = _normalize_setting("auto_classifier_model", model_id)
    await feature_settings_repository.upsert(key="auto_classifier_model", value={"value": normalized})
    _apply_setting("auto_classifier_model", normalized)
    return _current_settings()


async def run_text_benchmark() -> TextBenchmarkResult:
    dataset = _read_text_benchmark_dataset()
    if not dataset:
        return TextBenchmarkResult(entries=[])

    entries: list[TextBenchmarkEntry] = []
    for category in ("GENERAL", "CODING", "REASONING"):
        prompts = [item["prompt"] for item in dataset if item["category"] == category]
        if not prompts:
            continue
        candidates = _task_category_candidate_models(category)
        for model_id in candidates:
            answered = 0
            score_total = 0.0
            for prompt in prompts:
                try:
                    response = await llm_router.generate_text(
                        prompt=prompt,
                        model=model_id,
                        temperature=0.2,
                        max_tokens=256,
                    )
                    text = str(response or "").strip()
                    if text:
                        answered += 1
                        # lightweight heuristic score for launch stage
                        score_total += min(1.0, max(0.2, len(text) / 400.0))
                except Exception:
                    continue
            total = len(prompts)
            score = round((score_total / total) if total else 0.0, 4)
            entries.append(
                TextBenchmarkEntry(
                    category=category,
                    model_id=model_id,
                    score=score,
                    answered=answered,
                    total=total,
                )
            )
    result = TextBenchmarkResult(entries=entries)
    await _append_benchmark_history(
        benchmark_type="text",
        summary={
            "entries_count": len(entries),
            "categories": sorted(set(item.category for item in entries)),
        },
    )
    return result


def _judge_pick_winner(model_a: str, answer_a: str, model_b: str, answer_b: str, category: str) -> tuple[str, str]:
    prompt = (
        "You are a strict benchmark judge.\n"
        f"Category: {category}\n"
        "Pick exactly one winner between A and B.\n"
        "Criteria: correctness, relevance, clarity, completeness.\n"
        "Return JSON: {\"winner\":\"A\"|\"B\",\"reason\":\"short\"}\n\n"
        f"A ({model_a}):\n{answer_a}\n\n"
        f"B ({model_b}):\n{answer_b}\n"
    )
    return prompt


async def _judge_match(model_a: str, answer_a: str, model_b: str, answer_b: str, category: str) -> tuple[str, str]:
    judge_model = str(settings.model_court_judge_model or "").strip() or str(settings.auto_classifier_model or "")
    prompt = _judge_pick_winner(model_a, answer_a, model_b, answer_b, category)
    try:
        response = await llm_router.generate_text(
            prompt=prompt,
            model=judge_model,
            temperature=0.0,
            max_tokens=64,
            system_prompt="Return compact JSON only.",
        )
        text = str(response or "").strip()
        parsed = json.loads(text) if text.startswith("{") else {}
        winner = str(parsed.get("winner", "")).strip().upper()
        reason = str(parsed.get("reason", "")).strip() or "judge_decision"
        if winner == "A":
            return model_a, reason
        if winner == "B":
            return model_b, reason
    except Exception:
        pass
    # deterministic fallback
    score_a = len((answer_a or "").strip())
    score_b = len((answer_b or "").strip())
    if score_a >= score_b:
        return model_a, "fallback_length_heuristic"
    return model_b, "fallback_length_heuristic"


async def run_text_tournament_benchmark() -> TextTournamentBenchmarkResult:
    dataset = _read_text_benchmark_dataset()
    rounds: list[TournamentRound] = []
    winners: dict[str, str] = {}

    for category in ("GENERAL", "CODING", "REASONING"):
        prompts = [item["prompt"] for item in dataset if item["category"] == category]
        candidates = _task_category_candidate_models(category)
        if len(candidates) == 0 or len(prompts) == 0:
            continue
        if len(candidates) == 1:
            winners[category] = candidates[0]
            rounds.append(
                TournamentRound(
                    category=category,
                    round_index=1,
                    model_ids=list(candidates),
                    matches=[],
                )
            )
            continue

        current = list(candidates)
        round_index = 1
        prompt = prompts[0]
        while len(current) > 1:
            next_round: list[str] = []
            matches: list[TournamentMatch] = []
            for idx in range(0, len(current), 2):
                model_a = current[idx]
                if idx + 1 >= len(current):
                    next_round.append(model_a)
                    continue
                model_b = current[idx + 1]
                try:
                    answer_a = await llm_router.generate_text(prompt=prompt, model=model_a, temperature=0.2, max_tokens=256)
                except Exception:
                    answer_a = ""
                try:
                    answer_b = await llm_router.generate_text(prompt=prompt, model=model_b, temperature=0.2, max_tokens=256)
                except Exception:
                    answer_b = ""
                winner_model, judge_reason = await _judge_match(model_a, answer_a, model_b, answer_b, category)
                next_round.append(winner_model)
                matches.append(
                    TournamentMatch(
                        category=category,
                        round_index=round_index,
                        prompt=prompt,
                        model_a=model_a,
                        model_b=model_b,
                        winner_model_id=winner_model,
                        judge_reason=judge_reason,
                    )
                )

            rounds.append(
                TournamentRound(
                    category=category,
                    round_index=round_index,
                    model_ids=list(current),
                    matches=matches,
                )
            )
            current = next_round
            round_index += 1

        winners[category] = current[0]

    result = TextTournamentBenchmarkResult(rounds=rounds, winners=winners)
    await _append_benchmark_history(
        benchmark_type="text_tournament",
        summary={
            "categories": sorted(result.winners.keys()),
            "winners": result.winners,
            "rounds_count": len(result.rounds),
        },
    )
    return result


def _history_setting_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"value": json.dumps(items, ensure_ascii=False)}


async def _append_benchmark_history(benchmark_type: str, summary: dict[str, Any]) -> None:
    key = "auto_benchmark_history_json"
    existing = await feature_settings_repository.get(key)
    items: list[dict[str, Any]] = []
    if existing and isinstance(existing.value, dict):
        raw = existing.value.get("value")
        try:
            parsed = json.loads(str(raw or "[]"))
            if isinstance(parsed, list):
                items = parsed
        except Exception:
            items = []

    entry = {
        "run_id": str(uuid4()),
        "benchmark_type": benchmark_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }
    items.insert(0, entry)
    items = items[:100]
    await feature_settings_repository.upsert(key=key, value=_history_setting_payload(items))


async def get_benchmark_history() -> BenchmarkHistoryResult:
    key = "auto_benchmark_history_json"
    existing = await feature_settings_repository.get(key)
    if existing is None or not isinstance(existing.value, dict):
        return BenchmarkHistoryResult(items=[])
    raw = existing.value.get("value")
    try:
        parsed = json.loads(str(raw or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    items: list[BenchmarkHistoryEntry] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        items.append(
            BenchmarkHistoryEntry(
                run_id=str(entry.get("run_id", "")),
                benchmark_type=str(entry.get("benchmark_type", "")),
                created_at=str(entry.get("created_at", "")),
                summary=entry.get("summary", {}) if isinstance(entry.get("summary", {}), dict) else {},
            )
        )
    return BenchmarkHistoryResult(items=items)


def _seed_default_value_for_key(key: str, defaults: dict[str, Any]) -> Any | None:
    classifier = defaults.get("classifier_model")
    stt_model = defaults.get("stt_model")
    mapping = defaults.get("task_model_mapping")
    overrides = defaults.get("model_type_overrides")
    if key == "auto_classifier_model" and isinstance(classifier, str) and classifier.strip():
        return classifier.strip()
    if key == "multimodal_stt_model" and isinstance(stt_model, str) and stt_model.strip():
        return stt_model.strip()
    if key == "auto_task_model_general" and isinstance(mapping, dict):
        value = mapping.get("GENERAL")
        return str(value).strip() if value else None
    if key == "auto_task_model_coding" and isinstance(mapping, dict):
        value = mapping.get("CODING")
        return str(value).strip() if value else None
    if key == "auto_task_model_reasoning" and isinstance(mapping, dict):
        value = mapping.get("REASONING")
        return str(value).strip() if value else None
    if key == "auto_task_model_vision" and isinstance(mapping, dict):
        value = mapping.get("VISION")
        return str(value).strip() if value else None
    if key == "auto_task_model_image_generation" and isinstance(mapping, dict):
        value = mapping.get("IMAGE_GENERATION")
        return str(value).strip() if value else None
    if key == "auto_model_type_overrides_json" and isinstance(overrides, dict):
        return json.dumps(overrides, ensure_ascii=False)
    return None


async def _apply_bootstrap_defaults() -> None:
    defaults = _read_auto_model_defaults()
    if not defaults:
        return

    seed_keys = [
        "auto_classifier_model",
        "multimodal_stt_model",
        "auto_task_model_general",
        "auto_task_model_coding",
        "auto_task_model_reasoning",
        "auto_task_model_vision",
        "auto_task_model_image_generation",
        "auto_model_type_overrides_json",
    ]
    for key in seed_keys:
        existing = await feature_settings_repository.get(key)
        if existing is not None:
            continue
        seeded_value = _seed_default_value_for_key(key, defaults)
        if seeded_value is None:
            continue
        normalized = _normalize_setting(key, seeded_value)
        await feature_settings_repository.upsert(key=key, value={"value": normalized})
        _apply_setting(key, normalized)


def _avatar_ext_from_upload(file: UploadFile) -> str:
    filename = str(file.filename or "").strip().lower()
    ext = Path(filename).suffix.lower()
    if ext in _ALLOWED_AVATAR_EXTENSIONS:
        return ext
    content_type = str(file.content_type or "").lower()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/svg+xml":
        return ".svg"
    return ""


async def upload_default_model_avatar(file: UploadFile) -> dict[str, str]:
    ext = _avatar_ext_from_upload(file)
    if not ext:
        raise ValueError("Unsupported avatar format. Allowed: jpg, jpeg, png, svg.")
    data = await file.read()
    if not data:
        raise ValueError("Uploaded avatar is empty.")
    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for existing_ext in _ALLOWED_AVATAR_EXTENSIONS:
        path = _AVATAR_DIR / f"{_DEFAULT_AVATAR_BASENAME}{existing_ext}"
        if path.exists():
            path.unlink()
    output_path = _AVATAR_DIR / f"{_DEFAULT_AVATAR_BASENAME}{ext}"
    output_path.write_bytes(data)

    normalized = _normalize_setting("default_model_avatar_url", _DEFAULT_AVATAR_ROUTE)
    await feature_settings_repository.upsert(key="default_model_avatar_url", value={"value": normalized})
    _apply_setting("default_model_avatar_url", normalized)

    return {"default_model_avatar_url": normalized}
