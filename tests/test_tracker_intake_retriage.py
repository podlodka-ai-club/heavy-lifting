"""Re-triage detection tests for ``TrackerIntakeWorker`` (task18a §6.7a).

Scope of task18a:

* the worker must store ``last_triage_user_content_hash`` on the fetch task
  on first intake;
* on subsequent intake of the same external task, the worker must compare
  the incoming hash with the stored one and:
  - leave fetch.context untouched on idempotent polls (no user edit, no
    own-write effect);
  - refresh fetch.context wholesale when a user edit is detected, including
    references that were not previously known;
  - only update the stored hash when no triage execute is currently
    ``PROCESSING`` (so a user edit during an in-flight triage is not lost
    after the triage finishes);
  - update the context of a pending ``NEW`` triage execute too, so the
    worker picks up the latest user-authored fields when it eventually
    runs.

Out of scope (task18b): creating a new triage execute on user edit,
superseding pending implementation execute, reopen detection. Those scenarios
remain for ``test_tracker_intake_retriage_impl.py``.
"""

from __future__ import annotations

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.repositories.task_repository import TaskRepository
from backend.schemas import (
    TaskContext,
    TaskInputPayload,
    TaskLink,
    TrackerLinksAttachPayload,
    TrackerTaskCreatePayload,
)
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


def _read_fetch_context(session_factory, external_task_id: str):
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=external_task_id
        )
        assert fetch_task is not None
        # Detach a deep copy so callers can safely diff across multiple
        # transactions without re-querying.
        return dict(fetch_task.context or {}), fetch_task.id


def test_first_intake_stores_initial_hash(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="initial title"))
    )
    worker = _make_worker(tracker, session_factory)

    worker.poll_once()

    fetch_context, _ = _read_fetch_context(session_factory, created.external_id)
    incoming_hash = compute_user_content_hash(tracker._tasks[created.external_id])
    assert fetch_context["metadata"]["last_triage_user_content_hash"] == incoming_hash


def test_repeated_poll_is_noop_on_unchanged_content(session_factory) -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="static"))
    )
    worker = _make_worker(tracker, session_factory)

    worker.poll_once()
    before, _ = _read_fetch_context(session_factory, created.external_id)
    worker.poll_once()
    after, _ = _read_fetch_context(session_factory, created.external_id)

    assert before == after


def test_own_write_attach_links_does_not_trigger_refresh(session_factory) -> None:
    """Scenario E: own-write `attach_links` must not invalidate the hash.

    Our adapters mark these attachments with ``origin='own_write'`` and the
    hash function excludes them, so the next poll sees the same hash.
    """

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="task with own writes"))
    )
    worker = _make_worker(tracker, session_factory)

    worker.poll_once()
    before, fetch_id = _read_fetch_context(session_factory, created.external_id)

    tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id=created.external_id,
            links=[
                TaskLink(label="branch", url="https://example/branch"),
                TaskLink(label="pull_request", url="https://example/pr/1"),
            ],
        )
    )

    worker.poll_once()
    after, _ = _read_fetch_context(session_factory, created.external_id)

    assert before["metadata"] == after["metadata"]
    # references on fetch.context should NOT be back-filled by own-writes —
    # fetch.context only changes on actual user edits.
    assert before["references"] == after["references"]


def test_user_added_user_reference_triggers_refresh(session_factory) -> None:
    """Scenario E3 (X1): a user-added reference invalidates the hash.

    The reference goes directly into the tracker task without ``own_write``
    provenance, so it participates in the hash and the next poll refreshes
    fetch.context wholesale, including the new reference.
    """

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="task A"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    new_link = TaskLink(label="spec", url="https://x/spec", origin="user")
    tracker._tasks[created.external_id].context.references.append(new_link)

    worker.poll_once()
    fetch_context, _ = _read_fetch_context(session_factory, created.external_id)

    assert any(ref["url"] == "https://x/spec" for ref in fetch_context["references"])


def test_user_added_collision_label_triggers_refresh(session_factory) -> None:
    """Scenario E4 (Y1): user-added reference whose label collides with our
    own-write convention (``pull_request``) still participates in the hash
    because its provenance is ``user``."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="task A"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    collision = TaskLink(
        label="pull_request",
        url="https://attacker/file",
        origin="user",
    )
    tracker._tasks[created.external_id].context.references.append(collision)

    worker.poll_once()
    fetch_context, _ = _read_fetch_context(session_factory, created.external_id)

    assert any(
        ref["url"] == "https://attacker/file" for ref in fetch_context["references"]
    )


def test_user_edit_description_refreshes_fetch_context_and_hash(session_factory) -> None:
    """Scenario F: a user edit of ``description`` is the canonical case."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="t", description="initial description"),
            input_payload=TaskInputPayload(instructions="x"),
        )
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    tracker._tasks[created.external_id].context.description = "edited description"

    worker.poll_once()

    fetch_context, fetch_id = _read_fetch_context(session_factory, created.external_id)
    assert fetch_context["description"] == "edited description"
    new_hash = compute_user_content_hash(tracker._tasks[created.external_id])
    assert fetch_context["metadata"]["last_triage_user_content_hash"] == new_hash

    # task18a contract: NO new triage execute is created on this slice.
    from backend.models import Task

    with session_scope(session_factory=session_factory) as session:
        execute_count = (
            session.query(Task)
            .filter(Task.parent_id == fetch_id, Task.task_type == TaskType.EXECUTE)
            .count()
        )
        assert execute_count == 1


def test_user_edit_during_processing_triage_keeps_hash_stale(session_factory) -> None:
    """Scenario I: a user edit while a triage execute is ``PROCESSING``
    refreshes fetch.context but leaves ``last_triage_user_content_hash``
    untouched, so the very next poll after the triage finishes still sees the
    edit as a change and (in task18b) creates a fresh triage."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    initial_hash = compute_user_content_hash(tracker._tasks[created.external_id])

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        triage = repository.find_pending_triage_execute(
            parent_id=repository.find_fetch_task_by_tracker_task(
                tracker_name="mock", external_task_id=created.external_id
            ).id
        )
        assert triage is not None
        triage.status = TaskStatus.PROCESSING

    tracker._tasks[created.external_id].context.description = "edited mid-flight"

    worker.poll_once()

    fetch_context, _ = _read_fetch_context(session_factory, created.external_id)
    # Context refreshed (hash detection trigger).
    assert fetch_context["description"] == "edited mid-flight"
    # Hash NOT bumped because PROCESSING triage hasn't finished yet.
    assert fetch_context["metadata"]["last_triage_user_content_hash"] == initial_hash


def test_user_edit_with_pending_triage_updates_pending_context(session_factory) -> None:
    """Scenario H (pending NEW triage refresh): ``pending_triage.context``
    is rewritten so the worker picks up the latest tracker fields when it
    eventually runs."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t", description="initial"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    tracker._tasks[created.external_id].context.description = "edited"
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock", external_task_id=created.external_id
        )
        triage = repository.find_pending_triage_execute(parent_id=fetch_task.id)
        assert triage is not None
        assert triage.context["description"] == "edited"


def test_fetch_context_refresh_includes_references(session_factory) -> None:
    """Scenario J: refresh covers references, not just text fields. After a
    user adds a non-own-write reference, ``fetch.context['references']`` must
    contain it after the next poll."""

    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="t"))
    )
    worker = _make_worker(tracker, session_factory)
    worker.poll_once()

    tracker._tasks[created.external_id].context.references.append(
        TaskLink(label="spec", url="https://x/spec", origin="user")
    )

    worker.poll_once()

    fetch_context, _ = _read_fetch_context(session_factory, created.external_id)
    urls = [ref["url"] for ref in fetch_context["references"]]
    assert "https://x/spec" in urls
