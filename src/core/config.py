from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application settings
    app_name: str = Field(default="Kira API", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    app_description: str = Field(
        default="Household-aware parent guidance API for Kira",
        description="Application description",
    )
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment")
    
    # Server settings
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")
    reload: bool = Field(default=True, description="Auto-reload on code changes")
    
    # Database settings
    database_url: str = Field(
        default="postgresql+asyncpg://kira:kira@localhost:5432/kira",
        description="Database connection URL"
    )
    database_echo: bool = Field(default=False, description="Echo SQL queries")
    
    # Redis settings (for Dramatiq)
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    voice_session_redis_prefix: str = Field(
        default="kira:voice",
        description="Redis key prefix for live voice session state",
    )
    voice_session_ttl_seconds: int = Field(
        default=3600,
        description="TTL for live voice session state in Redis",
    )
    
    # CORS settings
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="CORS allowed origins"
    )
    cors_methods: list[str] = Field(
        default=["*"], description="CORS allowed methods"
    )
    cors_headers: list[str] = Field(
        default=["*"], description="CORS allowed headers"
    )
    
    # Rate limiting (example config - implement middleware as needed)
    rate_limit_requests: int = Field(default=100, description="Requests per minute")
    rate_limit_window: int = Field(default=60, description="Rate limit window in seconds")
    
    # API settings
    api_prefix: str = Field(default="/api/v1", description="API URL prefix")

    # Profile fixture settings
    profile_fixture_path: Path = Field(
        default=Path("src/modules/profiles/fixtures/parent_profiles.json"),
        description="Path to the parent profile fixture JSON file",
    )

    # LLM settings
    llm_provider: str = Field(default="openai", description="LLM provider identifier")
    llm_model: str = Field(default="gpt-5-mini", description="LLM model name")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the LLM API",
    )
    llm_timeout_seconds: float = Field(default=30.0, description="LLM request timeout in seconds")
    llm_reasoning_effort: str = Field(default="low", description="LLM reasoning effort")
    max_context_messages: int = Field(default=12, description="Maximum messages to send as context")
    conversation_summary_initial_threshold_turns: int = Field(
        default=10,
        description="Completed parent turns required before the first conversation summary is generated",
    )
    conversation_summary_refresh_interval_turns: int = Field(
        default=3,
        description="Completed parent turns between conversation summary refreshes after the first summary exists",
    )
    llm_input_cost_per_million_tokens_usd: float | None = Field(
        default=None,
        description="Optional override for billable input token cost per 1M tokens in USD",
    )
    llm_cached_input_cost_per_million_tokens_usd: float | None = Field(
        default=None,
        description="Optional override for cached input token cost per 1M tokens in USD",
    )
    llm_output_cost_per_million_tokens_usd: float | None = Field(
        default=None,
        description="Optional override for output token cost per 1M tokens in USD",
    )
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    langsmith_tracing: bool = Field(default=False, description="Enable LangSmith tracing")
    langsmith_project: Optional[str] = Field(default=None, description="LangSmith project name")
    langsmith_api_key: Optional[str] = Field(default=None, description="LangSmith API key")

    # Retell integration
    retell_api_key: Optional[str] = Field(default=None, description="Retell API key used for webhook verification")
    retell_inbound_voice_agent_id: Optional[str] = Field(
        default=None,
        description="Retell agent id used to accept inbound voice calls",
    )
    retell_default_begin_message: str = Field(
        default="Hello, this is Kira. How can I help today?",
        description="Default voice greeting spoken when a live call starts",
    )
    retell_verify_signatures: bool = Field(
        default=True,
        description="Whether Retell webhook signatures should be verified",
    )
    retell_webhook_max_age_ms: int = Field(
        default=300000,
        description="Maximum allowed Retell webhook signature age in milliseconds",
    )
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
        description="Log format"
    )

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_value(cls, value: bool | str) -> bool | str:
        if isinstance(value, bool):
            return value

        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return value

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
