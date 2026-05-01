import json
import os
from dataclasses import dataclass, replace
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from backend.application_settings import APPLICATION_SETTING_SPECS_BY_KEY


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _get_tuple(name: str, default: str) -> tuple[str, ...]:
    val = os.getenv(name, default)
    if not val.strip():
        return ()
    return tuple(x.strip() for x in val.split(",") if x.strip())


def _get_dict(name: str, default: str) -> dict[str, str]:
    val = os.getenv(name, default)
    if not val.strip():
        return {}
    try:
        parsed = json.loads(val)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
        return {}
    except json.JSONDecodeError:
        return {}


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
    api_basic_auth_username: str | None
    api_basic_auth_password: str | None
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
    cli_agent_preview_chars: int
    local_agent_provider: str
    local_agent_model: str
    local_agent_name: str
    tracker_poll_interval: int
    pr_poll_interval: int
    tracker_fetch_limit: int
    pr_feedback_fetch_limit: int
    linear_api_url: str
    linear_token_env_var: str
    linear_team_id: str | None
    linear_request_timeout_seconds: int
    linear_fetch_label_id: str | None
    linear_state_id_new: str | None
    linear_state_id_processing: str | None
    linear_state_id_done: str | None
    linear_state_id_failed: str | None
    linear_fetch_state_types: tuple[str, ...]
    linear_task_type_label_mapping: dict[str, str]
    linear_max_pages: int
    linear_description_warn_threshold: int
    github_api_base_url: str
    github_token_env_var: str
    github_user_name: str | None
    github_user_email: str | None
    github_default_remote: str
    github_default_repo_url: str | None
    scm_default_base_branch: str | None
    scm_branch_prefix: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = _get_int("POSTGRES_PORT", 5432)
    postgres_db = os.getenv("POSTGRES_DB", "heavy_lifting")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    env_settings = Settings(
        app_name=os.getenv("APP_NAME", "heavy-lifting-backend"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_get_int("APP_PORT", 8000),
        api_basic_auth_username=os.getenv("API_BASIC_AUTH_USERNAME") or None,
        api_basic_auth_password=os.getenv("API_BASIC_AUTH_PASSWORD") or None,
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
        cli_agent_preview_chars=_get_int("CLI_AGENT_PREVIEW_CHARS", 1000),
        local_agent_provider=os.getenv("LOCAL_AGENT_PROVIDER", "openai"),
        local_agent_model=os.getenv("LOCAL_AGENT_MODEL", "gpt-5.4"),
        local_agent_name=os.getenv("LOCAL_AGENT_NAME", "local-placeholder-runner"),
        tracker_poll_interval=_get_int("TRACKER_POLL_INTERVAL", 30),
        pr_poll_interval=_get_int("PR_POLL_INTERVAL", 60),
        tracker_fetch_limit=_get_int("TRACKER_FETCH_LIMIT", 100),
        pr_feedback_fetch_limit=_get_int("PR_FEEDBACK_FETCH_LIMIT", 100),
        linear_api_url=os.getenv("LINEAR_API_URL", "https://api.linear.app/graphql"),
        linear_token_env_var=os.getenv("LINEAR_TOKEN_ENV_VAR", "LINEAR_API_KEY"),
        linear_team_id=os.getenv("LINEAR_TEAM_ID") or None,
        linear_request_timeout_seconds=_get_int("LINEAR_REQUEST_TIMEOUT_SECONDS", 30),
        linear_fetch_label_id=os.getenv("LINEAR_FETCH_LABEL_ID") or None,
        linear_state_id_new=os.getenv("LINEAR_STATE_ID_NEW") or None,
        linear_state_id_processing=os.getenv("LINEAR_STATE_ID_PROCESSING") or None,
        linear_state_id_done=os.getenv("LINEAR_STATE_ID_DONE") or None,
        linear_state_id_failed=os.getenv("LINEAR_STATE_ID_FAILED") or None,
        linear_fetch_state_types=_get_tuple("LINEAR_FETCH_STATE_TYPES", "triage,backlog,unstarted"),
        linear_task_type_label_mapping=_get_dict("LINEAR_TASK_TYPE_LABEL_MAPPING", "{}"),
        linear_max_pages=_get_int("LINEAR_MAX_PAGES", 4),
        linear_description_warn_threshold=_get_int("LINEAR_DESCRIPTION_WARN_THRESHOLD", 50000),
        github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com"),
        github_token_env_var=os.getenv("GITHUB_TOKEN_ENV_VAR", "GITHUB_TOKEN"),
        github_user_name=os.getenv("GITHUB_USER_NAME") or None,
        github_user_email=os.getenv("GITHUB_USER_EMAIL") or None,
        github_default_remote=os.getenv("GITHUB_DEFAULT_REMOTE", "origin"),
        github_default_repo_url=os.getenv("GITHUB_DEFAULT_REPO_URL") or None,
        scm_default_base_branch=os.getenv("SCM_DEFAULT_BASE_BRANCH") or None,
        scm_branch_prefix=os.getenv("SCM_BRANCH_PREFIX", "execute/"),
    )

    return _apply_database_overrides(env_settings)


def _apply_database_overrides(settings: Settings) -> Settings:
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT setting_key, value, value_type "
                    "FROM application_settings"
                )
            )
            overrides: dict[str, int | str] = {}
            for key, raw_value, value_type in rows:
                if key not in APPLICATION_SETTING_SPECS_BY_KEY:
                    continue
                coerced_value = _coerce_database_value(raw_value, value_type)
                if coerced_value is not None:
                    overrides[key] = coerced_value
    except SQLAlchemyError:
        return settings
    finally:
        try:
            engine.dispose()
        except UnboundLocalError:
            pass

    if not overrides:
        return settings
    return replace(
        settings,
        tracker_fetch_limit=_int_override(
            overrides, "tracker_fetch_limit", settings.tracker_fetch_limit
        ),
        pr_feedback_fetch_limit=_int_override(
            overrides, "pr_feedback_fetch_limit", settings.pr_feedback_fetch_limit
        ),
        local_agent_provider=_str_override(
            overrides, "local_agent_provider", settings.local_agent_provider
        ),
        local_agent_model=_str_override(
            overrides, "local_agent_model", settings.local_agent_model
        ),
        local_agent_name=_str_override(
            overrides, "local_agent_name", settings.local_agent_name
        ),
        cli_agent_preview_chars=_int_override(
            overrides, "cli_agent_preview_chars", settings.cli_agent_preview_chars
        ),
    )


def _int_override(overrides: dict[str, int | str], key: str, default: int) -> int:
    value = overrides.get(key)
    return value if isinstance(value, int) else default


def _str_override(overrides: dict[str, int | str], key: str, default: str) -> str:
    value = overrides.get(key)
    return value if isinstance(value, str) else default


def _coerce_database_value(raw_value: str, value_type: str) -> int | str | None:
    if value_type == "int":
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    if value_type == "string":
        text_value = str(raw_value).strip()
        return text_value or None

    return None


__all__ = ["Settings", "get_settings"]
