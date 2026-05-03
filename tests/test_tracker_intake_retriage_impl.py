"""Re-triage scenarios for impl-state handling and reopen detection (task18b).

The plan §6.7a + §8.2 specifies these scenarios:

* G — user edit during impl PROCESSING (no re-triage; in-flight, edits go via PR feedback);
* G2 — user edit while impl is pending NEW (impl marked superseded, new triage created);
* K — DONE impl + reopen + edit → new triage with consumed marker;
* K0 — reopen-only without any edit → new triage (CC1);
* K0b — after K0 + escalation → next poll no-op (DD1 self-loop guard);
* K0c — new completed pipeline → reopen for that pipeline allowed again;
* K0d — impl DONE + deliver_impl NEW (race window) → no false reopen (EE1);
* K0d2 — same race + user edit → still no new triage (EE2);
* K2 — DONE impl + tracker_status != NEW → no re-triage;
* K3 — reopen → impl2 NEW + repeated edit → impl2 superseded + triage3 (AA1).

These tests deliberately use ``_ingest_tracker_task`` directly (rather than
``poll_once``) when they need to control ``tracker_task.status`` independently
of the MockTracker fetch-status filter — e.g. K2 explicitly exercises an
intake that the production poll would never deliver.
"""

from __future__ import annotations

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskContext, TrackerTaskCreatePayload
from backend.services.user_content_hash import compute_user_content_hash
from backend.task_constants import TaskStatus, TaskType
from backend.workers.tracker_intake import TrackerIntakeWorker


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _make_worker(tracker, session_factory):
    return TrackerIntakeWorker(
        tracker=tracker,
        scm=MockScm(),
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )


def _seed_done_triage_with_impl(
    *,
    repository: TaskRepository,
    fetch_id: int,
    impl_status: TaskStatus,
    triage_escalation_kind: str | None = None,
) -> tuple[Task, Task]:
    """Helper: create a DONE triage execute + impl execute under fetch.

    ``triage_escalation_kind=None`` → SP=2-style triage with brief.
    ``triage_escalation_kind in {"rfi","decomposition","system_design"}`` →
    escalation triage; impl is then NOT created and impl_status is ignored
    (caller must skip impl creation in that case).
    """
    triage = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=fetch_id,
            status=TaskStatus.DONE,
            input_payload={"action": "triage"},
            result_payload={
                "schema_version": 1,
                "outcome": "routed"
                if triage_escalation_kind is None
                else "needs_clarification",
                "summary": "triage done",
                "metadata": {"handover_brief": "## Agent Handover Brief\nbody"}
                if triage_escalation_kind is None
                else {},
                "delivery": {
                    "tracker_estimate": 2 if triage_escalation_kind is None else 5,
                    "tracker_status": None,
                    "tracker_labels": (
                        ["sp:2", "triage:ready"]
                        if triage_escalation_kind is None
                        else ["sp:5", "triage:rfi"]
                    ),
                    "escalation_kind": triage_escalation_kind,
                    "comment_body": "ok",
                },
            },
        )
    )
    if triage_escalation_kind is not None:
        return triage, None  # type: ignore[return-value]

    impl = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=fetch_id,
            status=impl_status,
            input_payload={
                "action": "implementation",
                "handoff": {
                    "from_task_id": triage.id,
                    "from_role": "triage",
                    "brief_markdown": "## Agent Handover Brief\nbody",
                },
            },
        )
    )
    return triage, impl


def _seed_deliver(
    *,
    repository: TaskRepository,
    parent_execute: Task,
    status: TaskStatus,
) -> Task:
    return repository.create_task(
        TaskCreateParams(
            task_type=TaskType.DELIVER,
            parent_id=parent_execute.id,
            status=status,
        )
    )


# ---------------------------------------------------------------------------
# Scenario G — user edit during impl PROCESSING → no new triage
# ---------------------------------------------------------------------------


def test_scenario_g_user_edit_during_processing_impl_no_retriage(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        # Mark first triage DONE, create PROCESSING impl.
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "triage done",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.PROCESSING,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        fetch_id = fetch.id

    tracker._tasks[created.external_id].context.description = "edited during impl"
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        # No new triage created. Cluster remains: triage(DONE) + impl(PROCESSING).
        assert len(executes) == 2
        actions = sorted(t.input_payload["action"] for t in executes)
        assert actions == ["implementation", "triage"]
        # fetch.context refreshed with new description.
        fetch = session.get(Task, fetch_id)
        assert fetch.context["description"] == "edited during impl"


# ---------------------------------------------------------------------------
# Scenario G2 — user edit while impl pending NEW → impl FAILED + new triage
# ---------------------------------------------------------------------------


def test_scenario_g2_user_edit_with_pending_impl_supersedes_and_retriages(
    session_factory,
) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "triage done",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        triage_id = triage.id
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.NEW,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        impl_id = impl.id
        fetch_id = fetch.id

    tracker._tasks[created.external_id].context.description = "edited before impl start"
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        impl_row = session.get(Task, impl_id)
        assert impl_row.status == TaskStatus.FAILED
        assert impl_row.error == f"superseded_by_user_edit_after_triage_{triage_id}"
        assert impl_row.result_payload["metadata"]["superseded_reason"] == "user_edit"

        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .order_by(Task.id.asc())
            .all()
        )
        # triage(DONE) + impl(FAILED) + new triage(NEW) = 3 rows.
        assert len(executes) == 3
        new_triage = executes[-1]
        assert new_triage.input_payload["action"] == "triage"
        assert new_triage.status == TaskStatus.NEW
        assert new_triage.context["description"] == "edited before impl start"


# ---------------------------------------------------------------------------
# Scenario K — done impl + reopen + edit → new triage
# ---------------------------------------------------------------------------


def test_scenario_k_reopen_with_edit_creates_new_triage(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        # Replace pending triage with DONE triage + DONE impl + DONE deliver_impl.
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "triage",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl, status=TaskStatus.DONE)
        fetch_id = fetch.id
        impl_id = impl.id

    # User edits + tracker reopen (status → NEW).
    tracker._tasks[created.external_id].context.description = "reopen edit"
    tracker._tasks[created.external_id].status = TaskStatus.NEW
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .order_by(Task.id.asc())
            .all()
        )
        # original triage + impl + new triage = 3 EXECUTE rows.
        assert len(executes) == 3
        new_triage = executes[-1]
        assert new_triage.input_payload["action"] == "triage"
        assert new_triage.context["description"] == "reopen edit"

        # Old DONE impl untouched.
        assert session.get(Task, impl_id).status == TaskStatus.DONE

        # Reopen consumed marker recorded.
        fetch = session.get(Task, fetch_id)
        assert (
            fetch.context["metadata"]["last_reopen_consumed_done_impl_id"] == impl_id
        )


# ---------------------------------------------------------------------------
# Scenario K0 — reopen-only without edit → new triage; consumed marker
# ---------------------------------------------------------------------------


def test_scenario_k0_reopen_only_without_edit_creates_new_triage(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="static"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "triage",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl, status=TaskStatus.DONE)
        fetch_id = fetch.id
        impl_id = impl.id

    # Reopen WITHOUT editing the description.
    tracker._tasks[created.external_id].status = TaskStatus.NEW
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .order_by(Task.id.asc())
            .all()
        )
        # Original triage + impl + NEW triage from reopen.
        assert len(executes) == 3
        assert executes[-1].input_payload["action"] == "triage"
        fetch = session.get(Task, fetch_id)
        assert (
            fetch.context["metadata"]["last_reopen_consumed_done_impl_id"] == impl_id
        )
        # hash updated to incoming hash (no edit, but stored on refresh).
        assert "last_triage_user_content_hash" in fetch.context["metadata"]


# ---------------------------------------------------------------------------
# Scenario K0b — reopen-only loop prevention after escalation
# ---------------------------------------------------------------------------


def test_scenario_k0b_reopen_consumed_blocks_self_loop(session_factory) -> None:
    """After K0 → triage SP=5 (escalation), the next poll without edits must
    NOT create another triage (DD1 self-loop guard via consumed marker)."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="static"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage1 = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage1.status = TaskStatus.DONE
        triage1.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t1",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl1 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage1.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl1, status=TaskStatus.DONE)
        fetch_id = fetch.id
        impl1_id = impl1.id

    # Reopen → triage2 created.
    tracker._tasks[created.external_id].status = TaskStatus.NEW
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage2 = repository.find_pending_triage_execute(parent_id=fetch.id)
        # Mark triage2 as escalation SP=5 (no impl follow-up).
        triage2.status = TaskStatus.DONE
        triage2.result_payload = {
            "schema_version": 1,
            "outcome": "needs_clarification",
            "summary": "t2 escalation",
            "metadata": {},
            "delivery": {
                "tracker_estimate": 5,
                "tracker_status": None,
                "tracker_labels": ["sp:5", "triage:rfi"],
                "escalation_kind": "rfi",
                "comment_body": "RFI",
            },
        }

    # Next poll WITHOUT any edit. Should be no-op (consumed marker blocks reopen).
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        # impl1, triage1 (DONE), triage2 (DONE) = 3. No triage3 created.
        assert len(executes) == 3
        fetch = session.get(Task, fetch_id)
        # consumed marker still pinned to impl1 (no new pipeline yet).
        assert (
            fetch.context["metadata"]["last_reopen_consumed_done_impl_id"] == impl1_id
        )


# ---------------------------------------------------------------------------
# Scenario K0c — new pipeline after consumed reopen unlocks future reopen
# ---------------------------------------------------------------------------


def test_scenario_k0c_new_pipeline_unlocks_future_reopen(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    # Build a "consumed reopen" state: impl1 DONE + deliver1 DONE +
    # marker pinned to impl1.id; then add a fresh impl2 DONE + deliver2 DONE
    # and verify another reopen creates triage3.
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage1 = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage1.status = TaskStatus.DONE
        triage1.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t1",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl1 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage1.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl1, status=TaskStatus.DONE)

        # Inject consumed marker pinned to impl1.
        ctx = dict(fetch.context)
        meta = dict(ctx["metadata"])
        meta["last_reopen_consumed_done_impl_id"] = impl1.id
        ctx["metadata"] = meta
        fetch.context = ctx
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(fetch, "context")

        # Build fresh impl2 + deliver2 DONE.
        triage2 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={"action": "triage"},
                result_payload={
                    "schema_version": 1,
                    "outcome": "routed",
                    "summary": "t2",
                    "metadata": {"handover_brief": "B2"},
                    "delivery": {
                        "tracker_estimate": 2,
                        "tracker_status": None,
                        "tracker_labels": ["sp:2", "triage:ready"],
                        "escalation_kind": None,
                        "comment_body": "ok",
                    },
                },
            )
        )
        impl2 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage2.id,
                        "from_role": "triage",
                        "brief_markdown": "B2",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl2, status=TaskStatus.DONE)
        fetch_id = fetch.id
        impl2_id = impl2.id

    # New reopen: tracker.status NEW, no edit.
    tracker._tasks[created.external_id].status = TaskStatus.NEW
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = session.get(Task, fetch_id)
        # consumed marker now points to impl2 — new triage created.
        assert (
            fetch.context["metadata"]["last_reopen_consumed_done_impl_id"] == impl2_id
        )
        # NEW triage created under fetch.
        new_triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        assert new_triage is not None


# ---------------------------------------------------------------------------
# Scenario K0d — false reopen guard: impl DONE + deliver_impl NEW (race)
# ---------------------------------------------------------------------------


def test_scenario_k0d_no_false_reopen_during_deliver_window(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="static"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        # deliver_impl pending NEW (race window — not yet DONE).
        _seed_deliver(repository=repository, parent_execute=impl, status=TaskStatus.NEW)
        fetch_id = fetch.id

    # tracker.status remains NEW (initial state — Linear status not yet bumped by
    # deliver_impl). Poll WITHOUT edit. Must NOT create new triage.
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        # triage(DONE) + impl(DONE) = 2. No triage from false reopen.
        assert len(executes) == 2


# ---------------------------------------------------------------------------
# Scenario K0d2 — same race + user edit → still no new triage
# ---------------------------------------------------------------------------


def test_scenario_k0d2_user_edit_during_deliver_window_no_triage(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl, status=TaskStatus.NEW)
        fetch_id = fetch.id

    # User edit during deliver-window. tracker.status still NEW.
    tracker._tasks[created.external_id].context.description = "edit during window"
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        # Edit was captured (fetch.context refreshed) BUT no new triage was created.
        assert len(executes) == 2
        fetch = session.get(Task, fetch_id)
        assert fetch.context["description"] == "edit during window"
        # Hash updated to the new value (no PROCESSING triage).
        new_hash = compute_user_content_hash(tracker._tasks[created.external_id])
        assert fetch.context["metadata"]["last_triage_user_content_hash"] == new_hash


# ---------------------------------------------------------------------------
# Scenario K2 — DONE impl + tracker_status != NEW → no re-triage
# ---------------------------------------------------------------------------


def test_scenario_k2_done_impl_without_reopen_does_not_retriage(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="static"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage.status = TaskStatus.DONE
        triage.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t",
            "metadata": {"handover_brief": "B"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage.id,
                        "from_role": "triage",
                        "brief_markdown": "B",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl, status=TaskStatus.DONE)
        fetch_id = fetch.id

    # Tracker is in DONE — pipeline complete, no reopen. Synthetic intake bypasses
    # MockTracker.fetch_tasks (which would filter NEW only).
    tracker._tasks[created.external_id].status = TaskStatus.DONE
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        worker._ingest_tracker_task(
            repository=repository, tracker_task=tracker._tasks[created.external_id]
        )

    with session_scope(session_factory=session_factory) as session:
        executes = (
            session.query(Task)
            .filter(Task.root_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .all()
        )
        # triage + impl = 2. No new triage.
        assert len(executes) == 2


# ---------------------------------------------------------------------------
# Scenario K3 — reopen + repeated edit → impl2 superseded, triage3
# ---------------------------------------------------------------------------


def test_scenario_k3_reopen_then_repeated_edit_supersedes_pending_impl(
    session_factory,
) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    # Pipeline 1 complete: triage1 DONE + impl1 DONE + deliver1 DONE.
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage1 = repository.find_pending_triage_execute(parent_id=fetch.id)
        triage1.status = TaskStatus.DONE
        triage1.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t1",
            "metadata": {"handover_brief": "B1"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        impl1 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage1.id,
                        "from_role": "triage",
                        "brief_markdown": "B1",
                    },
                },
            )
        )
        _seed_deliver(repository=repository, parent_execute=impl1, status=TaskStatus.DONE)
        fetch_id = fetch.id
        impl1_id = impl1.id

    # User reopens → triage2.
    tracker._tasks[created.external_id].status = TaskStatus.NEW
    tracker._tasks[created.external_id].context.description = "reopen edit"
    worker.poll_once()

    # Mark triage2 DONE and create impl2 NEW (from triage2's routing).
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        triage2 = repository.find_pending_triage_execute(parent_id=fetch_id)
        triage2.status = TaskStatus.DONE
        triage2.result_payload = {
            "schema_version": 1,
            "outcome": "routed",
            "summary": "t2",
            "metadata": {"handover_brief": "B2"},
            "delivery": {
                "tracker_estimate": 2,
                "tracker_status": None,
                "tracker_labels": ["sp:2", "triage:ready"],
                "escalation_kind": None,
                "comment_body": "ok",
            },
        }
        triage2_id = triage2.id
        impl2 = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_id,
                status=TaskStatus.NEW,
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage2.id,
                        "from_role": "triage",
                        "brief_markdown": "B2",
                    },
                },
            )
        )
        impl2_id = impl2.id

    # User edits AGAIN before impl2 starts. Must supersede impl2 + create triage3.
    tracker._tasks[created.external_id].context.description = "second edit"
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        impl2_row = session.get(Task, impl2_id)
        assert impl2_row.status == TaskStatus.FAILED
        assert impl2_row.error == f"superseded_by_user_edit_after_triage_{triage2_id}"

        # Old impl1 untouched.
        assert session.get(Task, impl1_id).status == TaskStatus.DONE

        repository = TaskRepository(session)
        triage3 = repository.find_pending_triage_execute(parent_id=fetch_id)
        assert triage3 is not None
        assert triage3.context["description"] == "second edit"
