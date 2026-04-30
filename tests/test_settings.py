from sqlalchemy.orm import Session

from backend.db import build_engine
from backend.models import ApplicationSetting, Base
from backend.settings import get_settings


def test_get_settings_uses_defaults(monkeypatch) -> None:
    for name in (
        "APP_NAME",
        "APP_HOST",
        "APP_PORT",
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "WORKSPACE_ROOT",
        "TRACKER_ADAPTER",
        "SCM_ADAPTER",
        "AGENT_RUNNER_ADAPTER",
        "CLI_AGENT_COMMAND",
        "CLI_AGENT_SUBCOMMAND",
        "CLI_AGENT_TIMEOUT_SECONDS",
        "CLI_AGENT_PROVIDER",
        "CLI_AGENT_MODEL",
        "CLI_AGENT_PROFILE",
        "CLI_AGENT_API_KEY_ENV_VAR",
        "CLI_AGENT_BASE_URL_ENV_VAR",
        "CLI_AGENT_PREVIEW_CHARS",
        "LOCAL_AGENT_PROVIDER",
        "LOCAL_AGENT_MODEL",
        "LOCAL_AGENT_NAME",
        "TRACKER_POLL_INTERVAL",
        "PR_POLL_INTERVAL",
        "TRACKER_FETCH_LIMIT",
        "PR_FEEDBACK_FETCH_LIMIT",
        "LINEAR_API_URL",
        "LINEAR_TOKEN_ENV_VAR",
        "LINEAR_TEAM_ID",
        "LINEAR_REQUEST_TIMEOUT_SECONDS",
        "LINEAR_FETCH_LABEL_ID",
        "LINEAR_STATE_ID_NEW",
        "LINEAR_STATE_ID_PROCESSING",
        "LINEAR_STATE_ID_DONE",
        "LINEAR_STATE_ID_FAILED",
        "LINEAR_FETCH_STATE_TYPES",
        "LINEAR_TASK_TYPE_LABEL_MAPPING",
        "LINEAR_MAX_PAGES",
        "LINEAR_DESCRIPTION_WARN_THRESHOLD",
        "GITHUB_API_BASE_URL",
        "GITHUB_TOKEN_ENV_VAR",
        "GITHUB_USER_NAME",
        "GITHUB_USER_EMAIL",
        "GITHUB_DEFAULT_REMOTE",
        "GITHUB_DEFAULT_REPO_URL",
        "SCM_DEFAULT_BASE_BRANCH",
        "SCM_BRANCH_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.app_name == "heavy-lifting-backend"
    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 8000
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "heavy_lifting"
    assert settings.postgres_user == "postgres"
    assert settings.postgres_password == "postgres"
    assert settings.database_url == (
        "postgresql+psycopg://postgres:postgres@localhost:5432/heavy_lifting"
    )
    assert settings.workspace_root == "/workspace/repos"
    assert settings.tracker_adapter == "mock"
    assert settings.scm_adapter == "mock"
    assert settings.agent_runner_adapter == "local"
    assert settings.cli_agent_command == "opencode"
    assert settings.cli_agent_subcommand == "run"
    assert settings.cli_agent_timeout_seconds == 1800
    assert settings.cli_agent_provider_hint is None
    assert settings.cli_agent_model_hint is None
    assert settings.cli_agent_profile is None
    assert settings.cli_agent_api_key_env_var == "OPENAI_API_KEY"
    assert settings.cli_agent_base_url_env_var == "OPENAI_BASE_URL"
    assert settings.cli_agent_preview_chars == 1000
    assert settings.local_agent_provider == "openai"
    assert settings.local_agent_model == "gpt-5.4"
    assert settings.local_agent_name == "local-placeholder-runner"
    assert settings.tracker_poll_interval == 30
    assert settings.pr_poll_interval == 60
    assert settings.tracker_fetch_limit == 100
    assert settings.pr_feedback_fetch_limit == 100
    assert settings.linear_api_url == "https://api.linear.app/graphql"
    assert settings.linear_token_env_var == "LINEAR_API_KEY"
    assert settings.linear_team_id is None
    assert settings.linear_request_timeout_seconds == 30
    assert settings.linear_fetch_label_id is None
    assert settings.linear_state_id_new is None
    assert settings.linear_state_id_processing is None
    assert settings.linear_state_id_done is None
    assert settings.linear_state_id_failed is None
    assert settings.linear_fetch_state_types == ("triage", "backlog", "unstarted")
    assert settings.linear_task_type_label_mapping == {}
    assert settings.linear_max_pages == 4
    assert settings.linear_description_warn_threshold == 50000
    assert settings.github_api_base_url == "https://api.github.com"
    assert settings.github_token_env_var == "GITHUB_TOKEN"
    assert settings.github_user_name is None
    assert settings.github_user_email is None
    assert settings.github_default_remote == "origin"
    assert settings.github_default_repo_url is None
    assert settings.scm_default_base_branch is None
    assert settings.scm_branch_prefix == "execute/"


def test_get_settings_reads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "orchestrator")
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "9001")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "orchestrator")
    monkeypatch.setenv("POSTGRES_USER", "service")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspaces")
    monkeypatch.setenv("TRACKER_ADAPTER", "custom-tracker")
    monkeypatch.setenv("SCM_ADAPTER", "custom-scm")
    monkeypatch.setenv("AGENT_RUNNER_ADAPTER", "cli")
    monkeypatch.setenv("CLI_AGENT_COMMAND", "codex")
    monkeypatch.setenv("CLI_AGENT_SUBCOMMAND", "exec")
    monkeypatch.setenv("CLI_AGENT_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("CLI_AGENT_MODEL", "gpt-5.4")
    monkeypatch.setenv("CLI_AGENT_PROFILE", "backend")
    monkeypatch.setenv("CLI_AGENT_API_KEY_ENV_VAR", "CUSTOM_API_KEY")
    monkeypatch.setenv("CLI_AGENT_BASE_URL_ENV_VAR", "CUSTOM_BASE_URL")
    monkeypatch.setenv("CLI_AGENT_PREVIEW_CHARS", "500")
    monkeypatch.setenv("LOCAL_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "claude-opus-4.6")
    monkeypatch.setenv("LOCAL_AGENT_NAME", "custom-local")
    monkeypatch.setenv("TRACKER_POLL_INTERVAL", "15")
    monkeypatch.setenv("PR_POLL_INTERVAL", "45")
    monkeypatch.setenv("TRACKER_FETCH_LIMIT", "25")
    monkeypatch.setenv("PR_FEEDBACK_FETCH_LIMIT", "9")
    monkeypatch.setenv("LINEAR_API_URL", "https://custom.linear.app")
    monkeypatch.setenv("LINEAR_TOKEN_ENV_VAR", "MY_LINEAR_KEY")
    monkeypatch.setenv("LINEAR_TEAM_ID", "team-123")
    monkeypatch.setenv("LINEAR_REQUEST_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LINEAR_FETCH_LABEL_ID", "label-123")
    monkeypatch.setenv("LINEAR_STATE_ID_NEW", "state-new")
    monkeypatch.setenv("LINEAR_STATE_ID_PROCESSING", "state-proc")
    monkeypatch.setenv("LINEAR_STATE_ID_DONE", "state-done")
    monkeypatch.setenv("LINEAR_STATE_ID_FAILED", "state-fail")
    monkeypatch.setenv("LINEAR_FETCH_STATE_TYPES", " triage, started, , ")
    monkeypatch.setenv(
        "LINEAR_TASK_TYPE_LABEL_MAPPING",
        '{"bug":"label-bug", "feature":"label-feat"}',
    )
    monkeypatch.setenv("LINEAR_MAX_PAGES", "10")
    monkeypatch.setenv("LINEAR_DESCRIPTION_WARN_THRESHOLD", "10000")
    monkeypatch.setenv("GITHUB_API_BASE_URL", "https://ghe.example.test/api/v3")
    monkeypatch.setenv("GITHUB_TOKEN_ENV_VAR", "MY_GH_TOKEN")
    monkeypatch.setenv("GITHUB_USER_NAME", "heavy-lifting-bot")
    monkeypatch.setenv("GITHUB_USER_EMAIL", "bot@example.test")
    monkeypatch.setenv("GITHUB_DEFAULT_REMOTE", "upstream")
    monkeypatch.setenv("GITHUB_DEFAULT_REPO_URL", "https://github.com/acme/widgets")
    monkeypatch.setenv("SCM_DEFAULT_BASE_BRANCH", "develop")
    monkeypatch.setenv("SCM_BRANCH_PREFIX", "hl/")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.app_name == "orchestrator"
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 9001
    assert settings.postgres_host == "db"
    assert settings.postgres_port == 6543
    assert settings.postgres_db == "orchestrator"
    assert settings.postgres_user == "service"
    assert settings.postgres_password == "secret"
    assert settings.database_url == "postgresql+psycopg://service:secret@db:6543/orchestrator"
    assert settings.workspace_root == "/tmp/workspaces"
    assert settings.tracker_adapter == "custom-tracker"
    assert settings.scm_adapter == "custom-scm"
    assert settings.agent_runner_adapter == "cli"
    assert settings.cli_agent_command == "codex"
    assert settings.cli_agent_subcommand == "exec"
    assert settings.cli_agent_timeout_seconds == 1200
    assert settings.cli_agent_provider_hint == "openai"
    assert settings.cli_agent_model_hint == "gpt-5.4"
    assert settings.cli_agent_profile == "backend"
    assert settings.cli_agent_api_key_env_var == "CUSTOM_API_KEY"
    assert settings.cli_agent_base_url_env_var == "CUSTOM_BASE_URL"
    assert settings.cli_agent_preview_chars == 500
    assert settings.local_agent_provider == "anthropic"
    assert settings.local_agent_model == "claude-opus-4.6"
    assert settings.local_agent_name == "custom-local"
    assert settings.tracker_poll_interval == 15
    assert settings.pr_poll_interval == 45
    assert settings.tracker_fetch_limit == 25
    assert settings.pr_feedback_fetch_limit == 9
    assert settings.linear_api_url == "https://custom.linear.app"
    assert settings.linear_token_env_var == "MY_LINEAR_KEY"
    assert settings.linear_team_id == "team-123"
    assert settings.linear_request_timeout_seconds == 60
    assert settings.linear_fetch_label_id == "label-123"
    assert settings.linear_state_id_new == "state-new"
    assert settings.linear_state_id_processing == "state-proc"
    assert settings.linear_state_id_done == "state-done"
    assert settings.linear_state_id_failed == "state-fail"
    assert settings.linear_fetch_state_types == ("triage", "started")
    assert settings.linear_task_type_label_mapping == {"bug": "label-bug", "feature": "label-feat"}
    assert settings.linear_max_pages == 10
    assert settings.linear_description_warn_threshold == 10000
    assert settings.github_api_base_url == "https://ghe.example.test/api/v3"
    assert settings.github_token_env_var == "MY_GH_TOKEN"
    assert settings.github_user_name == "heavy-lifting-bot"
    assert settings.github_user_email == "bot@example.test"
    assert settings.github_default_remote == "upstream"
    assert settings.github_default_repo_url == "https://github.com/acme/widgets"
    assert settings.scm_default_base_branch == "develop"
    assert settings.scm_branch_prefix == "hl/"


def test_get_settings_prefers_explicit_database_url(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://custom")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "ignored")
    monkeypatch.setenv("POSTGRES_USER", "ignored")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ignored")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://custom"


def test_get_settings_normalizes_postgresql_database_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://heavy_lifting:heavy_lifting@postgres:5432/heavy_lifting"
    )

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.database_url == (
        "postgresql+psycopg://heavy_lifting:heavy_lifting@postgres:5432/heavy_lifting"
    )


def test_get_settings_invalid_json_fallback(monkeypatch) -> None:
    monkeypatch.setenv("LINEAR_TASK_TYPE_LABEL_MAPPING", 'not-json')
    
    get_settings.cache_clear()
    settings = get_settings()
    
    assert settings.linear_task_type_label_mapping == {}


def test_get_settings_not_dict_json_fallback(monkeypatch) -> None:
    monkeypatch.setenv("LINEAR_TASK_TYPE_LABEL_MAPPING", '["list", "instead", "of", "dict"]')
    
    get_settings.cache_clear()
    settings = get_settings()
    
    assert settings.linear_task_type_label_mapping == {}


def test_get_settings_applies_database_overrides(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                ApplicationSetting(
                    setting_key="tracker_fetch_limit",
                    env_var="TRACKER_FETCH_LIMIT",
                    value_type="int",
                    value="42",
                    default_value="100",
                    description="Fetch limit",
                    display_order=10,
                ),
                ApplicationSetting(
                    setting_key="local_agent_model",
                    env_var="LOCAL_AGENT_MODEL",
                    value_type="string",
                    value="gpt-db",
                    default_value="gpt-5.4",
                    description="Local model",
                    display_order=40,
                ),
            ]
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TRACKER_FETCH_LIMIT", "25")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "gpt-env")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.tracker_fetch_limit == 42
    assert settings.local_agent_model == "gpt-db"


def test_get_settings_ignores_invalid_database_overrides(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                ApplicationSetting(
                    setting_key="tracker_fetch_limit",
                    env_var="TRACKER_FETCH_LIMIT",
                    value_type="int",
                    value="not-an-int",
                    default_value="100",
                    description="Fetch limit",
                    display_order=10,
                ),
                ApplicationSetting(
                    setting_key="local_agent_name",
                    env_var="LOCAL_AGENT_NAME",
                    value_type="string",
                    value=" ",
                    default_value="local-placeholder-runner",
                    description="Local name",
                    display_order=50,
                ),
            ]
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TRACKER_FETCH_LIMIT", "25")
    monkeypatch.setenv("LOCAL_AGENT_NAME", "env-local")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.tracker_fetch_limit == 25
    assert settings.local_agent_name == "env-local"
