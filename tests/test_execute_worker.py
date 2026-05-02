from __future__ import annotations

from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import AgentFeedbackEntry, Base, Task, TokenUsage
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskLink, TaskResultPayload
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
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


class EnsureWorkspaceRecorderMockScm(MockScm):
    def __init__(self) -> None:
        super().__init__()
        self.ensure_workspace_payloads = []

    def ensure_workspace(self, payload):
        self.ensure_workspace_payloads.append(payload.model_copy(deep=True))
        return super().ensure_workspace(payload)


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
    def __init__(
        self,
        *,
        stdout_preview: str | None = None,
        tracker_comment: str | None = None,
        details: str | None = None,
    ) -> None:
        self.requests: list[AgentRunRequest] = []
        self.stdout_preview = stdout_preview
        self.tracker_comment = tracker_comment
        self.details = details

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        stdout_preview = self.stdout_preview
        if stdout_preview is None:
            stdout_preview = (
                "2 story points\nReason: logging the CLI command is a small isolated change."
            )
        details = self.details
        if details is None:
            details = (
                "stdout:\n2 story points\nReason: logging the CLI command "
                "is a small isolated change."
            )
        return AgentRunResult(
            payload=TaskResultPayload(
                summary="CLI agent run completed successfully.",
                details=details,
                tracker_comment=self.tracker_comment,
                links=[
                    TaskLink(
                        label="artifact",
                        url="https://example.test/should-not-deliver",
                    )
                ],
                metadata={
                    "runner_adapter": "cli",
                    "stdout_preview": stdout_preview,
                },
            )
        )


class FailedCliAgentRunner:
    def __init__(self, exit_code: int = 17) -> None:
        self.exit_code = exit_code
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            payload=TaskResultPayload(
                summary=f"CLI agent run failed with exit code {self.exit_code}.",
                details="stderr:\ncommand failed",
                metadata={
                    "runner_adapter": "cli",
                    "exit_code": self.exit_code,
                    "execution_status": "failed",
                    "failure_message": (f"CLI agent run failed with exit code {self.exit_code}."),
                },
            )
        )


class RetroAgentRunner:
    def __init__(self, metadata):
        self.metadata = metadata
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            payload=TaskResultPayload(
                summary="Retro run completed.",
                metadata=self.metadata,
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


def test_execute_worker_persists_valid_agent_retro_feedback(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RetroAgentRunner(
            {
                "agent_retro": [
                    {
                        "tag": "missing-tests",
                        "category": "testing",
                        "severity": "warning",
                        "message": "Regression coverage was missing.",
                        "suggested_action": "Add regression coverage.",
                        "metadata": {"source_step": "execute"},
                    }
                ]
            }
        ),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-RETRO",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-retro",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-RETRO",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-retro",
                context={"title": "Implement retro persistence"},
                input_payload={
                    "instructions": "Run with retro metadata.",
                    "base_branch": "main",
                    "branch_name": "task-retro/run",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0
    with session_scope(session_factory=session_factory) as session:
        entries = session.query(AgentFeedbackEntry).all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.task_id == 2
        assert entry.root_id == 1
        assert entry.task_type == TaskType.EXECUTE
        assert entry.role is None
        assert entry.attempt == 1
        assert entry.source == "agent"
        assert entry.category == "testing"
        assert entry.tag == "missing-tests"
        assert entry.severity == "warning"
        assert entry.message == "Regression coverage was missing."
        assert entry.suggested_action == "Add regression coverage."
        assert entry.entry_metadata == {"source_step": "execute"}


def test_execute_worker_ignores_invalid_agent_retro_feedback(tmp_path, caplog) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RetroAgentRunner(
            {
                "agent_retro": [
                    {
                        "tag": "valid-tag",
                        "message": "This one should be kept.",
                    },
                    {
                        "tag": "Not A Slug",
                        "severity": "warning",
                        "message": "Invalid slug should be rejected.",
                    },
                ]
            }
        ),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-invalid-retro",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-invalid-retro",
                context={"title": "Run"},
                input_payload={"branch_name": "task-retro/invalid"},
            )
        )

    caplog.set_level("WARNING")
    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0
    with session_scope(session_factory=session_factory) as session:
        entries = session.query(AgentFeedbackEntry).all()
        assert len(entries) == 1
        assert entries[0].tag == "valid-tag"

    warning_events = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "agent_retro_item_invalid"
    ]
    assert len(warning_events) == 1
    assert warning_events[0]["task_id"] == 2


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


def test_execute_worker_requests_pr_feedback_workspace_on_existing_branch(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = EnsureWorkspaceRecorderMockScm()
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

    assert report.processed_pr_feedback_tasks == 1
    assert len(scm.ensure_workspace_payloads) == 2
    execute_payload, feedback_payload = scm.ensure_workspace_payloads
    assert execute_payload.branch_name is None
    assert feedback_payload.branch_name == "task27/worker-2"


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


def test_build_delivery_only_comment_keeps_existing_stdout_preview_with_reason(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    comment = worker._build_delivery_only_comment(
        agent_payload=TaskResultPayload(
            summary="Estimate completed.",
            details=(
                "stdout:\n2 story points\nReason: logging the CLI command "
                "is a small isolated change."
            ),
            metadata={
                "stdout_preview": (
                    "2 story points\nReason: logging the CLI command is a small isolated change."
                )
            },
        )
    )

    assert comment == (
        "2 story points\nReason: logging the CLI command is a small isolated change."
    )


def test_build_delivery_only_comment_appends_rationale_when_stdout_preview_has_only_estimate(
    tmp_path,
) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    comment = worker._build_delivery_only_comment(
        agent_payload=TaskResultPayload(
            summary="Estimate completed.",
            details="Reason: logging the CLI command is a small isolated change.",
            metadata={"stdout_preview": "2 story points"},
        )
    )

    assert comment == (
        "2 story points\nReason: logging the CLI command is a small isolated change."
    )


def test_build_delivery_only_comment_uses_combined_tracker_comment_without_duplication(
    tmp_path,
) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    comment = worker._build_delivery_only_comment(
        agent_payload=TaskResultPayload(
            summary="Estimate completed.",
            details="Reason: logging the CLI command is a small isolated change.",
            tracker_comment=(
                "2 story points\nReason: logging the CLI command is a small isolated change."
            ),
            metadata={"stdout_preview": "2 story points"},
        )
    )

    assert comment == (
        "2 story points\nReason: logging the CLI command is a small isolated change."
    )


def test_build_delivery_only_comment_uses_combined_details_without_duplication(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    comment = worker._build_delivery_only_comment(
        agent_payload=TaskResultPayload(
            summary="Estimate completed.",
            details=(
                "stdout:\n2 story points\nReason: logging the CLI command "
                "is a small isolated change."
            ),
            metadata={"stdout_preview": "2 story points"},
        )
    )

    assert comment == (
        "2 story points\nReason: logging the CLI command is a small isolated change."
    )


def test_execute_worker_marks_task_failed_when_workspace_key_is_missing(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    agent_runner = RecordingAgentRunner()
    worker = ExecuteWorker(
        scm=DefaultRepoUrlMockScm("https://example.test/default-repo.git"),
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
                context={"title": "Execute task without workspace key"},
                input_payload={"instructions": "Run with generated workspace key."},
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0
    assert len(agent_runner.requests) == 1
    assert agent_runner.requests[0].metadata["workspace_key"] == "task-27"

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.DONE
        assert execute_task.workspace_key == "task-27"
        assert execute_task.repo_url == "https://example.test/default-repo.git"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["metadata"]["workspace_key"] == "task-27"


def test_execute_worker_preserves_explicit_workspace_key_exactly(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = EnsureWorkspaceRecorderMockScm()
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-EXPLICIT",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="Repo-Explicit-42",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-EXPLICIT",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="Repo-Explicit-42",
                context={"title": "Run"},
                input_payload={"instructions": "Run."},
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert scm.ensure_workspace_payloads[0].workspace_key == "Repo-Explicit-42"

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.workspace_key == "Repo-Explicit-42"


def test_pr_feedback_still_requires_existing_workspace_key(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-PR-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-PR-27",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                branch_name="task27/worker-2",
                pr_external_id="1",
                pr_url="https://example.test/repo/pull/1",
                context={"title": "Execute task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_task_id="comment-1",
                external_parent_id="1",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                branch_name="task27/worker-2",
                pr_external_id="1",
                pr_url="https://example.test/repo/pull/1",
                input_payload={
                    "instructions": "Address feedback.",
                    "pr_feedback": {
                        "pr_external_id": "1",
                        "comment_id": "comment-1",
                        "body": "Please update the tests.",
                        "pr_url": "https://example.test/repo/pull/1",
                    },
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_pr_feedback_tasks == 0
    assert report.failed_pr_feedback_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        feedback_task = session.get(Task, 3)
        assert feedback_task is not None
        assert feedback_task.status == TaskStatus.FAILED
        assert feedback_task.error == "Worker 2 requires workspace_key for SCM workspace sync"


def test_execute_worker_propagates_repo_url_errors_from_scm_adapter(tmp_path) -> None:
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
                external_task_id="TASK-90",
                workspace_key="repo-90",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-90",
                workspace_key="repo-90",
                context={"title": "Execute without repo_url"},
            )
        )

    report = worker.poll_once()

    assert report.failed_execute_tasks == 1
    assert agent_runner.requests == []

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "MockScm requires repo_url"


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


def test_execute_worker_marks_cli_non_zero_exit_failed_without_scm_follow_up(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = MockScm()
    agent_runner = FailedCliAgentRunner(exit_code=17)
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
                external_task_id="TASK-88",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-88",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-88",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-88",
                context={"title": "CLI failure"},
                input_payload={
                    "instructions": "Run a CLI command that fails.",
                    "base_branch": "main",
                    "branch_name": "task88/cli-failure",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 0
    assert report.failed_execute_tasks == 1
    assert len(agent_runner.requests) == 1
    assert scm._commit_sequence == 0
    assert scm._pull_requests == {}

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "CLI agent run failed with exit code 17."
        assert execute_task.branch_name == "task88/cli-failure"
        assert execute_task.pr_external_id is None
        assert execute_task.pr_url is None
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["summary"] == "CLI agent run failed with exit code 17."
        assert execute_task.result_payload["metadata"]["execution_status"] == "failed"

        deliver_tasks = session.query(Task).filter(Task.task_type == TaskType.DELIVER).all()
        assert deliver_tasks == []

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


class DefaultRepoUrlMockScm(MockScm):
    def __init__(self, default_repo_url: str) -> None:
        super().__init__()
        self._default_repo_url = default_repo_url

    def ensure_workspace(self, payload):
        if payload.repo_url is None:
            payload = payload.model_copy(update={"repo_url": self._default_repo_url})
        return super().ensure_workspace(payload)


def test_execute_worker_persists_resolved_repo_url_back_to_task(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = DefaultRepoUrlMockScm("https://example.test/default-repo.git")
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-100",
                workspace_key="repo-100",
                context={"title": "Tracker task"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-100",
                workspace_key="repo-100",
                context={"title": "Implement Worker 2"},
                input_payload={
                    "instructions": "Run with default repo_url",
                    "branch_name": "task100/run",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.repo_url == "https://example.test/default-repo.git"
        assert execute_task.workspace_key == "repo-100"
        assert execute_task.result_payload is not None
        result_metadata = execute_task.result_payload["metadata"]
        assert result_metadata["repo_url"] == "https://example.test/default-repo.git"


def test_execute_worker_uses_scm_branch_prefix_from_settings(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = replace(get_settings(), scm_branch_prefix="hl/")
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="ENG-42",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-eng",
                context={"title": "Tracker"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="ENG-42",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-eng",
                context={"title": "Run"},
                input_payload={"instructions": "Run."},
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    with session_scope(session_factory=session_factory) as session:
        execute_task = session.get(Task, 2)
        assert execute_task is not None
        assert execute_task.branch_name == "hl/eng-42"


def test_execute_worker_uses_scm_default_base_branch(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = replace(get_settings(), scm_default_base_branch="develop")
    scm = MockScm()
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-200",
                repo_url="https://example.test/repo.git",
                workspace_key="repo-200",
                context={"title": "Tracker"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-200",
                repo_url="https://example.test/repo.git",
                workspace_key="repo-200",
                context={"title": "Run"},
                input_payload={
                    "instructions": "Run with develop fallback.",
                    "branch_name": "task200/run",
                },
            )
        )

    report = worker.poll_once()

    assert report.processed_execute_tasks == 1
    pull_requests = list(scm._pull_requests.values())
    assert len(pull_requests) == 1
    assert pull_requests[0].base_branch == "develop"


def test_execute_worker_pr_metadata_uses_workspace_repo_url(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = DefaultRepoUrlMockScm("https://example.test/default-repo.git")
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-300",
                workspace_key="repo-300",
                context={"title": "Tracker"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-300",
                workspace_key="repo-300",
                context={"title": "Run"},
                input_payload={
                    "instructions": "Run.",
                    "branch_name": "task300/run",
                },
            )
        )

    worker.poll_once()

    pull_requests = list(scm._pull_requests.values())
    assert len(pull_requests) == 1
    pr_metadata = pull_requests[0].pr_metadata
    assert pr_metadata.repo_url == "https://example.test/default-repo.git"
    assert pr_metadata.workspace_key == "repo-300"


def _build_session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)
