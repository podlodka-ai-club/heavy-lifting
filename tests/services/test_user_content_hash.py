"""Unit tests for ``compute_user_content_hash`` (task18a §6.7a).

The function must be:

* deterministic for the same user-authored content,
* sensitive to ``title``, ``description``, ``acceptance_criteria``, and to
  references whose ``origin`` is not ``"own_write"``,
* insensitive to ``metadata`` and to references with ``origin == "own_write"``,
* independent of the ordering of acceptance criteria and references.
"""

from __future__ import annotations

from backend.schemas import TaskContext, TaskLink, TrackerTask
from backend.services.user_content_hash import compute_user_content_hash


def _task(**context_overrides: object) -> TrackerTask:
    base = {
        "title": "Implement intake",
        "description": "Add fetch and execute tasks.",
        "acceptance_criteria": ["Local execute is queued"],
        "references": [],
        "metadata": {},
    }
    base.update(context_overrides)
    return TrackerTask(
        external_id="task-1",
        context=TaskContext.model_validate(base),
    )


def test_idempotent_hash_for_same_input() -> None:
    a = _task()
    b = _task()
    assert compute_user_content_hash(a) == compute_user_content_hash(b)


def test_hash_sensitive_to_title() -> None:
    a = _task(title="Old title")
    b = _task(title="New title")
    assert compute_user_content_hash(a) != compute_user_content_hash(b)


def test_hash_sensitive_to_description() -> None:
    a = _task(description="A")
    b = _task(description="B")
    assert compute_user_content_hash(a) != compute_user_content_hash(b)


def test_hash_sensitive_to_acceptance_criteria() -> None:
    a = _task(acceptance_criteria=["one"])
    b = _task(acceptance_criteria=["one", "two"])
    assert compute_user_content_hash(a) != compute_user_content_hash(b)


def test_hash_sensitive_to_user_reference() -> None:
    a = _task()
    b = _task(
        references=[TaskLink(label="spec", url="https://x/spec", origin="user").model_dump()]
    )
    assert compute_user_content_hash(a) != compute_user_content_hash(b)


def test_hash_sensitive_to_legacy_origin_none_reference() -> None:
    """References with ``origin=None`` (legacy) must participate in the hash.

    Safe-fail rule: unknown provenance is treated as user-authored, so a
    pre-existing reference written before this contract still triggers a
    refresh when modified.
    """
    a = _task()
    b = _task(references=[TaskLink(label="legacy", url="https://x/legacy").model_dump()])
    assert compute_user_content_hash(a) != compute_user_content_hash(b)


def test_hash_ignores_own_write_reference() -> None:
    a = _task()
    b = _task(
        references=[
            TaskLink(label="branch", url="https://x/branch", origin="own_write").model_dump(),
        ]
    )
    assert compute_user_content_hash(a) == compute_user_content_hash(b)


def test_hash_ignores_metadata() -> None:
    a = _task()
    b = _task(metadata={"selection": {"taken_in_work": True}, "anything": "else"})
    assert compute_user_content_hash(a) == compute_user_content_hash(b)


def test_hash_independent_of_acceptance_criteria_order() -> None:
    a = _task(acceptance_criteria=["alpha", "beta"])
    b = _task(acceptance_criteria=["beta", "alpha"])
    assert compute_user_content_hash(a) == compute_user_content_hash(b)


def test_hash_independent_of_reference_order() -> None:
    link_x = TaskLink(label="x", url="https://x", origin="user").model_dump()
    link_y = TaskLink(label="y", url="https://y", origin="user").model_dump()
    a = _task(references=[link_x, link_y])
    b = _task(references=[link_y, link_x])
    assert compute_user_content_hash(a) == compute_user_content_hash(b)


def test_collision_label_does_not_demote_user_reference() -> None:
    """A user-attached reference whose label collides with our internal
    convention (``pull_request``, ``branch``) must still count as user content
    when its ``origin`` is ``user``. The provenance is the source of truth."""
    a = _task()
    b = _task(
        references=[
            TaskLink(
                label="pull_request",
                url="https://attacker/file",
                origin="user",
            ).model_dump(),
        ]
    )
    assert compute_user_content_hash(a) != compute_user_content_hash(b)
