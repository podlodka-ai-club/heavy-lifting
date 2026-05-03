"""Repository tests for the new triage-execute lookups (task18a §4).

These methods are needed by the re-triage flow to detect whether a previous
triage execute is still pending, currently running, or already done — without
relying on JSON-path SQL (the implementation filters by
``input_payload['action']`` in Python).
"""

from __future__ import annotations

import pytest

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _make_fetch(repository: TaskRepository):
    return repository.create_task(
        TaskCreateParams(
            task_type=TaskType.FETCH,
            status=TaskStatus.DONE,
            tracker_name="mock",
            external_task_id="T-1",
        )
    )


def _make_execute(
    repository: TaskRepository,
    *,
    parent_id: int,
    status: TaskStatus,
    action: str,
):
    return repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=parent_id,
            status=status,
            input_payload={"action": action},
        )
    )


def test_find_pending_triage_execute_returns_new_triage(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        triage = _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.NEW,
            action="triage",
        )

        result = repository.find_pending_triage_execute(parent_id=fetch.id)

        assert result is not None
        assert result.id == triage.id


def test_find_pending_triage_execute_ignores_done_or_processing(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(repository, parent_id=fetch.id, status=TaskStatus.DONE, action="triage")
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.PROCESSING,
            action="triage",
        )

        assert repository.find_pending_triage_execute(parent_id=fetch.id) is None


def test_find_pending_triage_execute_ignores_implementation(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.NEW,
            action="implementation",
        )

        assert repository.find_pending_triage_execute(parent_id=fetch.id) is None


def test_find_processing_triage_execute_returns_processing_triage(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        triage = _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.PROCESSING,
            action="triage",
        )

        result = repository.find_processing_triage_execute(parent_id=fetch.id)

        assert result is not None
        assert result.id == triage.id


def test_find_processing_triage_execute_ignores_other_statuses(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(repository, parent_id=fetch.id, status=TaskStatus.NEW, action="triage")
        _make_execute(repository, parent_id=fetch.id, status=TaskStatus.DONE, action="triage")
        _make_execute(repository, parent_id=fetch.id, status=TaskStatus.FAILED, action="triage")

        assert repository.find_processing_triage_execute(parent_id=fetch.id) is None


def test_find_last_completed_triage_returns_latest(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        first = _make_execute(
            repository, parent_id=fetch.id, status=TaskStatus.DONE, action="triage"
        )
        second = _make_execute(
            repository, parent_id=fetch.id, status=TaskStatus.DONE, action="triage"
        )

        result = repository.find_last_completed_triage_execute(parent_id=fetch.id)

        assert result is not None
        # Ordered by ``created_at DESC, id DESC`` — second created wins.
        assert result.id == second.id
        assert result.id != first.id


def test_find_last_completed_triage_returns_none_when_only_pending(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(repository, parent_id=fetch.id, status=TaskStatus.NEW, action="triage")
        _make_execute(
            repository, parent_id=fetch.id, status=TaskStatus.PROCESSING, action="triage"
        )

        assert repository.find_last_completed_triage_execute(parent_id=fetch.id) is None


def test_find_last_completed_triage_ignores_implementation(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="implementation",
        )

        assert repository.find_last_completed_triage_execute(parent_id=fetch.id) is None
