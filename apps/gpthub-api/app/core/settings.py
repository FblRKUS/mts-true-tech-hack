from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    backend_cors_origins: str = "http://localhost:3000"

    mws_gpt_base_url: str = "https://api.gpt.mws.ru/v1"
    mws_gpt_api_key: str = ""
    internal_api_key: str = ""
    mws_stub_mode: bool = True
    mws_default_model: str = "mws-gpt-alpha"
    e2b_api_key: str = ""

    postgres_db: str = "gpthub"
    postgres_user: str = "gpthub"
    postgres_password: str = "gpthub"
    postgres_host: str = "db"
    postgres_port: int = 5432
    database_url: Optional[str] = None

    qdrant_url: str = "http://qdrant:6333"
    mem0_collection_name: str = "memories"
    memory_vector_backend: str = "qdrant"
    memory_vector_collection: str = "chat_memories"
    memory_embedding_model: str = "bge-m3"
    memory_embedding_dimensions: int = 128
    memory_recall_top_k: int = 5
    memory_lexical_candidates: int = 300
    memory_thread_boost: float = 0.3
    memory_chat_history_token_budget: int = 2200
    memory_retrieval_token_budget: int = 700
    memory_summary_token_budget: int = 500
    memory_max_recent_messages: int = 24
    memory_summary_interval: int = 8
    memory_summary_window_messages: int = 20
    memory_summary_min_messages: int = 8

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    langgraph_recursion_limit: int = 50
    max_qa_iterations: int = 3

    auto_enable_manual_override: bool = True
    auto_show_routing_reason: bool = True
    auto_enable_domain_hint: bool = True
    auto_enforce_model_profile: bool = True
    auto_auto_downgrade_on_latency: bool = False
    auto_show_latency_badge: bool = True
    auto_allow_provider_mixing: bool = True
    auto_low_confidence_threshold: float = 0.74
    auto_classifier_temperature: float = 0.0
    auto_classifier_max_tokens: int = 16
    auto_classifier_timeout_seconds: int = 12
    auto_classifier_confidence_threshold: float = 0.65
    auto_classifier_system_prompt_template: str = "You are a routing classifier. Output only one label."
    auto_classifier_user_prompt_template: str = (
        "Classify this user request into exactly one label from: "
        "CODING, IMAGE_GENERATION, VISION, REASONING, GENERAL.\n"
        "User request:\n{{user_message}}\n"
        "Return only the label."
    )
    auto_classifier_model: str = "mws-gpt-alpha"
    auto_task_model_general: str = "mws-gpt-alpha"
    auto_task_model_coding: str = "qwen3-coder-480b-a35b"
    auto_task_model_reasoning: str = "glm-4.6-357b"
    auto_task_model_vision: str = "qwen2.5-vl-72b"
    auto_task_model_image_generation: str = "qwen-image-lightning"
    auto_model_type_overrides_json: str = "{}"
    auto_task_override_prompt_template: str = (
        "Continue the same task in a better way. "
        "Use the previous assistant text as context, apologize briefly for the wrong start, and continue.\n\n"
        "Previous assistant text:\n{{last_message}}\n\n"
        "User request:\n{{user_message}}\n\n"
        "Previous task type: {{previous_task_type}}\n"
        "New task type: {{new_task_type}}"
    )
    default_model_avatar_url: str = "/v1/assets/model-avatars/default"
    multimodal_stt_model: str = "whisper-medium"

    autopilot_enable_stream_steps: bool = True
    autopilot_enable_auto_retry: bool = True
    autopilot_enable_risk_guard: bool = True
    autopilot_enable_partial_result_publish: bool = True
    autopilot_enable_cost_guard: bool = False
    autopilot_enable_plan_preview: bool = True
    autopilot_enable_human_handoff: bool = True

    model_court_enabled: bool = True
    model_court_candidates_count: int = 3
    model_court_candidate_timeout_seconds: int = 45
    model_court_judge_model: str = "glm-4.6-357b"
    model_court_enable_anonymous_judging: bool = True

    deep_research_enabled: bool = True
    deep_research_max_queries: int = 3
    deep_research_max_sources: int = 6
    deep_research_fetch_timeout_seconds: int = 12
    deep_research_source_char_limit: int = 2500
    deep_research_max_output_tokens: int = 1200
    deep_research_link_capture_mode: str = "attach_only"

    media_gallery_enabled: bool = True
    media_gallery_page_size: int = 24
    media_gallery_max_filters: int = 10
    media_gallery_retention_days: int = 365

    workspace_enable_shared_workspaces: bool = False
    workspace_enable_file_tree_sync: bool = True
    workspace_enable_workspace_scoping: bool = True
    workspace_enable_diff_preview: bool = True
    workspace_enable_conflict_guards: bool = True
    workspace_enable_session_locks: bool = True
    workspace_enable_workspace_templates: bool = True
    workspace_max_files_per_workspace: int = 1200

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @staticmethod
    def _normalize_sync_postgres_url(url: str) -> str:
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

    @property
    def async_database_url(self) -> str:
        sync_url = self._normalize_sync_postgres_url(self.resolved_database_url)
        return sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    @property
    def sync_database_url(self) -> str:
        return self._normalize_sync_postgres_url(self.resolved_database_url)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def openai_base_url(self) -> str:
        return self.mws_gpt_base_url

    @property
    def openai_api_key(self) -> str:
        return self.mws_gpt_api_key

    @property
    def api_key(self) -> str:
        return self.internal_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
