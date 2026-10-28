"""Environment-based configuration. Secrets are read from the environment only."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEED_", extra="ignore")

    admin_username: str = "admin"
    # Unset => login is disabled (typed 503), never a default password.
    admin_password: SecretStr | None = None
    # Unset => random per-process secret; sessions do not survive restart.
    session_secret: SecretStr | None = None
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
    # Ephemeral per-run dirs on the container tmpfs until artifact storage (M6).
    workspace_root: str = "/tmp/seed-workspaces"  # noqa: S108


@lru_cache
def get_settings() -> Settings:
    return Settings()
