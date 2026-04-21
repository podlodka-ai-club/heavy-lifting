from __future__ import annotations

from backend.adapters.mock_scm import MockScm
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task, TokenUsage
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.task_constants import TaskStatus, TaskType
from backend.workers.execute_worker import ExecuteWorker


class DuplicateBranchGuardMockScm(MockScm):
    def __init__(self) -> None:
        super().__init__()
        self.create_branch_calls: list[tuple[str, str]] = []

    def create_branch(self, payload):
        branch_key = (payload.workspace_key, payload.branch_name)
        self.create_branch_calls.append(branch_key)
        if branch_key in self._branches:
            raise AssertionError(f"branch recreated unexpectedly: {branch_key}")
        return super().create_branch(payload)


def test_execute_worker_processes_execute_task_and_creates_deliver(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-27",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-27",
                context={"title": "Implement Worker 2"},
                input_payload={
                    "instructions": "Implement the execute worker orchestration.",
                    "base_branch": "main",
                    "branch_name": "task27/worker-2",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.processed_pr_feedback_tasks == 0
    assert report.failed_execute_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task27/worker-2"
        assert execute_task.pr_external_id == "1"
        assert execute_task.pr_url == "https://example.test/repo/pull/1"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["commit_sha"] == "mock-commit-0001"
        assert execute_task.result_payload["metadata"]["pr_action"] == "created"

        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.task_type == TaskType.DELIVER
        assert deliver_task.parent_id == execute_task.id
        assert deliver_task.status == TaskStatus.NEW
        assert deliver_task.pr_external_id == execute_task.pr_external_id

        token_usage_entries = session.query(TokenUsage).all()
        assert len(token_usage_entries) == 1
        assert token_usage_entries[0].task_id == execute_task.id


def test_execute_worker_reuses_existing_pr_for_feedback_without_new_deliver(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = DuplicateBranchGuardMockScm()
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-27",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-27",
                context={"title": "Implement Worker 2"},
                input_payload={
                    "instructions": "Implement the execute worker orchestration.",
                    "base_branch": "main",
                    "branch_name": "task27/worker-2",
                },
            )
        )

    first_report = worker.poll_once()

    assert first_report.processed_execute_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_task_id="comment-1",
                external_parent_id=execute_task.pr_external_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                branch_name=execute_task.branch_name,
                pr_external_id=execute_task.pr_external_id,
                pr_url=execute_task.pr_url,
                input_payload={
                    "instructions": "Address the first PR review comment.",
                    "pr_feedback": {
                        "pr_external_id": execute_task.pr_external_id,
                        "comment_id": "comment-1",
                        "body": "Please add worker tests.",
                        "pr_url": execute_task.pr_url,
                    },
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 0
    assert report.processed_pr_feedback_tasks == 1
    assert report.failed_pr_feedback_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        feedback_task = session.get(Task, 4)
        assert execute_task is not None
        assert feedback_task is not None
        assert feedback_task.status == TaskStatus.DONE
        assert feedback_task.branch_name == execute_task.branch_name
        assert feedback_task.pr_external_id == execute_task.pr_external_id
        assert feedback_task.pr_url == execute_task.pr_url
        assert feedback_task.result_payload is not None
        assert feedback_task.result_payload["metadata"]["pr_action"] == "reused"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["metadata"]["last_updated_flow"] == "pr_feedback"
        assert execute_task.result_payload["metadata"]["last_feedback_comment_id"] == "comment-1"

        deliver_tasks = session.query(Task).filter(Task.task_type == TaskType.DELIVER).all()
        assert len(deliver_tasks) == 1

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 2
        assert token_usage_entries[-1].task_id == feedback_task.id

    assert scm.create_branch_calls == [("repo-27", "task27/worker-2")]


def test_execute_worker_marks_task_failed_when_workspace_context_is_missing(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-27",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-27",
                context={"title": "Broken execute task"},
            )
        )

    report = worker.poll_once()

    assert report.failed_execute_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "Worker 2 requires repo_url for SCM workspace sync"


def _build_session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)
