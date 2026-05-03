"""Integration scenarios for the triage pipeline (task11 §2).

Covers the four scenarios described in
``temp/plans/triage-story-point-agent.md`` §8.2:

* Scenario A — SP=2 happy path: triage → DONE, sibling impl-execute created,
  deliver under triage with SP=2 estimate and ``triage:ready`` label.
* Scenario B — SP=5 RFI: triage → DONE, no sibling impl-execute, deliver under
  triage with RFI escalation, no ``update_status`` (tracker_status is None).
* Scenario C — SP=13 system_design: same shape as B with ``triage:block`` and
  ``escalation_kind="system_design"``.
* Scenario D — Idempotency: a second triage in the same cluster MUST NOT
  duplicate the existing sibling impl-execute and logs the idempotent skip.
"""

from __future__ import annotations

from backend.adapters.mock_scm import MockScm
from backend.db import session_scope
from backend.models import Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.task_constants import TaskStatus, TaskType
from backend.workers.execute_worker import ExecuteWorker
from test_execute_worker_triage_dispatch import (
    _HANDOVER_BRIEF_BODY,
    _build_session_factory,
    _build_settings,
    _create_fetch,
    _envelope,
    _FakeAgentRunner,
)

# ---------------------------------------------------------------------------
# Scenario A — SP=2 happy path → sibling impl + deliver(triage)
# ---------------------------------------------------------------------------


def test_scenario_a_sp2_creates_sibling_impl_and_deliver_triage(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=2,
            task_kind="implementation",
            outcome="routed",
            markdown_body=_HANDOVER_BRIEF_BODY,
        )
    )
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=fake,
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="A")
        triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-A",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-A",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage.id
        fetch_id = fetch.id

    report = worker.poll_once()
    assert report.processed_execute_tasks == 1
    assert report.failed_execute_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        triage_row = session.get(Task, triage_id)
        assert triage_row is not None
        assert triage_row.status == TaskStatus.DONE

        cluster = (
            session.query(Task)
            .filter(Task.root_id == fetch_id)
            .order_by(Task.id.asc())
            .all()
        )
        # fetch + triage + sibling impl + deliver(triage) = 4 tasks
        assert len(cluster) == 4

        sibling = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .one()
        )
        assert sibling.status == TaskStatus.NEW
        sibling_payload = sibling.input_payload
        assert isinstance(sibling_payload, dict)
        assert sibling_payload["action"] == "implementation"
        handoff = sibling_payload["handoff"]
        assert handoff["from_task_id"] == triage_id
        assert handoff["from_role"] == "triage"
        assert isinstance(handoff["brief_markdown"], str)
        assert handoff["brief_markdown"].startswith("## Agent Handover Brief")

        deliver = (
            session.query(Task)
            .filter(Task.parent_id == triage_id, Task.task_type == TaskType.DELIVER)
            .one()
        )
        assert deliver.status == TaskStatus.NEW

        delivery = triage_row.result_payload["delivery"]
        assert delivery["tracker_estimate"] == 2
        assert delivery["tracker_status"] is None
        assert delivery["tracker_labels"] == ["sp:2", "triage:ready"]
        assert delivery["escalation_kind"] is None


# ---------------------------------------------------------------------------
# Scenario B — SP=5 RFI → only deliver(triage), no sibling impl
# ---------------------------------------------------------------------------


_RFI_BODY = "## RFI\n\nNeed clarification.\n"


def test_scenario_b_sp5_rfi_blocks_sibling_creation(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=5,
            task_kind="research",
            outcome="needs_clarification",
            markdown_body=_RFI_BODY,
        )
    )
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=fake,
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="B")
        triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-B",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-B",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage.id
        fetch_id = fetch.id

    report = worker.poll_once()
    assert report.processed_execute_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        triage_row = session.get(Task, triage_id)
        assert triage_row is not None
        assert triage_row.status == TaskStatus.DONE

        # sibling impl-execute NOT created
        assert repository.find_implementation_execute_for_root(fetch_id) is None

        cluster_executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        assert len(cluster_executes) == 1
        assert cluster_executes[0].id == triage_id

        deliver = (
            session.query(Task)
            .filter(Task.parent_id == triage_id, Task.task_type == TaskType.DELIVER)
            .one()
        )
        assert deliver.status == TaskStatus.NEW

        delivery = triage_row.result_payload["delivery"]
        assert delivery["tracker_estimate"] == 5
        assert delivery["tracker_status"] is None
        assert delivery["tracker_labels"] == ["sp:5", "triage:rfi"]
        assert delivery["escalation_kind"] == "rfi"
        assert isinstance(delivery["comment_body"], str)
        assert delivery["comment_body"].startswith("## RFI")


# ---------------------------------------------------------------------------
# Scenario C — SP=13 system_design → escalation, no sibling
# ---------------------------------------------------------------------------


_SYSTEM_DESIGN_BODY = "## Needs System Design\n\nArchitectural review required.\n"


def test_scenario_c_sp13_system_design(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=13,
            task_kind="implementation",
            outcome="blocked",
            markdown_body=_SYSTEM_DESIGN_BODY,
        )
    )
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=fake,
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="C")
        triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-C",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-C",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage.id
        fetch_id = fetch.id

    report = worker.poll_once()
    assert report.processed_execute_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        triage_row = session.get(Task, triage_id)
        assert triage_row is not None
        assert triage_row.status == TaskStatus.DONE
        assert repository.find_implementation_execute_for_root(fetch_id) is None

        delivery = triage_row.result_payload["delivery"]
        assert delivery["tracker_estimate"] == 13
        assert delivery["tracker_labels"] == ["sp:13", "triage:block"]
        assert delivery["escalation_kind"] == "system_design"
        assert delivery["tracker_status"] is None
        assert isinstance(delivery["comment_body"], str)
        assert delivery["comment_body"].startswith("## Needs System Design")


# ---------------------------------------------------------------------------
# Scenario D — Idempotency: re-triage with existing sibling impl
# ---------------------------------------------------------------------------


def test_scenario_d_idempotency_does_not_duplicate_sibling_impl(tmp_path, caplog) -> None:
    """Second triage processed under the same cluster — sibling impl-execute
    must remain unique (one per ``root_id``).
    """

    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=2,
            task_kind="implementation",
            outcome="routed",
            markdown_body=_HANDOVER_BRIEF_BODY,
        )
    )
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=fake,
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="D")
        prior_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-D",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-D",
                context={"title": "Earlier triage"},
                input_payload={"action": "triage"},
            )
        )
        existing_impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.NEW,
                tracker_name="mock",
                external_parent_id="TASK-D",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-D",
                context={"title": "Existing impl"},
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": prior_triage.id,
                        "from_role": "triage",
                        "brief_markdown": "PRIOR-BRIEF",
                    },
                },
            )
        )
        existing_impl_id = existing_impl.id
        # Mark existing impl PROCESSING so poll_task picks the re-triage first.
        new_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-D",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-D",
                context={"title": "Re-triage"},
                input_payload={"action": "triage"},
            )
        )
        new_triage_id = new_triage.id
        fetch_id = fetch.id

    with session_scope(session_factory=session_factory) as session:
        impl = session.get(Task, existing_impl_id)
        assert impl is not None
        impl.status = TaskStatus.PROCESSING

    with caplog.at_level("INFO"):
        worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        new_row = session.get(Task, new_triage_id)
        assert new_row is not None
        assert new_row.status == TaskStatus.DONE

        impl_for_root = repository.find_implementation_execute_for_root(fetch_id)
        assert impl_for_root is not None
        assert impl_for_root.id == existing_impl_id

        # Cluster: fetch + 2 triage + 1 impl + 1 deliver(new triage)
        impl_count = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .count()
        )
        # 2 triage + 1 impl = 3 EXECUTE rows; no fourth.
        assert impl_count == 3

    skip_messages = [
        record
        for record in caplog.records
        if "sibling_implementation_execute_skipped_idempotent" in record.getMessage()
    ]
    assert skip_messages, "expected idempotent skip log event"
