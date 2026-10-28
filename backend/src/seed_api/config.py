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


@lru_cache
def get_settings() -> Settings:
    return Settings()
