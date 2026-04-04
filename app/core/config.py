from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # OpenAI API
    openai_api_key: str
    openai_base_url: Optional[str] = None  # Custom OpenAI-compatible provider
    
    # LiteLLM
    litellm_master_key: str
    
    # PostgreSQL
    postgres_user: str = "mts_user"
    postgres_password: str = "mts_password"
    postgres_db: str = "mts_agentic_db"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    
    @property
    def database_url(self) -> str:
        """Construct PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def async_database_url(self) -> str:
        """Construct async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_api_key: Optional[str] = None
    
    @property
    def qdrant_url(self) -> str:
        """Construct Qdrant connection URL."""
        return f"http://{self.qdrant_host}:{self.qdrant_port}"
    
    # Mem0
    mem0_collection_name: str = "mts_memories"
    
    # E2B Sandbox
    e2b_api_key: str
    
    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    
    # LangGraph
    langgraph_recursion_limit: int = 50
    max_qa_iterations: int = 3


# Global settings instance
settings = Settings()
