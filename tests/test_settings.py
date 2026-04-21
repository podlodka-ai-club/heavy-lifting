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
        "TRACKER_POLL_INTERVAL",
        "PR_POLL_INTERVAL",
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
    assert settings.tracker_poll_interval == 30
    assert settings.pr_poll_interval == 60


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
    monkeypatch.setenv("TRACKER_POLL_INTERVAL", "15")
    monkeypatch.setenv("PR_POLL_INTERVAL", "45")

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
    assert settings.tracker_poll_interval == 15
    assert settings.pr_poll_interval == 45


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
