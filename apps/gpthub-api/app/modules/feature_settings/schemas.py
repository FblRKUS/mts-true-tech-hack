from __future__ import annotations

from pydantic import BaseModel


class FeatureSettingsPayload(BaseModel):
    mws_stub_mode: bool
    mws_default_model: str
    langgraph_recursion_limit: int
    max_qa_iterations: int

    memory_recall_top_k: int
    memory_lexical_candidates: int
    memory_thread_boost: float
    memory_chat_history_token_budget: int
    memory_retrieval_token_budget: int
    memory_summary_token_budget: int
    memory_max_recent_messages: int
    memory_summary_interval: int
    memory_summary_window_messages: int
    memory_summary_min_messages: int

    auto_enable_manual_override: bool
    auto_show_routing_reason: bool
    auto_enable_domain_hint: bool
    auto_enforce_model_profile: bool
    auto_auto_downgrade_on_latency: bool
    auto_show_latency_badge: bool
    auto_allow_provider_mixing: bool
    auto_low_confidence_threshold: float
    auto_classifier_temperature: float
    auto_classifier_max_tokens: int
    auto_classifier_timeout_seconds: int
    auto_classifier_confidence_threshold: float
    auto_classifier_system_prompt_template: str
    auto_classifier_user_prompt_template: str
    auto_classifier_model: str
    auto_task_model_general: str
    auto_task_model_coding: str
    auto_task_model_reasoning: str
    auto_task_model_vision: str
    auto_task_model_image_generation: str
    auto_model_type_overrides_json: str
    auto_task_override_prompt_template: str
    default_model_avatar_url: str
    multimodal_stt_model: str

    autopilot_enable_stream_steps: bool
    autopilot_enable_auto_retry: bool
    autopilot_enable_risk_guard: bool
    autopilot_enable_partial_result_publish: bool
    autopilot_enable_cost_guard: bool
    autopilot_enable_plan_preview: bool
    autopilot_enable_human_handoff: bool

    model_court_enabled: bool
    model_court_candidates_count: int
    model_court_candidate_timeout_seconds: int
    model_court_judge_model: str
    model_court_enable_anonymous_judging: bool

    deep_research_enabled: bool
    deep_research_max_queries: int
    deep_research_max_sources: int
    deep_research_fetch_timeout_seconds: int
    deep_research_source_char_limit: int
    deep_research_max_output_tokens: int
    deep_research_link_capture_mode: str

    media_gallery_enabled: bool
    media_gallery_page_size: int
    media_gallery_max_filters: int
    media_gallery_retention_days: int

    workspace_enable_shared_workspaces: bool
    workspace_enable_file_tree_sync: bool
    workspace_enable_workspace_scoping: bool
    workspace_enable_diff_preview: bool
    workspace_enable_conflict_guards: bool
    workspace_enable_session_locks: bool
    workspace_enable_workspace_templates: bool
    workspace_max_files_per_workspace: int


class FeatureSettingsPatchPayload(BaseModel):
    mws_stub_mode: bool | None = None
    mws_default_model: str | None = None
    langgraph_recursion_limit: int | None = None
    max_qa_iterations: int | None = None

    memory_recall_top_k: int | None = None
    memory_lexical_candidates: int | None = None
    memory_thread_boost: float | None = None
    memory_chat_history_token_budget: int | None = None
    memory_retrieval_token_budget: int | None = None
    memory_summary_token_budget: int | None = None
    memory_max_recent_messages: int | None = None
    memory_summary_interval: int | None = None
    memory_summary_window_messages: int | None = None
    memory_summary_min_messages: int | None = None

    auto_enable_manual_override: bool | None = None
    auto_show_routing_reason: bool | None = None
    auto_enable_domain_hint: bool | None = None
    auto_enforce_model_profile: bool | None = None
    auto_auto_downgrade_on_latency: bool | None = None
    auto_show_latency_badge: bool | None = None
    auto_allow_provider_mixing: bool | None = None
    auto_low_confidence_threshold: float | None = None
    auto_classifier_temperature: float | None = None
    auto_classifier_max_tokens: int | None = None
    auto_classifier_timeout_seconds: int | None = None
    auto_classifier_confidence_threshold: float | None = None
    auto_classifier_system_prompt_template: str | None = None
    auto_classifier_user_prompt_template: str | None = None
    auto_classifier_model: str | None = None
    auto_task_model_general: str | None = None
    auto_task_model_coding: str | None = None
    auto_task_model_reasoning: str | None = None
    auto_task_model_vision: str | None = None
    auto_task_model_image_generation: str | None = None
    auto_model_type_overrides_json: str | None = None
    auto_task_override_prompt_template: str | None = None
    default_model_avatar_url: str | None = None
    multimodal_stt_model: str | None = None

    autopilot_enable_stream_steps: bool | None = None
    autopilot_enable_auto_retry: bool | None = None
    autopilot_enable_risk_guard: bool | None = None
    autopilot_enable_partial_result_publish: bool | None = None
    autopilot_enable_cost_guard: bool | None = None
    autopilot_enable_plan_preview: bool | None = None
    autopilot_enable_human_handoff: bool | None = None

    model_court_enabled: bool | None = None
    model_court_candidates_count: int | None = None
    model_court_candidate_timeout_seconds: int | None = None
    model_court_judge_model: str | None = None
    model_court_enable_anonymous_judging: bool | None = None

    deep_research_enabled: bool | None = None
    deep_research_max_queries: int | None = None
    deep_research_max_sources: int | None = None
    deep_research_fetch_timeout_seconds: int | None = None
    deep_research_source_char_limit: int | None = None
    deep_research_max_output_tokens: int | None = None
    deep_research_link_capture_mode: str | None = None

    media_gallery_enabled: bool | None = None
    media_gallery_page_size: int | None = None
    media_gallery_max_filters: int | None = None
    media_gallery_retention_days: int | None = None

    workspace_enable_shared_workspaces: bool | None = None
    workspace_enable_file_tree_sync: bool | None = None
    workspace_enable_workspace_scoping: bool | None = None
    workspace_enable_diff_preview: bool | None = None
    workspace_enable_conflict_guards: bool | None = None
    workspace_enable_session_locks: bool | None = None
    workspace_enable_workspace_templates: bool | None = None
    workspace_max_files_per_workspace: int | None = None


class ClassifierBenchmarkEntry(BaseModel):
    model_id: str
    accuracy: float
    macro_f1: float
    correct: int
    total: int


class ClassifierBenchmarkResult(BaseModel):
    entries: list[ClassifierBenchmarkEntry]
    winner_model_id: str | None = None


class ApplyClassifierWinnerPayload(BaseModel):
    model_id: str


class TextBenchmarkEntry(BaseModel):
    category: str
    model_id: str
    score: float
    answered: int
    total: int


class TextBenchmarkResult(BaseModel):
    entries: list[TextBenchmarkEntry]


class TournamentMatch(BaseModel):
    category: str
    round_index: int
    prompt: str
    model_a: str
    model_b: str
    winner_model_id: str
    judge_reason: str


class TournamentRound(BaseModel):
    category: str
    round_index: int
    model_ids: list[str]
    matches: list[TournamentMatch]


class TextTournamentBenchmarkResult(BaseModel):
    rounds: list[TournamentRound]
    winners: dict[str, str]


class BenchmarkHistoryEntry(BaseModel):
    run_id: str
    benchmark_type: str
    created_at: str
    summary: dict


class BenchmarkHistoryResult(BaseModel):
    items: list[BenchmarkHistoryEntry]
