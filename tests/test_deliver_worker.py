from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskContext, TrackerTaskCreatePayload
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.workers.deliver_worker import DeliverWorker, build_deliver_worker


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_deliver_worker_posts_comment_updates_status_and_attaches_pr_link(session_factory) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        _tracker_task_payload(title="Tracker task", repo_url="https://example.test/repo.git")
    )
    worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-28",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-28",
                branch_name="task28/delivery-flow",
                pr_external_id="pr-28",
                pr_url="https://example.test/repo/pull/28",
                context={"title": "Implement Worker 3"},
                result_payload={
                    "summary": "Worker 3 delivery flow implemented.",
                    "details": "Added delivery worker orchestration and tracker sync.",
                    "branch_name": "task28/delivery-flow",
                    "commit_sha": "mock-commit-0028",
                    "pr_url": "https://example.test/repo/pull/28",
                    "tracker_comment": "Готово: результат доставлен обратно в tracker.",
                    "links": [
                        {
                            "label": "branch",
                            "url": "https://example.test/repo/tree/task28/delivery-flow",
                        }
                    ],
                    "metadata": {"flow_type": "execute"},
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                branch_name=execute_task.branch_name,
                pr_external_id=execute_task.pr_external_id,
                pr_url=execute_task.pr_url,
                context={"title": "Deliver Worker 3 result"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert report.failed_deliver_tasks == 0
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body == (
        "Готово: результат доставлен обратно в tracker."
    )
    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    assert [
        reference.url for reference in tracker._tasks[tracker_task.external_id].context.references
    ] == [
        "https://example.test/repo/tree/task28/delivery-flow",
        "https://example.test/repo/pull/28",
    ]

    with session_scope(session_factory=session_factory) as session:
        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.status == TaskStatus.DONE
        assert deliver_task.error is None
        assert deliver_task.result_payload is not None
        assert (
            deliver_task.result_payload["metadata"]["tracker_external_id"]
            == tracker_task.external_id
        )
        assert deliver_task.result_payload["metadata"]["links_attached"] == 2


def test_deliver_worker_marks_task_failed_when_execute_result_is_missing(session_factory) -> None:
    worker = DeliverWorker(tracker=MockTracker(), session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-28",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-28",
                context={"title": "Execute task without result"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id="TASK-28",
                context={"title": "Deliver missing result"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 0
    assert report.failed_deliver_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.status == TaskStatus.FAILED
        assert deliver_task.error == "deliver task requires a completed execute result"


def test_build_deliver_worker_uses_runtime_settings(session_factory) -> None:
    runtime = _runtime_with_tracker_poll_interval(poll_interval=17)

    worker = build_deliver_worker(runtime=runtime, session_factory=session_factory)

    assert worker.tracker is runtime.tracker
    assert worker.poll_interval == 17
    assert worker.session_factory is session_factory


def _tracker_task_payload(*, title: str, repo_url: str):
    return TrackerTaskCreatePayload(
        context=TaskContext(title=title),
        repo_url=repo_url,
        repo_ref="main",
        workspace_key="repo-28",
    )


def _runtime_with_tracker_poll_interval(*, poll_interval: int):
    return RuntimeContainer(
        settings=replace(get_settings(), tracker_poll_interval=poll_interval),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
