from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.demo import create_demo_components, main
from backend.models import Base
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.repositories.task_repository import TaskRepository
from backend.schemas import TaskResultPayload
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


_DEMO_TRIAGE_STDOUT = (
    "<triage_result>\n"
    "story_points: 2\n"
    "task_kind: implementation\n"
    "outcome: routed\n"
    "</triage_result>\n"
    "<markdown>\n"
    "## Agent Handover Brief\n"
    "**Assigned Story Points:** 2\n\n"
    "### 1. Intent\n- demo triage stub\n"
    "</markdown>\n"
)


class RecordingRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        input_payload = request.task_context.current_task.input_payload
        if input_payload is not None and input_payload.action == "triage":
            return AgentRunResult(
                payload=TaskResultPayload(summary="demo triage envelope"),
                raw_stdout=_DEMO_TRIAGE_STDOUT,
                raw_stderr="",
            )
        return AgentRunResult(payload=TaskResultPayload(summary="demo runner finished"))


def test_create_demo_components_share_runtime_and_session_factory(session_factory) -> None:
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-demo"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=RecordingRunner(),
    )

    demo = create_demo_components(runtime=runtime, session_factory=session_factory)

    assert demo.runtime is runtime
    assert demo.session_factory is session_factory
    assert demo.app.extensions["runtime_container"] is runtime
    assert demo.app.extensions["session_factory"] is session_factory
    assert demo.intake_worker.tracker is runtime.tracker
    assert demo.intake_worker.scm is runtime.scm
    assert demo.intake_worker.session_factory is session_factory
    assert demo.execute_worker.scm is runtime.scm
    assert demo.execute_worker.agent_runner is runtime.agent_runner
    assert demo.execute_worker.session_factory is session_factory
    assert demo.deliver_worker.tracker is runtime.tracker
    assert demo.deliver_worker.session_factory is session_factory


def test_demo_components_run_shared_http_intake_flow(session_factory, tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    runner = RecordingRunner()
    runtime = RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-demo"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=runner,
    )
    demo = create_demo_components(runtime=runtime, session_factory=session_factory)

    response = demo.app.test_client().post(
        "/tasks/intake",
        json={
            "context": {"title": "Demo flow"},
            "input_payload": {
                "instructions": "Run demo flow.",
                "branch_name": "task51/demo-flow",
                "base_branch": "main",
            },
            "repo_url": str(repo_dir),
            "repo_ref": "main",
            "workspace_key": "demo-repo",
        },
    )

    assert response.status_code == 201

    intake_report = demo.intake_worker.poll_once()
    triage_execute_report = demo.execute_worker.poll_once()
    impl_execute_report = demo.execute_worker.poll_once()
    deliver_triage_report = demo.deliver_worker.poll_once()
    deliver_impl_report = demo.deliver_worker.poll_once()

    assert intake_report.created_fetch_tasks == 1
    assert intake_report.created_execute_tasks == 1
    assert triage_execute_report.processed_execute_tasks == 1
    assert impl_execute_report.processed_execute_tasks == 1
    assert deliver_triage_report.processed_deliver_tasks == 1
    assert deliver_impl_report.processed_deliver_tasks == 1
    # Two runner invocations: triage + impl.
    assert len(runner.requests) == 2
    # Both runs target the workspace_key 'demo-repo'. On platforms where the
    # MockScm can resolve the local repo path it surfaces ``repo_dir.resolve()``;
    # otherwise it falls back to ``/tmp/mock-scm/<workspace_key>``. We accept
    # either, but they must be the same for both runs.
    expected_paths = {str(repo_dir.resolve()), "/tmp/mock-scm/demo-repo"}
    assert runner.requests[0].workspace_path in expected_paths
    assert runner.requests[1].workspace_path == runner.requests[0].workspace_path

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id="task-1",
        )

        assert fetch_task is not None
        triage_task = repository.find_child_task(
            parent_id=fetch_task.id,
            task_type=TaskType.EXECUTE,
        )
        assert triage_task is not None
        execute_task = repository.find_implementation_execute_for_root(fetch_task.id)
        assert execute_task is not None
        deliver_task = repository.find_child_task(
            parent_id=execute_task.id,
            task_type=TaskType.DELIVER,
        )

        assert deliver_task is not None
        assert triage_task.status == TaskStatus.DONE
        assert execute_task.status == TaskStatus.DONE
        assert deliver_task.status == TaskStatus.DONE

    assert runtime.tracker._tasks["task-1"].status == TaskStatus.DONE


def test_demo_main_delegates_to_run_demo(monkeypatch) -> None:
    called = {"count": 0}

    def fake_run_demo() -> None:
        called["count"] += 1

    monkeypatch.setattr("backend.demo.run_demo", fake_run_demo)

    main()

    assert called["count"] == 1
