from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LISA Backend"
    debug: bool = False

    database_url: str = "postgresql+psycopg://lisa:lisa@localhost:5432/lisa"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:5173"]

    agent_token: str | None = None

    public_base_url: str = "http://localhost:8000"

    heartbeat_interval_seconds: int = 86400

    llm_provider: str = "ollama"

    llm_base_url: str = "http://localhost:11434"

    llm_model: str = "llama3.2"

    llm_api_key: str | None = None

    llm_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
