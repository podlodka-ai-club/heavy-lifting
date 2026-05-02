from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskContext, TrackerTaskCreatePayload
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_post_manual_tracker_comment_resolves_tracker_thread_and_returns_comment_reference(
    session_factory,
) -> None:
    runtime = _runtime()
    tracker_task = runtime.tracker.create_task(_tracker_payload(title="Runtime verification task"))

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                context={"title": "Runtime verification task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                pr_external_id="pr-77",
                context={"title": "Implement runtime verification"},
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                status=TaskStatus.NEW,
                tracker_name="mock",
                external_task_id="comment-77",
                external_parent_id="pr-77",
                pr_external_id="pr-77",
                input_payload={
                    "pr_feedback": {
                        "pr_external_id": "pr-77",
                        "comment_id": "comment-77",
                        "body": "Please adjust the edge case.",
                    }
                },
            )
        )

    app = create_app(runtime=runtime, session_factory=session_factory)

    response = app.test_client().post(
        f"/tasks/{feedback_task.id}/tracker-comments",
        json={"body": "Manual operator note"},
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "task_id": feedback_task.id,
        "tracker_task_id": tracker_task.external_id,
        "tracker_comment_id": "comment-1",
    }
    assert len(runtime.tracker._comments[tracker_task.external_id]) == 1
    assert runtime.tracker._comments[tracker_task.external_id][0].body == "Manual operator note"
    assert runtime.tracker._comments[tracker_task.external_id][0].metadata == {
        "task_id": feedback_task.id,
        "root_task_id": fetch_task.id,
        "source": "api_manual_comment",
    }


def test_post_manual_tracker_comment_returns_404_for_missing_task(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post("/tasks/999/tracker-comments", json={"body": "Hello"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "Task 999 not found"}


def test_post_manual_tracker_comment_returns_404_when_tracker_thread_cannot_be_resolved(
    session_factory,
) -> None:
    with session_scope(session_factory=session_factory) as session:
        task = TaskRepository(session).create_task(TaskCreateParams(task_type=TaskType.EXECUTE))

    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post(f"/tasks/{task.id}/tracker-comments", json={"body": "Hello"})

    assert response.status_code == 404
    assert response.get_json() == {
        "error": f"Task {task.id} has no resolvable tracker external task id"
    }


def test_post_manual_tracker_comment_returns_400_for_invalid_payload(session_factory) -> None:
    runtime = _runtime()
    tracker_task = runtime.tracker.create_task(_tracker_payload(title="Runtime verification task"))

    with session_scope(session_factory=session_factory) as session:
        task = TaskRepository(session).create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                context={"title": "Runtime verification task"},
            )
        )

    app = create_app(runtime=runtime, session_factory=session_factory)

    response = app.test_client().post(
        f"/tasks/{task.id}/tracker-comments",
        json={"text": "Wrong field"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["error"] == "Invalid manual tracker comment payload"
    assert payload["details"]
    assert runtime.tracker._comments.get(tracker_task.external_id) is None


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )


def _tracker_payload(*, title: str) -> TrackerTaskCreatePayload:
    return TrackerTaskCreatePayload(context=TaskContext(title=title))
