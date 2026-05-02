"""Provenance tests for ``MockTracker.attach_links`` (task18a §6.7a).

Adapter contract: every link added through ``attach_links`` must carry
``origin='own_write'`` so the re-triage hash function ignores it. References
written directly into a fixture (without going through ``attach_links``) keep
their original ``origin`` (``None`` or ``"user"``).
"""

from __future__ import annotations

from backend.adapters.mock_tracker import MockTracker
from backend.schemas import (
    TaskContext,
    TaskLink,
    TrackerLinksAttachPayload,
    TrackerTaskCreatePayload,
)


def test_attach_links_marks_origin_own_write() -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="x"))
    )

    tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id=created.external_id,
            links=[
                TaskLink(label="branch", url="https://example/branch"),
                TaskLink(label="pull_request", url="https://example/pr/1", origin="user"),
            ],
        )
    )

    refreshed = tracker._tasks[created.external_id]
    assert len(refreshed.context.references) == 2
    assert all(link.origin == "own_write" for link in refreshed.context.references)


def test_fixture_references_keep_their_origin() -> None:
    tracker = MockTracker()
    created = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="x"))
    )

    user_link = TaskLink(label="spec", url="https://example/spec", origin="user")
    tracker._tasks[created.external_id].context.references.append(user_link)
    legacy_link = TaskLink(label="legacy", url="https://example/legacy")
    tracker._tasks[created.external_id].context.references.append(legacy_link)

    tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id=created.external_id,
            links=[TaskLink(label="branch", url="https://example/branch")],
        )
    )

    refreshed = tracker._tasks[created.external_id].context.references
    assert refreshed[0].origin == "user"
    assert refreshed[1].origin is None
    assert refreshed[2].origin == "own_write"
