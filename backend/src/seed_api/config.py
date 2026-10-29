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
    # Limits for every agent run (each task attempt).
    run_max_steps: int = 8
    run_max_runtime_seconds: float = 300
    run_max_total_tokens: int = 200_000
    # SEED Flow (durable tasks). Unset database => the tasks API answers 503.
    database_url: SecretStr | None = None
    task_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_lease_seconds: float = Field(default=30.0, ge=3, le=600)
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # Tasks one worker process runs at once (D-026): a task waiting for its agents
    # must not hold up the agents' own tasks.
    worker_concurrency: int = Field(default=4, ge=1, le=16)
    # Delegation limits (D-026): agent tasks one task may have working at once, may
    # start in all, and how deep agents may hand work on (1 = agents do not delegate).
    delegation_max_parallel: int = Field(default=3, ge=1, le=8)
    delegation_max_per_task: int = Field(default=10, ge=1, le=50)
    delegation_max_depth: int = Field(default=1, ge=1, le=3)
    # Tools that wait for a person's approval before each call (D-009). JSON list.
    approval_required_tools: list[str] = ["run_command"]
    # Chat: how many earlier completed turns a new message carries as context.
    chat_context_turns: int = Field(default=20, ge=1, le=200)
    # Sandbox (ADR-0010). Worker side: unset URL => tasks get file tools only, no
    # command execution. Sandbox side: the rest bounds every command.
    sandbox_url: str | None = None
    sandbox_root: str = "/workspaces"
    # Each task's files and commands run as a user of their own. Needs root in the
    # sandbox container; off only for tests on a non-root machine.
    sandbox_isolate_users: bool = True
    sandbox_command_timeout_seconds: float = Field(default=60, gt=0, le=600)
    sandbox_memory_mb: int = Field(default=512, ge=32)
    sandbox_cpu_seconds: int = Field(default=60, ge=1)
    sandbox_max_processes: int = Field(default=64, ge=1)
    sandbox_max_file_mb: int = Field(default=64, ge=1)
    # Without a sandbox: per-workspace dirs on the container tmpfs. Files outlive
    # them as artifacts when artifact_root is set.
    workspace_root: str = "/tmp/seed-workspaces"  # noqa: S108
    # Artifacts (ADR-0014): where saved file content lives, on a persistent volume.
    # Unset => task files are not saved.
    artifact_root: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
