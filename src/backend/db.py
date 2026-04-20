from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from backend.settings import get_settings


def _validate_database_url(database_url: str) -> str:
    if not database_url:
        raise ValueError("DATABASE_URL is required")

    try:
        make_url(database_url)
    except ArgumentError as exc:
        raise ValueError("DATABASE_URL is invalid") from exc

    return database_url


def build_engine(database_url: str | None = None) -> Engine:
    if database_url is None:
        database_url = get_settings().database_url

    return create_engine(_validate_database_url(database_url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine()


def build_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine or get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return build_session_factory()


def create_session(session_factory: sessionmaker[Session] | None = None) -> Session:
    return (session_factory or get_session_factory())()


def get_db_session() -> Iterator[Session]:
    session = create_session()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    session = create_session(session_factory=session_factory)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_database_state() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()


__all__ = [
    "build_engine",
    "build_session_factory",
    "create_session",
    "get_db_session",
    "get_engine",
    "get_session_factory",
    "reset_database_state",
    "session_scope",
]
