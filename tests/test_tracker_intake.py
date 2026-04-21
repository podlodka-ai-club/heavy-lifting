from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_tracker import MockTracker
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskContext, TaskInputPayload, TrackerTaskCreatePayload
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.workers.tracker_intake import TrackerIntakeWorker, build_tracker_intake_worker


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_tracker_intake_creates_fetch_and_execute_tasks(session_factory) -> None:
    tracker = MockTracker()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Implement tracker intake",
                description="Create local fetch and execute tasks.",
                acceptance_criteria=["Local execute task is queued"],
            ),
            input_payload=TaskInputPayload(
                instructions="Implement Worker 1 flow.",
                base_branch="main",
                branch_name="task25/tracker-intake",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-25",
        )
    )
    worker = TrackerIntakeWorker(
        tracker=tracker,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    report = worker.poll_once()

    assert report.fetched_count == 1
    assert report.created_fetch_tasks == 1
    assert report.created_execute_tasks == 1
    assert report.skipped_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=created_task.external_id,
        )

        assert fetch_task is not None
        assert fetch_task.status is TaskStatus.DONE
        assert fetch_task.task_type is TaskType.FETCH
        assert fetch_task.external_task_id == created_task.external_id
        assert fetch_task.context == {
            "title": "Implement tracker intake",
            "description": "Create local fetch and execute tasks.",
            "acceptance_criteria": ["Local execute task is queued"],
            "references": [],
            "metadata": {},
        }

        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )

        assert execute_task is not None
        assert execute_task.status is TaskStatus.NEW
        assert execute_task.parent_id == fetch_task.id
        assert execute_task.root_id == fetch_task.root_id
        assert execute_task.external_parent_id == created_task.external_id
        assert execute_task.repo_url == "https://example.test/repo.git"
        assert execute_task.repo_ref == "main"
        assert execute_task.workspace_key == "repo-25"
        assert execute_task.context == fetch_task.context
        assert execute_task.input_payload == {
            "instructions": "Implement Worker 1 flow.",
            "base_branch": "main",
            "branch_name": "task25/tracker-intake",
            "commit_message_hint": None,
            "pr_feedback": None,
            "metadata": {},
        }


def test_tracker_intake_is_idempotent_for_repeated_polls(session_factory) -> None:
    tracker = MockTracker()
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Repeatable intake task"),
            input_payload=TaskInputPayload(instructions="Run once"),
        )
    )
    worker = TrackerIntakeWorker(
        tracker=tracker,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    first_report = worker.poll_once()
    second_report = worker.poll_once()

    assert first_report.created_fetch_tasks == 1
    assert first_report.created_execute_tasks == 1
    assert second_report.fetched_count == 1
    assert second_report.created_fetch_tasks == 0
    assert second_report.created_execute_tasks == 0
    assert second_report.skipped_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        tasks = session.query(Task).count()

    assert tasks == 2


def test_tracker_intake_restores_missing_execute_child(session_factory) -> None:
    tracker = MockTracker()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Repair missing execute child"),
            input_payload=TaskInputPayload(instructions="Restore child"),
            repo_url="https://example.test/repo.git",
        )
    )
    with session_scope(session_factory=session_factory) as session:
        TaskRepository(session).create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_task_id=created_task.external_id,
                context={"title": "Repair missing execute child"},
            )
        )

    worker = TrackerIntakeWorker(
        tracker=tracker,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    report = worker.poll_once()

    assert report.created_fetch_tasks == 0
    assert report.created_execute_tasks == 1
    assert report.skipped_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=created_task.external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        assert execute_task.external_parent_id == created_task.external_id
        assert execute_task.input_payload == {
            "instructions": "Restore child",
            "base_branch": None,
            "branch_name": None,
            "commit_message_hint": None,
            "pr_feedback": None,
            "metadata": {},
        }


def test_build_tracker_intake_worker_uses_runtime_settings(session_factory) -> None:
    runtime = RuntimeContainer(
        settings=replace(get_settings(), tracker_poll_interval=12, tracker_adapter="mock"),
        tracker=MockTracker(),
        scm=object(),
        agent_runner=object(),
    )

    worker = build_tracker_intake_worker(runtime=runtime, session_factory=session_factory)

    assert worker.tracker is runtime.tracker
    assert worker.tracker_name == "mock"
    assert worker.poll_interval == 12
    assert worker.session_factory is session_factory
