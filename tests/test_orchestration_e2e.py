from __future__ import annotations

from dataclasses import replace

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
    TrackerTaskCreatePayload,
)
from backend.services.agent_runner import LocalAgentRunner
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


class RecordingAgentRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
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
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert intake_report == intake_report.__class__(
        fetched_count=1,
        created_fetch_tasks=1,
        created_execute_tasks=1,
        fetched_feedback_items=0,
        created_pr_feedback_tasks=0,
        skipped_feedback_items=0,
        unmapped_feedback_items=0,
    )
    assert execute_report.processed_execute_tasks == 1
    assert execute_report.failed_execute_tasks == 0
    assert deliver_report.processed_deliver_tasks == 1
    assert deliver_report.failed_deliver_tasks == 0
    assert len(runner.requests) == 1
    assert runner.requests[0].workspace_path == "/tmp/mock-scm/repo-48"
    assert runner.requests[0].task_context.flow_type == TaskType.EXECUTE
    assert runner.requests[0].task_context.instructions == "Run the full HTTP intake happy path."

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None

        assert fetch_task.status == TaskStatus.DONE
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task48/http-intake-e2e"
        assert execute_task.pr_external_id == "1"
        assert execute_task.pr_url == "https://example.test/repo/pull/1"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["summary"] == "Fake CLI runner completed execution."
        assert execute_task.result_payload["commit_sha"] == "mock-commit-0001"
        assert execute_task.result_payload["metadata"] == {
            "runner_adapter": "fake-cli",
            "mode": "test-double",
            "request_metadata": {
                "task_id": execute_task.id,
                "task_type": "execute",
                "workspace_key": "repo-48",
                "workspace_path": "/tmp/mock-scm/repo-48",
                "branch_name": "task48/http-intake-e2e",
                "repo_url": "https://example.test/repo.git",
                "repo_ref": "main",
            },
            "workspace_path": "/tmp/mock-scm/repo-48",
            "workspace_key": "repo-48",
            "repo_url": "https://example.test/repo.git",
            "repo_ref": "main",
            "flow_type": "execute",
            "pr_action": "created",
        }
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["metadata"] == {
            "tracker_external_id": "task-1",
            "tracker_status": "done",
            "comment_posted": True,
            "links_attached": 3,
        }

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 1
        assert token_usage_entries[0].task_id == execute_task.id
        assert token_usage_entries[0].model == "fake-cli-model"
        assert token_usage_entries[0].provider == "test"

    assert runtime.tracker._tasks["task-1"].status == TaskStatus.DONE
    assert len(runtime.tracker._comments["task-1"]) == 1
    assert runtime.tracker._comments["task-1"][0].body == (
        "CLI runner delivered a deterministic happy-path result."
    )
    assert [reference.url for reference in runtime.tracker._tasks["task-1"].context.references] == [
        "https://example.test/artifacts/task48-report",
        "https://example.test/repo/tree/task48/http-intake-e2e",
        "https://example.test/repo/pull/1",
    ]


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
    execute_report = execute_worker.poll_once()
    deliver_report = deliver_worker.poll_once()

    assert intake_report.fetched_count == 1
    assert intake_report.created_fetch_tasks == 1
    assert intake_report.created_execute_tasks == 1
    assert intake_report.created_pr_feedback_tasks == 0
    assert execute_report.processed_execute_tasks == 1
    assert execute_report.failed_execute_tasks == 0
    assert deliver_report.processed_deliver_tasks == 1
    assert deliver_report.failed_deliver_tasks == 0

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
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id, task_type=TaskType.DELIVER
        )
        assert deliver_task is not None
        assert fetch_task.status == TaskStatus.DONE
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE
        assert execute_task.branch_name == "task33/e2e-flow"
        assert execute_task.pr_external_id == "1"
        assert execute_task.pr_url == "https://example.test/repo/pull/1"
        assert execute_task.result_payload is not None
        assert execute_task.result_payload["metadata"]["flow_type"] == "execute"
        assert execute_task.result_payload["metadata"]["pr_action"] == "created"
        assert deliver_task.result_payload is not None
        assert deliver_task.result_payload["metadata"] == {
            "tracker_external_id": tracker_task.external_id,
            "tracker_status": "done",
            "comment_posted": True,
            "links_attached": 2,
        }

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 1
        assert token_usage_entries[0].task_id == execute_task.id

    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body == (
        "Prepared local agent execution for Implement orchestration e2e"
        ".\n\nWorkspace: /tmp/mock-scm/repo-33\n"
        "Flow: execute\n"
        "Instructions: Implement the full orchestration flow."
    )
    assert [
        reference.url for reference in tracker._tasks[tracker_task.external_id].context.references
    ] == [
        "https://example.test/repo/tree/task33/e2e-flow",
        "https://example.test/repo/pull/1",
    ]


def test_orchestration_flow_updates_execute_result_after_pr_feedback(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
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
    initial_execute_report = execute_worker.poll_once()

    assert intake_report.created_execute_tasks == 1
    assert initial_execute_report.processed_execute_tasks == 1

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
        original_commit_sha = execute_task.result_payload["commit_sha"]
        pull_request_id = execute_task.pr_external_id

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
            external_task_id=tracker_task.external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
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
        assert task_types == [
            TaskType.FETCH,
            TaskType.EXECUTE,
            TaskType.DELIVER,
            TaskType.PR_FEEDBACK,
        ]

        token_usage_entries = session.query(TokenUsage).order_by(TokenUsage.id.asc()).all()
        assert len(token_usage_entries) == 2
        assert token_usage_entries[0].task_id == execute_task.id
        assert token_usage_entries[1].task_id == feedback_task.id

    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body == (
        "Prepared local agent execution for Handle PR feedback e2e"
        ".\n\nWorkspace: /tmp/mock-scm/repo-33-feedback\n"
        "Flow: execute\n"
        "Instructions: Implement the initial PR version."
    )
