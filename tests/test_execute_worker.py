from __future__ import annotations

from backend.adapters.mock_scm import MockScm
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task, TokenUsage
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskLink, TaskResultPayload
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


class RecordingAgentRunner(LocalAgentRunner):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return super().run(request)


class FailingAgentRunner:
    def __init__(self, message: str) -> None:
        self.message = message
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        raise RuntimeError(self.message)


class EstimateOnlyAgentRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            payload=TaskResultPayload(
                summary="CLI agent run completed successfully.",
                details=(
                    "stdout:\n2 story points\nReason: logging the CLI command "
                    "is a small isolated change."
                ),
                links=[
                    TaskLink(
                        label="artifact",
                        url="https://example.test/should-not-deliver",
                    )
                ],
                metadata={
                    "runner_adapter": "cli",
                    "stdout_preview": (
                        "2 story points\nReason: logging the CLI command "
                        "is a small isolated change."
                    ),
                },
            )
        )


def test_execute_worker_processes_execute_task_and_creates_deliver(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    agent_runner = RecordingAgentRunner()
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=agent_runner,
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

    assert len(agent_runner.requests) == 1
    request = agent_runner.requests[0]
    assert request.workspace_path == "/tmp/mock-scm/repo-27"
    assert request.metadata == {
        "task_id": 2,
        "task_type": "execute",
        "workspace_key": "repo-27",
        "workspace_path": "/tmp/mock-scm/repo-27",
        "branch_name": "task27/worker-2",
        "repo_url": "https://example.test/repo.git",
        "repo_ref": "main",
    }

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


def test_execute_worker_skips_scm_artifacts_for_estimate_only_requests(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = MockScm()
    agent_runner = EstimateOnlyAgentRunner()
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=agent_runner,
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-62",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-62",
                context={
                    "title": "Estimate CLI logging effort",
                    "description": "Estimate only. Do not modify code.",
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-62",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-62",
                context={
                    "title": "Estimate CLI logging effort",
                    "description": "Need only a story point estimate without code changes.",
                },
                input_payload={
                    "instructions": "Return only estimate. Do not modify code.",
                    "base_branch": "main",
                    "branch_name": "task62/estimate-only",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0
    assert len(agent_runner.requests) == 1
    assert agent_runner.requests[0].metadata["branch_name"] is None
    assert scm._branches == {}
    assert scm._pull_requests == {}
    assert scm._commit_sequence == 0

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.DONE
        assert execute_task.branch_name is None
        assert execute_task.pr_external_id is None
        assert execute_task.pr_url is None
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["commit_sha"] is None
        assert execute_task.result_payload["pr_url"] is None
        assert execute_task.result_payload["tracker_comment"] == (
            "2 story points\nReason: logging the CLI command is a small isolated change."
        )
        assert execute_task.result_payload["links"] == []
        assert execute_task.result_payload["metadata"]["delivery_mode"] == "estimate_only"
        assert execute_task.result_payload["metadata"]["pr_action"] == "skipped"

        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.task_type == TaskType.DELIVER
        assert deliver_task.parent_id == execute_task.id
        assert deliver_task.status == TaskStatus.NEW
        assert deliver_task.branch_name is None
        assert deliver_task.pr_external_id is None
        assert deliver_task.pr_url is None


def test_execute_worker_marks_task_failed_when_workspace_context_is_missing(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    agent_runner = RecordingAgentRunner()
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=agent_runner,
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
    assert agent_runner.requests == []

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "Worker 2 requires repo_url for SCM workspace sync"


def test_execute_worker_marks_task_failed_when_runner_execution_step_fails(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    agent_runner = FailingAgentRunner("runner crashed")
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=agent_runner,
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-47",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-47",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-47",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-47",
                context={"title": "Runner failure"},
                input_payload={
                    "instructions": "Break during the explicit execute stage.",
                    "base_branch": "main",
                    "branch_name": "task47/runner-failure",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 0
    assert report.failed_execute_tasks == 1
    assert len(agent_runner.requests) == 1
    assert agent_runner.requests[0].metadata["branch_name"] == "task47/runner-failure"

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "runner crashed"

        token_usage_entries = session.query(TokenUsage).all()
        assert token_usage_entries == []


def test_execute_worker_emits_structured_lifecycle_logs(tmp_path, caplog) -> None:
    session_factory = _build_session_factory(tmp_path)
    agent_runner = RecordingAgentRunner()
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=agent_runner,
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-61",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-61",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-61",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-61",
                context={"title": "Structured logging"},
                input_payload={
                    "instructions": "Emit lifecycle logs.",
                    "base_branch": "main",
                    "branch_name": "task61/structured-logging",
                },
            )
        )

    caplog.set_level("INFO")

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    worker_events = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("component") == "worker2"
    ]
    assert [entry["event"] for entry in worker_events] == [
        "worker_task_picked_up",
        "workspace_prepared",
        "agent_run_started",
        "agent_run_finished",
        "execute_task_completed",
        "deliver_task_created",
    ]
    assert all(entry["task_id"] == 2 for entry in worker_events)
    assert all(entry["root_task_id"] == 1 for entry in worker_events)
    assert all(entry["workspace_key"] == "repo-61" for entry in worker_events[1:])
    assert worker_events[1]["branch_name"] == "task61/structured-logging"
    assert worker_events[4]["pr_action"] == "created"
    assert worker_events[5]["deliver_task_id"] == 3


def _build_session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)
