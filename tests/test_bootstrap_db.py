from sqlalchemy import inspect

from backend.bootstrap_db import MVP_SCHEMA_TABLES, bootstrap_schema, main
from backend.db import build_engine


def test_bootstrap_schema_creates_mvp_tables(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    created_tables = bootstrap_schema(database_url)
    table_names = set(inspect(build_engine(database_url)).get_table_names())

    assert created_tables == MVP_SCHEMA_TABLES
    assert table_names == set(MVP_SCHEMA_TABLES)


def test_bootstrap_schema_is_idempotent(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    bootstrap_schema(database_url)
    created_tables = bootstrap_schema(database_url)

    assert created_tables == ()


def test_main_accepts_database_url_override(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"

    exit_code = main(["--database-url", database_url])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert "MVP schema is ready; created tables: tasks, token_usage" in stdout
