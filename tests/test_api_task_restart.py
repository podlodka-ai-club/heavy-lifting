from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_post_task_restart_requeues_failed_worker_owned_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        task = TaskRepository(session).create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                status=TaskStatus.FAILED,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-1",
                branch_name="task26/retry-me",
                pr_external_id="pr-26",
                pr_url="https://example.test/pr/26",
                context={"title": "Retry review feedback"},
                input_payload={"action": "respond_pr"},
                result_payload={"summary": "CLI agent run failed"},
                error="CLI agent run failed",
                attempt=3,
            )
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post(f"/tasks/{task.id}/restart")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["task"]["id"] == task.id
    assert payload["task"]["task_type"] == "pr_feedback"
    assert payload["task"]["status"] == "new"
    assert payload["task"]["repo_url"] == "https://example.test/repo.git"
    assert payload["task"]["repo_ref"] == "main"
    assert payload["task"]["workspace_key"] == "repo-1"
    assert payload["task"]["branch_name"] == "task26/retry-me"
    assert payload["task"]["pr_external_id"] == "pr-26"
    assert payload["task"]["pr_url"] == "https://example.test/pr/26"
    assert payload["task"]["context"] == {"title": "Retry review feedback"}
    assert payload["task"]["input_payload"] == {"action": "respond_pr"}
    assert payload["task"]["result_payload"] is None
    assert payload["task"]["error"] is None
    assert payload["task"]["attempt"] == 3

    with session_scope(session_factory=session_factory) as session:
        restarted_task = session.get(Task, task.id)
        assert restarted_task is not None
        assert restarted_task.status == TaskStatus.NEW
        assert restarted_task.error is None
        assert restarted_task.result_payload is None
        assert restarted_task.repo_url == "https://example.test/repo.git"
        assert restarted_task.workspace_key == "repo-1"
        assert restarted_task.branch_name == "task26/retry-me"
        assert restarted_task.pr_external_id == "pr-26"
        assert restarted_task.pr_url == "https://example.test/pr/26"
        assert restarted_task.attempt == 3


def test_post_task_restart_returns_409_for_unsupported_task_type(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        task = TaskRepository(session).create_task(
            TaskCreateParams(task_type=TaskType.FETCH, status=TaskStatus.FAILED)
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post(f"/tasks/{task.id}/restart")

    assert response.status_code == 409
    assert response.get_json() == {
        "error": (
            "Only failed worker-owned tasks can be restarted; "
            f"task {task.id} has unsupported type fetch"
        )
    }


def test_post_task_restart_returns_409_for_non_failed_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        task = TaskRepository(session).create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, status=TaskStatus.DONE)
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post(f"/tasks/{task.id}/restart")

    assert response.status_code == 409
    assert response.get_json() == {
        "error": (f"Only failed worker-owned tasks can be restarted; task {task.id} is done")
    }


def test_post_task_restart_returns_404_for_missing_task(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().post("/tasks/999/restart")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Task 999 not found"}


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
