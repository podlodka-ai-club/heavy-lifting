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
