"""Application settings, fully driven by environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LISA Backend"
    debug: bool = False

    database_url: str = "postgresql+psycopg://lisa:lisa@localhost:5432/lisa"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Shared secret the agent presents as `Authorization: Bearer <token>`.
    # If unset (None), agent endpoints are open — dev only. Set in prod.
    agent_token: str | None = None

    # Backend URL the agent should call back on (put in the config it fetches).
    public_base_url: str = "http://localhost:8000"

    # Told to the agent so it knows how often to check in.
    heartbeat_interval_seconds: int = 86400


@lru_cache
def get_settings() -> Settings:
    return Settings()
