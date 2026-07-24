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


settings = Settings()
