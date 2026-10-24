from functools import lru_cache

from pydantic import field_validator
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

    # Operator (panel) auth. When operator_password is unset the operator
    # endpoints are open — dev mode, matching agent_token above. jwt_secret
    # signs the login tokens; when unset it is derived from operator_password
    # so a single env var (OPERATOR_PASSWORD) is enough to lock the panel.
    operator_password: str | None = None
    jwt_secret: str | None = None
    jwt_ttl_minutes: int = 720

    ml_models_dir: str = "models"
    default_activity: str = "firefox"

    # OS targets the deployment can actually build. Add "macos" and/or
    # "windows" once a build worker for that OS is running (see
    # docs/deployment.md); builds for an OS not listed here are refused up front
    # so an agent never hangs in `building` with no worker to pick it up. Nuitka
    # can't cross-compile, so each OS needs its own worker (#195, #221).
    buildable_os: list[str] = ["linux"]

    llm_provider: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    llm_api_key: str | None = None
    llm_timeout: float = 60.0

    heartbeat_interval_seconds: int = 86400

    @field_validator("operator_password", "jwt_secret", "agent_token", "llm_api_key", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat an empty/whitespace env var as unset (None).

        docker-compose always injects these as `${VAR:-}`, i.e. an empty string
        when not provided, and `.env.example` ships them blank to mean "open /
        dev mode". The auth layer keys dev mode on `is None`, so without this a
        blank OPERATOR_PASSWORD/AGENT_TOKEN would be read as a real empty secret
        that nothing can match — locking the panel instead of opening it.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
