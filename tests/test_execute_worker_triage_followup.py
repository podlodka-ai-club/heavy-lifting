"""Tests for ``ExecuteWorker._ensure_followup_implementation_execute`` (task07).

These tests cover sibling impl-execute creation after a successful triage
(SP 1/2/3), idempotency through ``find_implementation_execute_for_root``,
and the negative paths for SP 5/8/13 escalations + edge cases.
"""

from __future__ import annotations

import pytest

from backend.adapters.mock_scm import MockScm
from backend.db import session_scope
from backend.models import Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import TaskInputPayload, TaskResultPayload, TaskRoutingPayload
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
# Test 1 — SP=2 happy path → sibling created with all expected fields
# ---------------------------------------------------------------------------


def test_triage_creates_sibling_implementation_execute_for_sp_2(tmp_path) -> None:
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
        fetch = _create_fetch(repository, suffix="sp2")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-sp2",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-sp2",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        triage_row = session.get(Task, triage_id)
        assert triage_row is not None
        assert triage_row.status == TaskStatus.DONE

        siblings = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .all()
        )
        assert len(siblings) == 1
        sibling = siblings[0]

        assert sibling.parent_id == fetch_id
        assert sibling.task_type == TaskType.EXECUTE
        assert sibling.status == TaskStatus.NEW
        assert sibling.tracker_name == "mock"
        assert sibling.external_parent_id == "TASK-sp2"
        assert sibling.repo_url == "https://example.test/repo.git"
        assert sibling.repo_ref == "main"
        assert sibling.workspace_key == "repo-sp2"
        assert sibling.context == {"title": "Triage execute"}
        assert sibling.branch_name is None
        assert sibling.pr_external_id is None
        assert sibling.pr_url is None

        payload = sibling.input_payload
        assert isinstance(payload, dict)
        assert payload["schema_version"] == 1
        assert payload["action"] == "implementation"
        handoff = payload["handoff"]
        assert handoff["from_task_id"] == triage_id
        assert handoff["from_role"] == "triage"
        assert isinstance(handoff["brief_markdown"], str)
        assert handoff["brief_markdown"].startswith("## Agent Handover Brief")


# ---------------------------------------------------------------------------
# Test 2 — SP=1 / SP=3 (parametrised) → sibling created
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("story_points", [1, 3])
def test_triage_creates_sibling_for_sp_1_and_sp_3(tmp_path, story_points: int) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=story_points,
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
        fetch = _create_fetch(repository, suffix=f"sp{story_points}")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id=f"TASK-sp{story_points}",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key=f"repo-sp{story_points}",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        siblings = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .all()
        )
        assert len(siblings) == 1
        sibling = siblings[0]
        payload = sibling.input_payload
        assert isinstance(payload, dict)
        assert payload["action"] == "implementation"
        assert payload["handoff"]["from_task_id"] == triage_id
        assert payload["handoff"]["from_role"] == "triage"
        assert isinstance(payload["handoff"]["brief_markdown"], str)
        assert payload["handoff"]["brief_markdown"].startswith("## Agent Handover Brief")


# ---------------------------------------------------------------------------
# Test 3 — SP=5 (RFI) → no sibling, deliver row only
# ---------------------------------------------------------------------------


_RFI_COMMENT = (
    "## RFI\n\n"
    "Need clarification on auth flow. SP=5.\n"
)


_DECOMPOSITION_BODY = (
    "## Decomposition\n\n"
    "Split into smaller tasks.\n"
)


_SYSTEM_DESIGN_BODY = (
    "## Needs System Design\n\n"
    "Need architectural review.\n"
)


def test_triage_does_not_create_sibling_for_sp_5_rfi(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=5,
            task_kind="research",
            outcome="needs_clarification",
            markdown_body=_RFI_COMMENT,
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
        fetch = _create_fetch(repository, suffix="sp5")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-sp5",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-sp5",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id
        root_id = fetch.id  # root == fetch.id since fetch is created without parent

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        triage_row = session.get(Task, triage_id)
        assert triage_row is not None
        assert triage_row.status == TaskStatus.DONE

        # No execute task other than the triage itself under fetch root
        executes = (
            session.query(Task)
            .filter(
                Task.root_id == root_id,
                Task.task_type == TaskType.EXECUTE,
            )
            .all()
        )
        assert len(executes) == 1
        assert executes[0].id == triage_id

        # find_implementation_execute_for_root must return None
        repository = TaskRepository(session)
        assert repository.find_implementation_execute_for_root(root_id) is None

        # Deliver row under the triage exists (task06 contract preserved)
        deliver = (
            session.query(Task)
            .filter(Task.parent_id == triage_id, Task.task_type == TaskType.DELIVER)
            .first()
        )
        assert deliver is not None
        assert deliver.status == TaskStatus.NEW
        # Confirm escalation routing path: parent of triage (fetch) holds no sibling
        siblings = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .all()
        )
        assert siblings == []


# ---------------------------------------------------------------------------
# Test 4 — SP=8 (decomposition) → no sibling
# ---------------------------------------------------------------------------


def test_triage_does_not_create_sibling_for_sp_8_decomposition(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=8,
            task_kind="implementation",
            outcome="routed",
            markdown_body=_DECOMPOSITION_BODY,
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
        fetch = _create_fetch(repository, suffix="sp8")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-sp8",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-sp8",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        root_id = fetch.id

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        assert repository.find_implementation_execute_for_root(root_id) is None
        executes = (
            session.query(Task)
            .filter(
                Task.root_id == root_id,
                Task.task_type == TaskType.EXECUTE,
            )
            .all()
        )
        assert len(executes) == 1
        assert executes[0].id == triage_id


# ---------------------------------------------------------------------------
# Test 5 — SP=13 (system_design) → no sibling
# ---------------------------------------------------------------------------


def test_triage_does_not_create_sibling_for_sp_13_system_design(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=13,
            task_kind="implementation",
            outcome="routed",
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
        fetch = _create_fetch(repository, suffix="sp13")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-sp13",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-sp13",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        root_id = fetch.id

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        assert repository.find_implementation_execute_for_root(root_id) is None
        executes = (
            session.query(Task)
            .filter(
                Task.root_id == root_id,
                Task.task_type == TaskType.EXECUTE,
            )
            .all()
        )
        assert len(executes) == 1
        assert executes[0].id == triage_id


# ---------------------------------------------------------------------------
# Test 6 — idempotency: existing impl-execute → no second sibling
# ---------------------------------------------------------------------------


def test_triage_idempotent_when_sibling_already_exists(tmp_path, caplog) -> None:
    """Second triage in the same cluster must not duplicate the sibling.

    Setup: fetch + DONE triage + existing NEW impl-execute (from a prior
    triage run). We then create another NEW triage task (re-triage scenario)
    and process it. The new triage must complete DONE but NOT create a second
    impl-execute under the fetch root.
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
        fetch = _create_fetch(repository, suffix="idem")
        # First triage — already DONE.
        prior_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-idem",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-idem",
                context={"title": "Earlier triage"},
                input_payload={"action": "triage"},
            )
        )
        # Existing sibling impl-execute from the prior triage.
        existing_impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.NEW,
                tracker_name="mock",
                external_parent_id="TASK-idem",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-idem",
                context={"title": "Earlier impl"},
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
        # New triage (re-triage scenario).
        new_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-idem",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-idem",
                context={"title": "Re-triage"},
                input_payload={"action": "triage"},
            )
        )
        new_triage_id = new_triage.id
        root_id = fetch.id
        fetch_id = fetch.id

    # poll_once polls only NEW tasks; existing_impl is NEW too and would
    # be picked first (FIFO). To exercise the re-triage path we mark it
    # PROCESSING so poll_task skips it and reaches the new triage.
    with session_scope(session_factory=session_factory) as session:
        impl = session.get(Task, existing_impl_id)
        assert impl is not None
        impl.status = TaskStatus.PROCESSING

    with caplog.at_level("INFO"):
        worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        new_triage_row = session.get(Task, new_triage_id)
        assert new_triage_row is not None
        assert new_triage_row.status == TaskStatus.DONE

        impl_executes = []
        for execute in (
            session.query(Task)
            .filter(
                Task.root_id == root_id,
                Task.task_type == TaskType.EXECUTE,
            )
            .all()
        ):
            payload = execute.input_payload
            if isinstance(payload, dict) and payload.get("action") == "implementation":
                impl_executes.append(execute)
        assert len(impl_executes) == 1
        assert impl_executes[0].id == existing_impl_id
        # The new triage did NOT add an extra execute under the fetch.
        sibling_count = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
            )
            .count()
        )
        # Two triages + one prior impl-execute = 3 total, no fourth.
        assert sibling_count == 3

    skip_messages = [
        record
        for record in caplog.records
        if "sibling_implementation_execute_skipped_idempotent" in record.getMessage()
    ]
    assert skip_messages, "expected idempotent skip log event"


# ---------------------------------------------------------------------------
# Test 7 — handover_brief inline propagation (already covered by Test 1
# extras, but explicit here for clarity).
# ---------------------------------------------------------------------------


def test_triage_followup_passes_brief_to_handover_payload(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    brief_body = "## Agent Handover Brief\n\nA single-line stub for the resolver.\n"
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=2,
            task_kind="implementation",
            outcome="routed",
            markdown_body=brief_body,
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
        fetch = _create_fetch(repository, suffix="brief")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-brief",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-brief",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id

    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        sibling = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .first()
        )
        assert sibling is not None
        payload = sibling.input_payload
        assert isinstance(payload, dict)
        # TaskInputPayload validates the schema.
        validated = TaskInputPayload.model_validate(payload)
        assert validated.action == "implementation"
        assert validated.handoff is not None
        assert validated.handoff.brief_markdown is not None
        assert validated.handoff.brief_markdown.startswith("## Agent Handover Brief")


# ---------------------------------------------------------------------------
# Test 8 — direct unit test of _ensure_followup_implementation_execute when
# brief metadata is missing; sibling is still created with brief_markdown=None.
#
# We test the helper directly because the standard envelope guarantees
# brief presence for SP 1/2/3 (TriageStep populates metadata["handover_brief"]
# only when decision.brief_markdown is non-None). Hand-crafted payload
# isolates the worker contract from the TriageStep parser.
# ---------------------------------------------------------------------------


def test_triage_followup_skipped_when_brief_metadata_missing(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=_FakeAgentRunner(canned_stdout="unused"),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="nobrief")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-nobrief",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-nobrief",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id

        result_payload = TaskResultPayload(
            summary="Triage routed.",
            outcome="routed",
            routing=TaskRoutingPayload(
                next_task_type="execute",
                next_role="implementation",
                create_followup_task=True,
                requires_human_approval=False,
            ),
            metadata={},  # no handover_brief
        )
        sibling = worker._ensure_followup_implementation_execute(
            repository=repository,
            triage_task=triage_task,
            result_payload=result_payload,
        )
        assert sibling is not None
        sibling_id = sibling.id

    with session_scope(session_factory=session_factory) as session:
        sibling_row = session.get(Task, sibling_id)
        assert sibling_row is not None
        assert sibling_row.parent_id == fetch_id
        payload = sibling_row.input_payload
        assert isinstance(payload, dict)
        assert payload["action"] == "implementation"
        assert payload["handoff"]["from_task_id"] == triage_id
        assert payload["handoff"]["from_role"] == "triage"
        assert payload["handoff"]["brief_markdown"] is None


# ---------------------------------------------------------------------------
# Test 9 — defensive: routing=None → returns None without raising.
# ---------------------------------------------------------------------------


def test_triage_followup_creates_no_sibling_when_routing_is_none(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=_FakeAgentRunner(canned_stdout="unused"),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = _create_fetch(repository, suffix="norouting")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-norouting",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-norouting",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        fetch_id = fetch.id
        triage_id = triage_task.id

        result_payload = TaskResultPayload(
            summary="Defensive case.",
            outcome="routed",
            routing=None,
            metadata={},
        )
        result = worker._ensure_followup_implementation_execute(
            repository=repository,
            triage_task=triage_task,
            result_payload=result_payload,
        )
        assert result is None

    with session_scope(session_factory=session_factory) as session:
        siblings = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .all()
        )
        assert siblings == []


# ---------------------------------------------------------------------------
# Test 10 — fail-loud when triage has no parent_id.
# ---------------------------------------------------------------------------


def test_triage_followup_raises_when_triage_has_no_parent(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=_FakeAgentRunner(canned_stdout="unused"),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        # Hand-craft an orphan triage execute (no parent_id) — violates
        # tracker_intake invariant but still the contract requires fail-loud.
        orphan_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=None,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=None,
                context={"title": "Orphan triage"},
                input_payload={"action": "triage"},
            )
        )
        result_payload = TaskResultPayload(
            summary="Triage routed.",
            outcome="routed",
            routing=TaskRoutingPayload(
                next_task_type="execute",
                next_role="implementation",
                create_followup_task=True,
                requires_human_approval=False,
            ),
            metadata={"handover_brief": "BRIEF"},
        )
        with pytest.raises(RuntimeError, match="fetch parent"):
            worker._ensure_followup_implementation_execute(
                repository=repository,
                triage_task=orphan_triage,
                result_payload=result_payload,
            )


# ---------------------------------------------------------------------------
# Test 10b — fail-loud дolжен срабатывать ДАЖЕ когда idempotency-lookup
# нашёл бы existing impl-execute под тем же root_id.
#
# Codex REVIEW round 1 (P1) пометил, что прежний порядок проверок:
#   existing = find_impl_for_root(root_id) → return None (idempotency)
#   if triage.parent_id is None: raise RuntimeError(...)  # never reached!
# тихо маскировал нарушенный инвариант tracker_intake. Фикс — переставить
# fail-loud parent_id проверку ДО idempotency lookup. Этот тест регрессионно
# фиксирует новый порядок: orphan-триаж + existing impl всё равно raise.
# ---------------------------------------------------------------------------


def test_triage_followup_raises_on_orphan_even_when_existing_impl_present(
    tmp_path,
) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=MockScm(),
        agent_runner=_FakeAgentRunner(canned_stdout="unused"),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        # Orphan triage (parent_id=None) — нарушает инвариант, но именно
        # этот сценарий должен отлавливаться fail-loud-ом.
        orphan_triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=None,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=None,
                context={"title": "Orphan triage"},
                input_payload={"action": "triage"},
            )
        )
        orphan_root_id = orphan_triage.root_id or orphan_triage.id
        # Существующий impl-execute под тем же root_id (artefact of a
        # corrupted/half-broken cluster). Без round-2 фикса idempotency-lookup
        # вернул бы existing → return None, проглотив инвариант.
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=orphan_triage.id,
                status=TaskStatus.NEW,
                tracker_name="mock",
                external_parent_id=None,
                context={"title": "Existing impl"},
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": orphan_triage.id,
                        "from_role": "triage",
                        "brief_markdown": "EXISTING-BRIEF",
                    },
                },
            )
        )
        # Sanity: idempotency-lookup действительно НАШЁЛ бы кандидата.
        assert (
            repository.find_implementation_execute_for_root(orphan_root_id)
            is not None
        )
        result_payload = TaskResultPayload(
            summary="Triage routed.",
            outcome="routed",
            routing=TaskRoutingPayload(
                next_task_type="execute",
                next_role="implementation",
                create_followup_task=True,
                requires_human_approval=False,
            ),
            metadata={"handover_brief": "BRIEF"},
        )
        with pytest.raises(RuntimeError, match="fetch parent"):
            worker._ensure_followup_implementation_execute(
                repository=repository,
                triage_task=orphan_triage,
                result_payload=result_payload,
            )


# ---------------------------------------------------------------------------
# Test 11 — sibling impl-execute is compatible with task09
# ContextBuilder.handover_brief resolver (primary inline path).
# ---------------------------------------------------------------------------


def test_triage_followup_compatible_with_handover_brief_resolver(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    brief_body = "## Agent Handover Brief\n\nReusable brief body.\n"
    fake = _FakeAgentRunner(
        canned_stdout=_envelope(
            story_points=2,
            task_kind="implementation",
            outcome="routed",
            markdown_body=brief_body,
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
        fetch = _create_fetch(repository, suffix="t09")
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id="TASK-t09",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-t09",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_id = triage_task.id
        fetch_id = fetch.id

    # Run the triage poll: triage completes DONE + sibling impl-execute created.
    worker.poll_once()

    with session_scope(session_factory=session_factory) as session:
        sibling = (
            session.query(Task)
            .filter(
                Task.parent_id == fetch_id,
                Task.task_type == TaskType.EXECUTE,
                Task.id != triage_id,
            )
            .first()
        )
        assert sibling is not None
        sibling_id = sibling.id

    # Now invoke _prepare_execution directly on the sibling to verify
    # ContextBuilder picks up the inline handover_brief from input_payload.
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        sibling_row = session.get(Task, sibling_id)
        assert sibling_row is not None
        chain = repository.load_task_chain(sibling_row.root_id or sibling_row.id)
        sibling_in_chain = next(t for t in chain if t.id == sibling_id)
        prepared = worker._prepare_execution(
            repository=repository,
            task=sibling_in_chain,
            task_chain=chain,
        )

    assert prepared.task_context.handover_brief is not None
    assert prepared.task_context.handover_brief.startswith("## Agent Handover Brief")
