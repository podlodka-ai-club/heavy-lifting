"""Repository tests for ``find_implementation_execute_for_root`` (task11 §3).

The sibling-impl-execute model (task07 + task16) places the implementation
execute as a sibling of the triage-execute under the same fetch-task.
``find_implementation_execute_for_root`` is used by ``TriageStep`` and the
re-triage flow to detect whether the cluster already has an impl-execute and
to avoid creating duplicates.
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
    status: TaskStatus = TaskStatus.NEW,
    action: str = "implementation",
):
    return repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=parent_id,
            status=status,
            input_payload={"action": action},
        )
    )


def test_find_implementation_returns_none_when_only_triage_exists(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="triage",
        )

        assert repository.find_implementation_execute_for_root(fetch.id) is None


def test_find_implementation_returns_sibling_when_present(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="triage",
        )
        impl = _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.NEW,
            action="implementation",
        )

        result = repository.find_implementation_execute_for_root(fetch.id)
        assert result is not None
        assert result.id == impl.id


def test_find_implementation_ignores_non_implementation_executes(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="triage",
        )
        # Second triage execute (re-triage scenario) — also not implementation.
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.NEW,
            action="triage",
        )

        assert repository.find_implementation_execute_for_root(fetch.id) is None


def test_find_implementation_returns_earliest_when_multiple(session_factory) -> None:
    """Defensive: artificial two-impl scenario returns the earliest one."""

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _make_fetch(repository)
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="triage",
        )
        first_impl = _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
            action="implementation",
        )
        _make_execute(
            repository,
            parent_id=fetch.id,
            status=TaskStatus.NEW,
            action="implementation",
        )

        result = repository.find_implementation_execute_for_root(fetch.id)
        assert result is not None
        assert result.id == first_impl.id
