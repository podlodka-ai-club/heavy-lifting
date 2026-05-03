from __future__ import annotations

import subprocess
from dataclasses import replace
from decimal import Decimal

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task, TokenUsage
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.repositories.task_repository import TaskRepository
from backend.schemas import (
    TaskContext,
    TaskInputPayload,
    TaskLink,
    TaskResultPayload,
    TokenUsagePayload,
    TrackerCommentCreatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTaskCreatePayload,
)
from backend.services.agent_runner import CliAgentRunner, CliAgentRunnerConfig, LocalAgentRunner
from backend.services.mock_task_selection import MockTaskSelectionService
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.workers.deliver_worker import DeliverWorker
from backend.workers.execute_worker import ExecuteWorker
from backend.workers.tracker_intake import TrackerIntakeWorker


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


_BRIEF_BODY_SP2 = (
    "## Agent Handover Brief\n"
    "**Assigned Story Points:** 2\n\n"
    "### 1. Intent\n- e2e triage stub\n"
)

_RFI_BODY_SP5_ESTIMATE_ONLY = (
    "## RFI\n\n"
    "2 story points\n"
    "Reason: adding CLI command logging is a small isolated change.\n"
)


def _triage_envelope(*, sp: int, task_kind: str, outcome: str, body: str) -> str:
    return (
        "<triage_result>\n"
        f"story_points: {sp}\n"
        f"task_kind: {task_kind}\n"
        f"outcome: {outcome}\n"
        "</triage_result>\n"
        "<markdown>\n"
        f"{body}"
        "</markdown>\n"
    )


def _is_triage_request(request: AgentRunRequest) -> bool:
    input_payload = request.task_context.current_task.input_payload
    return input_payload is not None and input_payload.action == "triage"


class RecordingAgentRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        if _is_triage_request(request):
            return AgentRunResult(
                payload=TaskResultPayload(
                    summary="Fake triage envelope.",
                    token_usage=[
                        TokenUsagePayload(
                            model="fake-cli-model",
                            provider="test",
                            input_tokens=32,
                            output_tokens=12,
                            cached_tokens=3,
                        )
                    ],
                ),
                raw_stdout=_triage_envelope(
                    sp=2,
                    task_kind="implementation",
                    outcome="routed",
                    body=_BRIEF_BODY_SP2,
                ),
                raw_stderr="",
            )
        return AgentRunResult(
            payload=TaskResultPayload(
                summary="Fake CLI runner completed execution.",
                details="Runner executed through the e2e HTTP intake path.",
                tracker_comment="CLI runner delivered a deterministic happy-path result.",
                links=[
                    TaskLink(
                        label="artifact",
                        url="https://example.test/artifacts/task48-report",
                    )
                ],
                token_usage=[
                    TokenUsagePayload(
                        model="fake-cli-model",
                        provider="test",
                        input_tokens=64,
                        output_tokens=21,
                        cached_tokens=5,
                    )
                ],
                metadata={
                    "runner_adapter": "fake-cli",
                    "mode": "test-double",
                    "request_metadata": dict(request.metadata),
                    "workspace_path": request.workspace_path,
                },
            )
        )


class EstimateOnlyRecordingRunner:
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
        if _is_triage_request(request):
            return AgentRunResult(
                payload=TaskResultPayload(
                    summary="Fake triage RFI envelope.",
                    token_usage=[],
                ),
                raw_stdout=_triage_envelope(
                    sp=5,
                    task_kind="research",
                    outcome="needs_clarification",
                    body=_RFI_BODY_SP5_ESTIMATE_ONLY,
                ),
                raw_stderr="",
            )
        return AgentRunResult(
            payload=TaskResultPayload(
                summary="CLI agent run completed successfully.",
                details=self.details
                or (
                    "stdout:\n2 story points\nReason: adding CLI command logging "
                    "is a small isolated change."
                ),
                tracker_comment=self.tracker_comment,
                metadata={
                    "runner_adapter": "cli",
                    "request_metadata": dict(request.metadata),
                    "workspace_path": request.workspace_path,
                    "stdout_preview": self.stdout_preview
                    or (
                        "2 story points\nReason: adding CLI command logging "
                        "is a small isolated change."
                    ),
                },
            )
        )


def test_http_intake_flow_runs_workers_end_to_end(session_factory) -> None:
    runner = RecordingAgentRunner()
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=runner,
    )
    app = create_app(runtime=runtime, session_factory=session_factory)

    response = app.test_client().post(
        "/tasks/intake",
        json={
            "context": {
                "title": "HTTP intake e2e",
                "description": "Create task through API and process full chain",
                "acceptance_criteria": ["Deliver final result to tracker"],
            },
            "input_payload": {
                "instructions": "Run the full HTTP intake happy path.",
                "base_branch": "main",
                "branch_name": "task48/http-intake-e2e",
                "commit_message_hint": "task48 e2e fake cli execution",
            },
            "repo_url": "https://example.test/repo.git",
            "repo_ref": "main",
            "workspace_key": "repo-48",
        },
    )

    assert response.status_code == 201
    assert response.get_json() == {"external_id": "task-1"}

    intake_worker = TrackerIntakeWorker(
        tracker=runtime.tracker,
        scm=runtime.scm,
        tracker_name=runtime.settings.tracker_adapter,
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=runtime.scm,
        agent_runner=runtime.agent_runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=runtime.tracker, session_factory=session_factory)

    intake_report = intake_worker.poll_once()
    triage_execute_report = execute_worker.poll_once()
    impl_execute_report = execute_worker.poll_once()
    deliver_triage_report = deliver_worker.poll_once()
    deliver_impl_report = deliver_worker.poll_once()

    assert intake_report == intake_report.__class__(
        fetched_count=1,
        created_fetch_tasks=1,
        created_execute_tasks=1,
        fetched_feedback_items=0,
        created_pr_feedback_tasks=0,
        skipped_feedback_items=0,
        unmapped_feedback_items=0,
    )
    assert triage_execute_report.processed_execute_tasks == 1
    assert triage_execute_report.failed_execute_tasks == 0
    assert impl_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.failed_execute_tasks == 0
    assert deliver_triage_report.processed_deliver_tasks == 1
    assert deliver_triage_report.failed_deliver_tasks == 0
    assert deliver_impl_report.processed_deliver_tasks == 1
    assert deliver_impl_report.failed_deliver_tasks == 0
    assert len(runner.requests) == 2
    assert runner.requests[0].task_context.current_task.input_payload is not None
    assert runner.requests[0].task_context.current_task.input_payload.action == "triage"
    assert runner.requests[1].task_context.current_task.input_payload is not None
    assert runner.requests[1].task_context.current_task.input_payload.action == "implementation"
    assert runner.requests[1].workspace_path == "/tmp/mock-scm/repo-48"
    assert runner.requests[1].task_context.flow_type == TaskType.EXECUTE
    assert runner.requests[1].task_context.instructions == "Run the full HTTP intake happy path."

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        triage_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert triage_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        triage_deliver_task = repository.find_child_task(
            parent_id=triage_task.id, task_type=TaskType.DELIVER
        )
        assert triage_deliver_task is not None

        assert fetch_task.status == TaskStatus.DONE
        assert triage_task.status == TaskStatus.DONE
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert triage_deliver_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task48/http-intake-e2e"
        assert execute_task.pr_external_id == "1"
        assert execute_task.pr_url == "https://example.test/repo/pull/1"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["summary"] == "Fake CLI runner completed execution."
        assert execute_task.result_payload["commit_sha"] == "mock-commit-0001"
        metadata = execute_task.result_payload["metadata"]
        assert metadata["runner_adapter"] == "fake-cli"
        assert metadata["mode"] == "test-double"
        assert metadata["flow_type"] == "execute"
        assert metadata["pr_action"] == "created"
        assert "delivery_mode" not in metadata
        assert metadata["request_metadata"]["branch_name"] == "task48/http-intake-e2e"
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["metadata"] == {
            "tracker_external_id": "task-1",
            "tracker_status": "done",
            "comment_posted": True,
            "links_attached": 3,
        }

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 2
        assert {entry.task_id for entry in token_usage_entries} == {
            triage_task.id,
            execute_task.id,
        }
        assert all(entry.model == "fake-cli-model" for entry in token_usage_entries)
        assert all(entry.provider == "test" for entry in token_usage_entries)

    assert runtime.tracker._tasks["task-1"].status == TaskStatus.DONE
    assert len(runtime.tracker._comments["task-1"]) == 2
    triage_comment = runtime.tracker._comments["task-1"][0].body
    impl_comment = runtime.tracker._comments["task-1"][1].body
    assert triage_comment == "Triage SP=2: Brief сохранён, передано в работу."
    assert impl_comment == "CLI runner delivered a deterministic happy-path result."
    assert [reference.url for reference in runtime.tracker._tasks["task-1"].context.references] == [
        "https://example.test/artifacts/task48-report",
        "https://example.test/repo/tree/task48/http-intake-e2e",
        "https://example.test/repo/pull/1",
    ]


def test_http_intake_flow_persists_cli_token_usage_from_json_events(
    monkeypatch, session_factory
) -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=120,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
        )
    )
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=runner,
    )
    app = create_app(runtime=runtime, session_factory=session_factory)

    impl_stdout = (
        '{"type":"step_start","part":{"type":"step-start"}}\n'
        '{"type":"text","part":{"type":"text","text":"CLI worker completed task."}}\n'
        '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":215,'
        '"input":144,"output":54,"reasoning":17,"cache":{"read":22,"write":3}},'
        '"cost":"0.008765"}}\n'
    )
    triage_stdout = (
        "<triage_result>\n"
        "story_points: 2\n"
        "task_kind: implementation\n"
        "outcome: routed\n"
        "</triage_result>\n"
        "<markdown>\n"
        "## Agent Handover Brief\n"
        "**Assigned Story Points:** 2\n\n"
        "### 1. Intent\n- triage stub\n"
        "</markdown>\n"
        '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":120,'
        '"input":80,"output":30,"reasoning":10,"cache":{"read":5,"write":1}},'
        '"cost":"0.001"}}\n'
    )

    def fake_run(command, **kwargs):
        # The CliAgentRunner places the prompt as the last argument. The triage
        # prompt embeds the literal "<role>" / "<task_context>" blocks rendered
        # by TriageStep.build_prompt, so we use those as the discriminator.
        prompt_arg = command[-1] if command else ""
        is_triage = "<role>" in prompt_arg and "<task_context>" in prompt_arg
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=triage_stdout if is_triage else impl_stdout,
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = app.test_client().post(
        "/tasks/intake",
        json={
            "context": {"title": "CLI token accounting e2e"},
            "input_payload": {
                "instructions": "Run the CLI worker and persist real token usage.",
                "base_branch": "main",
                "branch_name": "task77/cli-token-accounting",
            },
            "repo_url": "https://example.test/repo.git",
            "repo_ref": "main",
            "workspace_key": "repo-77",
        },
    )

    assert response.status_code == 201

    intake_worker = TrackerIntakeWorker(
        tracker=runtime.tracker,
        scm=runtime.scm,
        tracker_name=runtime.settings.tracker_adapter,
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=runtime.scm,
        agent_runner=runtime.agent_runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=runtime.tracker, session_factory=session_factory)

    intake_worker.poll_once()
    triage_execute_report = execute_worker.poll_once()
    impl_execute_report = execute_worker.poll_once()
    deliver_worker.poll_once()
    deliver_worker.poll_once()

    assert triage_execute_report.processed_execute_tasks == 1
    assert triage_execute_report.failed_execute_tasks == 0
    assert impl_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.failed_execute_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        triage_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert triage_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["details"] == "stdout:\nCLI worker completed task."
        assert execute_task.result_payload["metadata"]["usage"] == {
            "status": "parsed",
            "model": "gpt-5.4",
            "provider": "openai",
            "input_tokens": 144,
            "output_tokens": 54,
            "cached_tokens": 22,
            "cost_usd": "0.008765",
            "reasoning_tokens": 17,
            "total_tokens": 215,
            "cache_write_tokens": 3,
        }

        # Triage execute does not record token usage: CliAgentRunner's stdout
        # parser bails out on the first non-JSON line (the <triage_result>
        # envelope), so payload.token_usage is empty for the triage run.
        # The impl execute records its full usage as before.
        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 1
        impl_usage = token_usage_entries[0]
        assert impl_usage.task_id == execute_task.id
        assert impl_usage.model == "gpt-5.4"
        assert impl_usage.provider == "openai"
        assert impl_usage.input_tokens == 144
        assert impl_usage.output_tokens == 54
        assert impl_usage.cached_tokens == 22
        assert impl_usage.estimated is False
        assert impl_usage.cost_usd == Decimal("0.008765")


def test_http_intake_flow_stops_after_cli_non_zero_exit(monkeypatch, session_factory) -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=120,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
        )
    )
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=runner,
    )
    app = create_app(runtime=runtime, session_factory=session_factory)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=23,
            stdout='{"type":"text","part":{"type":"text","text":"CLI failed."}}\n',
            stderr="fatal: command failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = app.test_client().post(
        "/tasks/intake",
        json={
            "context": {"title": "CLI non-zero exit e2e"},
            "input_payload": {
                "instructions": "Run the CLI worker and stop on failure.",
                "base_branch": "main",
                "branch_name": "task89/cli-non-zero",
            },
            "repo_url": "https://example.test/repo.git",
            "repo_ref": "main",
            "workspace_key": "repo-89",
        },
    )

    assert response.status_code == 201

    intake_worker = TrackerIntakeWorker(
        tracker=runtime.tracker,
        scm=runtime.scm,
        tracker_name=runtime.settings.tracker_adapter,
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=runtime.scm,
        agent_runner=runtime.agent_runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=runtime.tracker, session_factory=session_factory)

    intake_worker.poll_once()
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert execute_report.processed_execute_tasks == 0
    assert execute_report.failed_execute_tasks == 1
    assert deliver_report.processed_deliver_tasks == 0
    assert deliver_report.failed_deliver_tasks == 0
    assert runtime.scm._commit_sequence == 0
    assert runtime.scm._pull_requests == {}

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        # The first execute is the triage execute. Its output (a generic
        # JSON-event line) is not a triage envelope, so the triage parser
        # rejects it and the worker fails the task with
        # error="triage_output_malformed" — exit_code/stderr are not surfaced
        # because the triage path bypasses the CLI execution_status check.
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "triage_output_malformed"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["summary"] == "Triage agent output malformed."
        assert "CLI failed." in execute_task.result_payload["metadata"]["raw_stdout_preview"]
        assert execute_task.pr_external_id is None
        assert execute_task.pr_url is None

        # No sibling impl execute is ever created when triage fails.
        assert repository.find_implementation_execute_for_root(fetch_task.id) is None

        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is None

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert token_usage_entries == []

    assert runtime.tracker._tasks["task-1"].status == TaskStatus.NEW
    assert runtime.tracker._comments.get("task-1", []) == []


def test_http_intake_flow_stops_after_cli_error_signals_with_zero_exit(
    monkeypatch, session_factory
) -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=120,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
        )
    )
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=runner,
    )
    app = create_app(runtime=runtime, session_factory=session_factory)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"text","part":{"type":"text","text":"Preparing request."}}\n'
                '{"type":"error","part":{"type":"error",'
                '"text":"Invalid model: openai/missing-model"}}\n'
                '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":21,'
                '"input":13,"output":5,"reasoning":3,"cache":{"read":1,"write":0}},'
                '"cost":"0.001200"}}\n'
            ),
            stderr=(
                "ProviderModelNotFoundError: openai/missing-model "
                "is not available for this provider"
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = app.test_client().post(
        "/tasks/intake",
        json={
            "context": {"title": "CLI invalid model e2e"},
            "input_payload": {
                "instructions": "Run the CLI worker and stop when the model is invalid.",
                "base_branch": "main",
                "branch_name": "task90/cli-invalid-model",
            },
            "repo_url": "https://example.test/repo.git",
            "repo_ref": "main",
            "workspace_key": "repo-90",
        },
    )

    assert response.status_code == 201

    intake_worker = TrackerIntakeWorker(
        tracker=runtime.tracker,
        scm=runtime.scm,
        tracker_name=runtime.settings.tracker_adapter,
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=runtime.scm,
        agent_runner=runtime.agent_runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=runtime.tracker, session_factory=session_factory)

    intake_worker.poll_once()
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert execute_report.processed_execute_tasks == 0
    assert execute_report.failed_execute_tasks == 1
    assert deliver_report.processed_deliver_tasks == 0
    assert deliver_report.failed_deliver_tasks == 0
    assert runtime.scm._commit_sequence == 0
    assert runtime.scm._pull_requests == {}

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        # First execute is now triage; its stdout (text/error JSON events) is
        # not a triage envelope, so the triage parser rejects it. The worker
        # surfaces "triage_output_malformed" — the CLI-level execution_status
        # / failure_message is not consulted in the triage path. No sibling
        # impl execute, no deliver task, no SCM artifacts, no token usage.
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        assert execute_task.status == TaskStatus.FAILED
        assert execute_task.error == "triage_output_malformed"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["summary"] == "Triage agent output malformed."
        raw_preview = execute_task.result_payload["metadata"]["raw_stdout_preview"]
        assert "Preparing request." in raw_preview
        assert "Invalid model: openai/missing-model" in raw_preview
        assert execute_task.pr_external_id is None
        assert execute_task.pr_url is None

        assert repository.find_implementation_execute_for_root(fetch_task.id) is None

        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is None

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert token_usage_entries == []

    assert runtime.tracker._tasks["task-1"].status == TaskStatus.NEW
    assert runtime.tracker._comments.get("task-1", []) == []


def test_orchestration_flow_fetch_execute_deliver(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Implement orchestration e2e",
                description="Run the full MVP orchestration flow.",
                acceptance_criteria=["Deliver the result back to the tracker"],
            ),
            input_payload=TaskInputPayload(
                instructions="Implement the full orchestration flow.",
                base_branch="main",
                branch_name="task33/e2e-flow",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-33",
        )
    )
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_report = intake_worker.poll_once()
    triage_execute_report = execute_worker.poll_once()
    impl_execute_report = execute_worker.poll_once()
    deliver_triage_report = deliver_worker.poll_once()
    deliver_impl_report = deliver_worker.poll_once()

    assert intake_report.fetched_count == 1
    assert intake_report.created_fetch_tasks == 1
    assert intake_report.created_execute_tasks == 1
    assert intake_report.created_pr_feedback_tasks == 0
    assert triage_execute_report.processed_execute_tasks == 1
    assert triage_execute_report.failed_execute_tasks == 0
    assert impl_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.failed_execute_tasks == 0
    assert deliver_triage_report.processed_deliver_tasks == 1
    assert deliver_triage_report.failed_deliver_tasks == 0
    assert deliver_impl_report.processed_deliver_tasks == 1
    assert deliver_impl_report.failed_deliver_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=tracker_task.external_id,
        )

        assert fetch_task is not None
        triage_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert triage_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        triage_deliver_task = repository.find_child_task(
            parent_id=triage_task.id, task_type=TaskType.DELIVER
        )
        assert triage_deliver_task is not None
        assert fetch_task.status == TaskStatus.DONE
        assert triage_task.status == TaskStatus.DONE
        assert triage_task.branch_name is None
        assert triage_task.pr_external_id is None
        assert triage_task.pr_url is None
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert triage_deliver_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task33/e2e-flow"
        assert execute_task.pr_external_id == "1"
        assert execute_task.pr_url == "https://example.test/repo/pull/1"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["metadata"]["flow_type"] == "execute"
        assert execute_task.result_payload["metadata"]["pr_action"] == "created"
        assert "delivery_mode" not in execute_task.result_payload["metadata"]
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["metadata"] == {
            "tracker_external_id": tracker_task.external_id,
            "tracker_status": "done",
            "comment_posted": True,
            "links_attached": 2,
        }

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 2
        assert {entry.task_id for entry in token_usage_entries} == {
            triage_task.id,
            execute_task.id,
        }

    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    assert len(tracker._comments[tracker_task.external_id]) == 2
    assert tracker._comments[tracker_task.external_id][0].body == (
        "Triage SP=2: Brief сохранён, передано в работу."
    )
    assert tracker._comments[tracker_task.external_id][1].body == (
        "Prepared local agent execution for Implement orchestration e2e"
        ".\n\nWorkspace: /tmp/mock-scm/repo-33\n"
        "Flow: execute\n"
        "Instructions: Implement the full orchestration flow."
    )
    reference_urls = [
        reference.url
        for reference in tracker._tasks[tracker_task.external_id].context.references
    ]
    assert reference_urls == [
        "https://example.test/repo/tree/task33/e2e-flow",
        "https://example.test/repo/pull/1",
    ]


def test_orchestration_flow_routes_estimate_only_to_delivery_without_scm_side_effects(
    session_factory,
) -> None:
    tracker = MockTracker()
    scm = MockScm()
    runner = EstimateOnlyRecordingRunner()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Estimate CLI logging task",
                description="Estimate only. Do not modify code.",
                acceptance_criteria=["Return story point estimate to tracker"],
            ),
            input_payload=TaskInputPayload(
                instructions="Give only a story point estimate and do not modify code.",
                base_branch="main",
                branch_name="task63/estimate-only",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-63",
        )
    )
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_report = intake_worker.poll_once()
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert intake_report.created_execute_tasks == 1
    assert execute_report.processed_execute_tasks == 1
    assert execute_report.failed_execute_tasks == 0
    assert deliver_report.processed_deliver_tasks == 1
    # Only one agent run: the triage. SP=5 escalates with no sibling impl
    # execute, so the runner is never re-invoked.
    assert len(runner.requests) == 1
    assert runner.requests[0].metadata["action"] == "triage"
    assert runner.requests[0].metadata["branch_name"] is None
    assert scm._branches == {}
    assert scm._pull_requests == {}
    assert scm._commit_sequence == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=tracker_task.external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        # SP=5 triage does NOT create a sibling implementation-execute.
        assert repository.find_implementation_execute_for_root(fetch_task.id) is None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert execute_task.branch_name is None
        assert execute_task.pr_external_id is None
        assert execute_task.pr_url is None
        assert execute_task.result_payload is not None
        # Triage SP=5 → outcome=needs_clarification, escalation=rfi, status
        # remains None (deliver does not call update_status).
        assert execute_task.result_payload["outcome"] == "needs_clarification"
        assert execute_task.result_payload["estimate"]["story_points"] == 5
        delivery = execute_task.result_payload["delivery"]
        assert delivery["tracker_estimate"] == 5
        assert delivery["escalation_kind"] == "rfi"
        assert delivery["tracker_status"] is None
        assert delivery["tracker_labels"] == ["sp:5", "triage:rfi"]
        assert delivery["comment_body"].startswith("## RFI")
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["links"] == []
        assert deliver_task.result_payload["metadata"] == {
            "tracker_external_id": tracker_task.external_id,
            "tracker_status": None,
            "comment_posted": True,
            "links_attached": 0,
            "tracker_estimate": 5,
            "tracker_labels": ["sp:5", "triage:rfi"],
            "escalation_kind": "rfi",
        }

    # Tracker stays in NEW because deliver_triage does not call update_status
    # (delivery.tracker_status is None for SP=5 escalations).
    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.NEW
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body.startswith("## RFI")
    assert tracker._tasks[tracker_task.external_id].context.references == []


def test_orchestration_flow_merges_estimate_and_rationale_for_estimate_only_delivery(
    session_factory,
) -> None:
    tracker = MockTracker()
    scm = MockScm()
    runner = EstimateOnlyRecordingRunner(
        stdout_preview="2 story points",
        details="Reason: adding CLI command logging is a small isolated change.",
    )
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Estimate CLI logging task",
                description="Estimate only. Do not modify code.",
                acceptance_criteria=["Return story point estimate to tracker"],
            ),
            input_payload=TaskInputPayload(
                instructions="Give only a story point estimate and do not modify code.",
                base_branch="main",
                branch_name="task63/estimate-only",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-63",
        )
    )
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_worker.poll_once()
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert execute_report.processed_execute_tasks == 1
    assert deliver_report.processed_deliver_tasks == 1
    assert tracker._comments[tracker_task.external_id][0].body == (
        _RFI_BODY_SP5_ESTIMATE_ONLY.strip()
    )


def test_orchestration_top_level_intake_uses_explicit_estimate_mode_without_keywords(
    session_factory,
) -> None:
    tracker = MockTracker()
    scm = MockScm()
    runner = EstimateOnlyRecordingRunner(
        stdout_preview="2 story points",
        details="Reason: this is a small isolated change.",
    )
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Assess CLI logging task",
                description="Assess complexity for planning.",
                acceptance_criteria=["Return an estimate to tracker"],
            ),
            input_payload=TaskInputPayload(
                instructions="Assess complexity and report result.",
                base_branch="main",
                branch_name="task163/assess",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-163",
        )
    )
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_worker.poll_once()
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert execute_report.processed_execute_tasks == 1
    assert deliver_report.processed_deliver_tasks == 1
    assert scm._branches == {}
    assert scm._pull_requests == {}
    assert scm._commit_sequence == 0
    assert tracker._comments[tracker_task.external_id][0].body == (
        _RFI_BODY_SP5_ESTIMATE_ONLY.strip()
    )


def test_selected_estimated_tracker_task_flows_through_existing_pipeline(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    estimated_parent = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Implement selected backlog task",
                description="Previously estimated small task.",
                acceptance_criteria=["Open a PR and deliver result to tracker"],
            ),
            input_payload=TaskInputPayload(
                instructions="Implement the selected backlog task.",
                base_branch="main",
                branch_name="task120/selected-from-estimate",
                commit_message_hint="task120 selected backlog task",
            ),
            status=TaskStatus.DONE,
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-120",
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    selected = MockTaskSelectionService(tracker=tracker).select_small_estimated_task(
        max_story_points=3
    )
    assert selected is not None

    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_report = intake_worker.poll_once()
    triage_execute_report = execute_worker.poll_once()
    impl_execute_report = execute_worker.poll_once()
    deliver_triage_report = deliver_worker.poll_once()
    deliver_impl_report = deliver_worker.poll_once()

    assert intake_report.created_fetch_tasks == 1
    assert intake_report.created_execute_tasks == 1
    assert triage_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.processed_execute_tasks == 1
    assert deliver_triage_report.processed_deliver_tasks == 1
    assert deliver_impl_report.processed_deliver_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=selected.created_task.external_id,
        )

        assert fetch_task is not None
        triage_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert triage_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        assert fetch_task.external_parent_id == estimated_parent.external_id
        assert execute_task.external_parent_id == selected.created_task.external_id
        assert triage_task.status == TaskStatus.DONE
        assert execute_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task120/selected-from-estimate"
        assert execute_task.pr_external_id is not None
        assert deliver_task.status == TaskStatus.DONE

    selected_tracker_task = tracker._tasks[selected.created_task.external_id]
    assert selected_tracker_task.status == TaskStatus.DONE
    assert (
        tracker._tasks[estimated_parent.external_id].metadata["selection"]["taken_in_work"] is True
    )
    # Two comments now: triage SP=2 brief comment + impl summary.
    assert len(tracker._comments[selected.created_task.external_id]) == 2
    assert tracker._comments.get(estimated_parent.external_id, []) == []


def test_orchestration_flow_updates_execute_result_after_pr_feedback(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    parent_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Estimated parent task"),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    selected_ref = tracker.create_subtask(
        TrackerSubtaskCreatePayload(
            parent_external_id=parent_task.external_id,
            context=TaskContext(title="Handle PR feedback e2e"),
            input_payload=TaskInputPayload(
                instructions="Implement the initial PR version.",
                base_branch="main",
                branch_name="task33/pr-feedback-flow",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-33-feedback",
        )
    )
    tracker_task_external_id = selected_ref.external_id
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=LocalAgentRunner(),
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_report = intake_worker.poll_tracker_once()
    triage_execute_report = execute_worker.poll_once()
    impl_execute_report = execute_worker.poll_once()
    # Deliver only the triage now; defer impl deliver until after PR feedback
    # so the impl deliver captures the post-feedback commit_sha.
    deliver_triage_report = deliver_worker.poll_once()

    assert intake_report.created_execute_tasks == 1
    assert triage_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.processed_execute_tasks == 1
    assert deliver_triage_report.processed_deliver_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=tracker_task_external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        original_commit_sha = execute_task.result_payload["commit_sha"]
        pull_request_id = execute_task.pr_external_id
        triage_id = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        ).id

    assert pull_request_id is not None
    feedback_item = scm.add_pr_feedback(
        pull_request_id,
        "Please update the implementation details before delivery.",
        author="reviewer-1",
    )

    feedback_report = intake_worker.poll_pr_feedback_once()
    feedback_execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert feedback_report.fetched_feedback_items == 1
    assert feedback_report.created_pr_feedback_tasks == 1
    assert feedback_execute_report.processed_pr_feedback_tasks == 1
    assert feedback_execute_report.failed_pr_feedback_tasks == 0
    assert deliver_report.processed_deliver_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=tracker_task_external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        feedback_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.PR_FEEDBACK,
            external_task_id=feedback_item.comment_id,
        )

        assert feedback_task is not None
        assert execute_task.status == TaskStatus.DONE
        assert feedback_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert feedback_task.branch_name == execute_task.branch_name == "task33/pr-feedback-flow"
        assert feedback_task.pr_external_id == execute_task.pr_external_id
        assert feedback_task.pr_url == execute_task.pr_url
        assert execute_task.result_payload is not None
        assert feedback_task.result_payload is not None
        assert execute_task.result_payload["commit_sha"] != original_commit_sha
        assert execute_task.result_payload["commit_sha"] == "mock-commit-0002"
        assert execute_task.result_payload["metadata"]["last_updated_flow"] == "pr_feedback"
        assert execute_task.result_payload["metadata"]["last_feedback_task_id"] == feedback_task.id
        assert execute_task.result_payload["metadata"]["last_feedback_comment_id"] == (
            feedback_item.comment_id
        )
        assert feedback_task.result_payload["metadata"]["flow_type"] == "pr_feedback"
        assert feedback_task.result_payload["metadata"]["pr_action"] == "reused"
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["commit_sha"] == "mock-commit-0002"

        task_types = [task.task_type for task in session.query(Task).order_by(Task.id.asc()).all()]
        # Cluster after triage→impl two-step + PR feedback. Insertion order is
        # determined by the worker pipeline:
        #   1. tracker_intake creates fetch + triage(execute)
        #   2. triage processing creates the impl(execute) sibling first, then
        #      its own deliver(triage) child — so the impl row is inserted
        #      BEFORE the triage deliver.
        #   3. impl processing creates deliver(impl).
        #   4. tracker_intake.poll_pr_feedback creates pr_feedback.
        assert task_types == [
            TaskType.FETCH,
            TaskType.EXECUTE,  # triage
            TaskType.EXECUTE,  # impl (sibling created during triage processing)
            TaskType.DELIVER,  # deliver(triage)
            TaskType.DELIVER,  # deliver(impl)
            TaskType.PR_FEEDBACK,
        ]

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        # Three usage rows: triage, impl execute, pr_feedback execute.
        assert len(token_usage_entries) == 3
        assert {entry.task_id for entry in token_usage_entries} == {
            triage_id,
            execute_task.id,
            feedback_task.id,
        }

    assert tracker._tasks[tracker_task_external_id].status == TaskStatus.DONE
    # Two comments now: triage SP=2 brief + impl summary. PR feedback does
    # not produce a new tracker comment (deliver was for the impl path; PR
    # feedback updates the impl row in place).
    assert len(tracker._comments[tracker_task_external_id]) == 2
    assert tracker._comments[tracker_task_external_id][0].body == (
        "Triage SP=2: Brief сохранён, передано в работу."
    )
    assert tracker._comments[tracker_task_external_id][1].body == (
        "Prepared local agent execution for Handle PR feedback e2e"
        ".\n\nWorkspace: /tmp/mock-scm/repo-33-feedback\n"
        "Flow: execute\n"
        "Instructions: Implement the initial PR version."
    )


def test_orchestration_flow_replies_to_estimate_only_tracker_comment_without_scm_side_effects(
    session_factory,
) -> None:
    tracker = MockTracker()
    scm = MockScm()
    runner = EstimateOnlyRecordingRunner()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Estimate CLI logging task",
                description="Estimate only. Do not modify code.",
            ),
            input_payload=TaskInputPayload(
                instructions="Give only a story point estimate and do not modify code.",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-63",
        )
    )
    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    intake_worker.poll_once()
    execute_worker.poll_once()
    deliver_worker.poll_once()
    runner.tracker_comment = (
        "2 story points\nReason: the extra explanation still does not require code changes."
    )
    tracker.add_comment(
        TrackerCommentCreatePayload(
            external_task_id=tracker_task.external_id,
            body="Can you justify this estimate in more detail?",
            metadata={"source": "operator"},
        )
    )

    feedback_report = intake_worker.poll_tracker_feedback_once()
    feedback_execute_report = execute_worker.poll_once()
    feedback_deliver_report = deliver_worker.poll_once()

    assert feedback_report.created_tracker_feedback_tasks == 1
    assert feedback_report.skipped_feedback_items == 1
    assert feedback_execute_report.processed_tracker_feedback_tasks == 1
    assert feedback_execute_report.failed_tracker_feedback_tasks == 0
    assert feedback_deliver_report.processed_deliver_tasks == 1
    assert scm._branches == {}
    assert scm._pull_requests == {}
    assert scm._commit_sequence == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=tracker_task.external_id,
        )
        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        feedback_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.TRACKER_FEEDBACK,
            external_task_id="comment-2",
        )
        assert feedback_task is not None
        deliver_task = repository.find_child_task(
            parent_id=feedback_task.id,
            task_type=TaskType.DELIVER,
        )
        assert deliver_task is not None
        assert feedback_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert feedback_task.result_payload is not None
        assert feedback_task.result_payload["metadata"]["flow_type"] == "tracker_feedback"
        assert feedback_task.result_payload["metadata"]["pr_action"] == "skipped"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["metadata"]["last_updated_flow"] == "tracker_feedback"
        assert execute_task.result_payload["metadata"]["last_feedback_comment_id"] == "comment-2"

    assert [comment.body for comment in tracker._comments[tracker_task.external_id]] == [
        _RFI_BODY_SP5_ESTIMATE_ONLY.strip(),
        "Can you justify this estimate in more detail?",
        (
            "Оценка задачи:\n"
            "- Стоимость: 2 SP\n"
            "- Можно брать в работу сейчас: да\n"
            "- Обоснование: adding CLI command logging is a small isolated change."
        ),
    ]
