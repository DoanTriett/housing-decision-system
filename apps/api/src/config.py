from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    environment: str = Field(default="development")
    database_url: str = Field(default="postgresql://postgres:postgres@localhost:5432/housing")
    redis_url: str = Field(default="redis://localhost:6379/0")
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")
    log_level: str = Field(default="INFO")
    voyage_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    planner_model: str = Field(default="gpt-4.1-mini")
    specialist_model: str = Field(default="gpt-4.1-mini")
    llm_timeout_seconds: int = Field(default=30)
    llm_max_retries: int = Field(default=2)
    qdrant_collection: str = Field(default="neighborhoods")
    neighborhood_top_k: int = Field(default=3)
    google_maps_api_key: str = Field(default="")
    nominatim_user_agent: str = Field(default="housing-decision-system")
    commute_cache_ttl_seconds: int = Field(default=86400)
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")
    sse_channel_prefix: str = Field(default="run_progress")
    # Clerk JWT - set CLERK_JWKS_URL=local for HS256 local-dev tokens (see .env.example).
    clerk_jwks_url: str = Field(default="local")
    clerk_issuer: str = Field(default="http://localhost/clerk")
    # Used only when clerk_jwks_url == "local" (never for production Clerk RS256).
    dev_jwt_secret: str = Field(default="local-dev-only-not-for-production")
    rate_limit_per_user_per_hour: int = Field(default=20)
    # LangSmith / LangChain tracing (optional; enabled only when explicitly true).
    langchain_tracing_v2: bool = Field(default=False)
    langchain_api_key: str = Field(default="")
    langchain_project: str = Field(default="housing-decision-system")
    langsmith_api_key: str = Field(default="")  # alias accepted by some dashboards
    langsmith_tracing: bool = Field(default=False)
    langsmith_project: str = Field(default="")
    langsmith_endpoint: str = Field(default="")
    upstash_redis_rest_url: str = Field(default="")
    upstash_redis_rest_token: str = Field(default="")


settings = Settings()


def configure_langsmith_env() -> None:
    """Export LangSmith env vars so LangGraph/LiteLLM emit traces when configured."""
    import os

    api_key = settings.langchain_api_key or settings.langsmith_api_key
    tracing_enabled = settings.langchain_tracing_v2 or settings.langsmith_tracing
    project = settings.langchain_project or settings.langsmith_project
    if not api_key or not tracing_enabled:
        return
    os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", project)
    os.environ.setdefault("LANGSMITH_PROJECT", project)
