"""End-to-end smoke test of the re-triage protocol (task18c).

The scenario walks one tracker task through a complete re-triage cycle:

1. First intake → triage SP=5 escalation (RFI). No impl execute, no SCM
   side-effects. Tracker receives the RFI comment and the SP=5 estimate.
2. User edits the description on the tracker side.
3. Next intake → re-triage execute created with the fresh context.
4. Triage SP=2 → sibling impl execute + handover brief → impl runs to DONE
   with branch + PR; both deliver tasks complete.

The test deliberately runs against the in-memory MockTracker / MockScm stack
so it covers the orchestrator wiring without external dependencies.
"""

from __future__ import annotations

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.repositories.task_repository import TaskRepository
from backend.schemas import (
    TaskContext,
    TaskInputPayload,
    TaskResultPayload,
    TrackerTaskCreatePayload,
)
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
    "### 1. Intent\n- smoke triage stub\n"
)

_RFI_BODY_SP5 = (
    "## RFI\n\n"
    "Need clarification on the desired behaviour.\n"
)


def _envelope(*, sp: int, task_kind: str, outcome: str, body: str) -> str:
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


class _ScriptedRunner:
    """Action-aware runner: emits SP=5 envelope first, SP=2 second; impl is
    a normal payload."""

    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []
        self._triage_calls = 0

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        action = (
            request.task_context.current_task.input_payload.action
            if request.task_context.current_task.input_payload is not None
            else None
        )
        if action == "triage":
            self._triage_calls += 1
            if self._triage_calls == 1:
                stdout = _envelope(
                    sp=5,
                    task_kind="research",
                    outcome="needs_clarification",
                    body=_RFI_BODY_SP5,
                )
            else:
                stdout = _envelope(
                    sp=2,
                    task_kind="implementation",
                    outcome="routed",
                    body=_BRIEF_BODY_SP2,
                )
            return AgentRunResult(
                payload=TaskResultPayload(summary="triage stub"),
                raw_stdout=stdout,
                raw_stderr="",
            )

        return AgentRunResult(
            payload=TaskResultPayload(
                summary="impl finished",
                details="smoke impl details",
                tracker_comment="Implementation merged.",
            ),
            raw_stdout="",
            raw_stderr="",
        )


def test_retriage_cycle_smoke(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    runner = _ScriptedRunner()

    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Re-triage smoke",
                description="Initial vague description.",
                acceptance_criteria=["Eventually deliver the change"],
            ),
            input_payload=TaskInputPayload(
                instructions="Implement after triage.",
                base_branch="main",
                branch_name="task-smoke/retriage",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-smoke",
        )
    )

    intake_worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )
    execute_worker = ExecuteWorker(
        scm=scm,
        agent_runner=runner,
        session_factory=session_factory,
    )
    deliver_worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    # ---------- Cycle 1: SP=5 escalation ----------
    intake_worker.poll_once()
    execute_worker.poll_once()
    deliver_worker.poll_once()

    # Tracker has the RFI comment; status remains NEW; no SCM artifacts.
    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.NEW
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body.startswith("## RFI")
    assert scm._branches == {}
    assert scm._pull_requests == {}

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=tracker_task.external_id
        )
        assert fetch_task is not None
        # Single execute (the triage) under fetch.
        executes = (
            session.query(Task)
            .filter(Task.parent_id == fetch_task.id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        assert len(executes) == 1
        assert executes[0].input_payload["action"] == "triage"
        assert executes[0].status == TaskStatus.DONE

    # ---------- User edits the description on the tracker side ----------
    tracker._tasks[tracker_task.external_id].context.description = (
        "Add detailed logging hook to the API layer."
    )

    # ---------- Cycle 2: re-triage SP=2 → sibling impl + impl run ----------
    intake_worker.poll_once()
    # Two execute polls: re-triage, then sibling impl.
    execute_worker.poll_once()
    execute_worker.poll_once()
    # Two deliver polls: deliver_triage (fresh) + deliver_impl.
    deliver_worker.poll_once()
    deliver_worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=tracker_task.external_id
        )
        assert fetch_task is not None

        executes = (
            session.query(Task)
            .filter(Task.parent_id == fetch_task.id, Task.task_type == TaskType.EXECUTE)
            .order_by(Task.id.asc())
            .all()
        )
        # Original triage (SP=5 DONE) + new triage (SP=2 DONE) + impl (DONE).
        assert len(executes) == 3
        assert executes[0].input_payload["action"] == "triage"
        assert executes[1].input_payload["action"] == "triage"
        assert executes[2].input_payload["action"] == "implementation"
        assert all(e.status == TaskStatus.DONE for e in executes)

        impl = repository.find_implementation_execute_for_root(fetch_task.id)
        assert impl is not None
        assert impl.branch_name == "task-smoke/retriage"
        assert impl.pr_external_id is not None
        assert impl.pr_url is not None

        # Each triage and impl has its own deliver row.
        deliver_under_triage_1 = repository.find_child_task(
            parent_id=executes[0].id, task_type=TaskType.DELIVER
        )
        deliver_under_triage_2 = repository.find_child_task(
            parent_id=executes[1].id, task_type=TaskType.DELIVER
        )
        deliver_under_impl = repository.find_child_task(
            parent_id=impl.id, task_type=TaskType.DELIVER
        )
        assert deliver_under_triage_1.status == TaskStatus.DONE
        assert deliver_under_triage_2.status == TaskStatus.DONE
        assert deliver_under_impl.status == TaskStatus.DONE

    # Final tracker state: pipeline complete via deliver_impl.
    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    # Comments accumulated: RFI + SP=2 triage line + impl summary = 3.
    assert len(tracker._comments[tracker_task.external_id]) == 3
    assert tracker._comments[tracker_task.external_id][0].body.startswith("## RFI")
    assert "Brief сохранён" in tracker._comments[tracker_task.external_id][1].body
    assert (
        tracker._comments[tracker_task.external_id][2].body
        == "Implementation merged."
    )
