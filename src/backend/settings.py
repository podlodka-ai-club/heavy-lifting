import os
from dataclasses import dataclass
from functools import lru_cache


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return database_url


def _build_database_url(
    postgres_host: str,
    postgres_port: int,
    postgres_db: str,
    postgres_user: str,
    postgres_password: str,
) -> str:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://"
        f"{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}",
    )

    return _normalize_database_url(database_url)


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_host: str
    app_port: int
    database_url: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    workspace_root: str
    tracker_adapter: str
    scm_adapter: str
    agent_runner_adapter: str
    cli_agent_command: str
    cli_agent_subcommand: str
    cli_agent_timeout_seconds: int
    cli_agent_provider_hint: str | None
    cli_agent_model_hint: str | None
    cli_agent_profile: str | None
    cli_agent_api_key_env_var: str | None
    cli_agent_base_url_env_var: str | None
    tracker_poll_interval: int
    pr_poll_interval: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = _get_int("POSTGRES_PORT", 5432)
    postgres_db = os.getenv("POSTGRES_DB", "heavy_lifting")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    return Settings(
        app_name=os.getenv("APP_NAME", "heavy-lifting-backend"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_get_int("APP_PORT", 8000),
        database_url=_build_database_url(
            postgres_host=postgres_host,
            postgres_port=postgres_port,
            postgres_db=postgres_db,
            postgres_user=postgres_user,
            postgres_password=postgres_password,
        ),
        postgres_host=postgres_host,
        postgres_port=postgres_port,
        postgres_db=postgres_db,
        postgres_user=postgres_user,
        postgres_password=postgres_password,
        workspace_root=os.getenv("WORKSPACE_ROOT", "/workspace/repos"),
        tracker_adapter=os.getenv("TRACKER_ADAPTER", "mock"),
        scm_adapter=os.getenv("SCM_ADAPTER", "mock"),
        agent_runner_adapter=os.getenv("AGENT_RUNNER_ADAPTER", "local"),
        cli_agent_command=os.getenv("CLI_AGENT_COMMAND", "opencode"),
        cli_agent_subcommand=os.getenv("CLI_AGENT_SUBCOMMAND", "run"),
        cli_agent_timeout_seconds=_get_int("CLI_AGENT_TIMEOUT_SECONDS", 1800),
        cli_agent_provider_hint=os.getenv("CLI_AGENT_PROVIDER") or None,
        cli_agent_model_hint=os.getenv("CLI_AGENT_MODEL") or None,
        cli_agent_profile=os.getenv("CLI_AGENT_PROFILE") or None,
        cli_agent_api_key_env_var=os.getenv("CLI_AGENT_API_KEY_ENV_VAR", "OPENAI_API_KEY") or None,
        cli_agent_base_url_env_var=os.getenv("CLI_AGENT_BASE_URL_ENV_VAR", "OPENAI_BASE_URL")
        or None,
        tracker_poll_interval=_get_int("TRACKER_POLL_INTERVAL", 30),
        pr_poll_interval=_get_int("PR_POLL_INTERVAL", 60),
    )


__all__ = ["Settings", "get_settings"]
