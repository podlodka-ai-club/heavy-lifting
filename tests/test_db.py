import pytest
from sqlalchemy import text

from backend.db import build_engine, build_session_factory, session_scope


def test_build_engine_requires_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        build_engine("")


def test_build_engine_rejects_invalid_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL is invalid"):
        build_engine("not a database url")


def test_session_scope_commits_changes(tmp_path) -> None:
    database_path = tmp_path / "app.db"
    engine = build_engine(f"sqlite+pysqlite:///{database_path}")
    session_factory = build_session_factory(engine)

    with engine.begin() as connection:
        connection.execute(text("create table items (id integer primary key, name text)"))

    with session_scope(session_factory=session_factory) as session:
        session.execute(text("insert into items (name) values ('created')"))

    with session_scope(session_factory=session_factory) as session:
        rows = session.execute(text("select name from items")).scalars().all()

    assert rows == ["created"]


def test_session_scope_rolls_back_on_error(tmp_path) -> None:
    database_path = tmp_path / "app.db"
    engine = build_engine(f"sqlite+pysqlite:///{database_path}")
    session_factory = build_session_factory(engine)

    with engine.begin() as connection:
        connection.execute(text("create table items (id integer primary key, name text)"))

    with pytest.raises(RuntimeError, match="boom"):
        with session_scope(session_factory=session_factory) as session:
            session.execute(text("insert into items (name) values ('created')"))
            raise RuntimeError("boom")

    with session_scope(session_factory=session_factory) as session:
        rows = session.execute(text("select name from items")).scalars().all()

    assert rows == []
