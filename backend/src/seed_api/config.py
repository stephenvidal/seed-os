"""Environment-based configuration. Secrets are read from the environment only."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEED_", extra="ignore")

    admin_username: str = "admin"
    # Read once, on first start, to create the first admin when no users exist.
    # Never a default password: unset and no users => sign-in answers 503.
    admin_password: SecretStr | None = None
    session_ttl_seconds: int = 60 * 60 * 12
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_window_seconds: int = 60
    cors_origins: list[str] = []

    # Model providers. Unset key => the provider is not configured.
    ollama_api_key: SecretStr | None = None
    ollama_base_url: str = "https://ollama.com"
    provider_timeout_seconds: float = 120.0
    default_model: str | None = None
    # Agent runs (in-request until SEED Flow lands in M3).
    max_concurrent_runs: int = 2
    run_max_steps: int = 8
    run_max_runtime_seconds: float = 300
    run_max_total_tokens: int = 200_000
    # SEED Flow (durable tasks). Unset database => the tasks API answers 503.
    database_url: SecretStr | None = None
    task_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_lease_seconds: float = Field(default=30.0, ge=3, le=600)
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # Ephemeral per-run dirs on the container tmpfs until artifact storage (M6).
    workspace_root: str = "/tmp/seed-workspaces"  # noqa: S108


@lru_cache
def get_settings() -> Settings:
    return Settings()
