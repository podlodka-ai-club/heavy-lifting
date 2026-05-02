"""Tests for ``LocalAgentRunner`` triage-mode envelope (task11 §1).

When ``request.task_context.current_task.input_payload.action == "triage"`` the
runner returns a deterministic triage envelope (``<triage_result>`` + ``<markdown>``)
in ``raw_stdout`` so ``parse_triage_output`` can decode it. The mapping from
``tracker_context.description`` length to Story Points is fixed for
reproducibility on the local test stand:

* 0–199 chars → SP=2 (impl/routed).
* 200–999 chars → SP=3 (impl/routed).
* 1000+ chars → SP=5 (research/needs_clarification).

The non-triage path is unchanged: ``raw_stdout == ""`` and the placeholder
payload summary is preserved.
"""

from __future__ import annotations

import pytest

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.protocols.agent_runner import AgentRunRequest
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.services.context_builder import ContextBuilder
from backend.services.triage_parser import parse_triage_output
from backend.task_constants import TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _build_triage_request(
    session_factory, *, description: str, suffix: str
) -> AgentRunRequest:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=f"TASK-{suffix}",
                context={
                    "title": "Triage local-stub task",
                    "description": description,
                    "acceptance_criteria": [],
                },
            )
        )
        triage = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id=f"TASK-{suffix}",
                context={"title": "Triage local-stub task"},
                input_payload={"action": "triage"},
            )
        )
        chain = repository.load_task_chain(fetch.id)
        effective = ContextBuilder().build_for_task(task=triage, task_chain=chain)
    return AgentRunRequest(task_context=effective, workspace_path="/tmp/triage-stub")


def _build_impl_request(session_factory, *, suffix: str) -> AgentRunRequest:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=f"TASK-{suffix}",
                context={"title": "Impl placeholder task"},
            )
        )
        impl = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch.id,
                tracker_name="mock",
                external_parent_id=f"TASK-{suffix}",
                context={"title": "Impl placeholder task"},
                input_payload={
                    "action": "implementation",
                    "instructions": "Run.",
                    "branch_name": f"task{suffix}/run",
                    "base_branch": "main",
                },
            )
        )
        chain = repository.load_task_chain(fetch.id)
        effective = ContextBuilder().build_for_task(task=impl, task_chain=chain)
    return AgentRunRequest(task_context=effective, workspace_path="/tmp/impl-stub")


def test_triage_mode_emits_sp2_envelope_for_short_description(session_factory) -> None:
    runner = LocalAgentRunner()
    request = _build_triage_request(
        session_factory, description="Short description.", suffix="sp2"
    )

    result = runner.run(request)

    assert result.raw_stdout != ""
    decision = parse_triage_output(result.raw_stdout)
    assert decision.story_points == 2
    assert decision.task_kind == "implementation"
    assert decision.outcome == "routed"
    assert decision.brief_markdown is not None
    assert decision.brief_markdown.startswith("## Agent Handover Brief")
    assert decision.comment_markdown is None


def test_triage_mode_emits_sp3_envelope_for_medium_description(session_factory) -> None:
    runner = LocalAgentRunner()
    request = _build_triage_request(
        session_factory,
        description="x" * 500,
        suffix="sp3",
    )

    result = runner.run(request)

    decision = parse_triage_output(result.raw_stdout)
    assert decision.story_points == 3
    assert decision.task_kind == "implementation"
    assert decision.outcome == "routed"
    assert decision.brief_markdown is not None
    assert decision.brief_markdown.startswith("## Agent Handover Brief")


def test_triage_mode_emits_sp5_envelope_for_long_description(session_factory) -> None:
    runner = LocalAgentRunner()
    request = _build_triage_request(
        session_factory,
        description="x" * 2000,
        suffix="sp5",
    )

    result = runner.run(request)

    decision = parse_triage_output(result.raw_stdout)
    assert decision.story_points == 5
    assert decision.task_kind == "research"
    assert decision.outcome == "needs_clarification"
    assert decision.brief_markdown is None
    assert decision.comment_markdown is not None
    assert decision.comment_markdown.startswith("## RFI")


def test_triage_mode_metadata_marks_runner_mode(session_factory) -> None:
    runner = LocalAgentRunner()
    request = _build_triage_request(
        session_factory, description="Triage stub.", suffix="meta"
    )

    result = runner.run(request)

    assert result.payload.metadata["mode"] == "triage_stub"
    assert result.payload.metadata["runner_adapter"] == "local"
    assert result.payload.summary == "Prepared local triage envelope."


def test_non_triage_request_returns_placeholder_payload(session_factory) -> None:
    runner = LocalAgentRunner()
    request = _build_impl_request(session_factory, suffix="impl")

    result = runner.run(request)

    assert result.raw_stdout == ""
    assert result.payload.summary == "Prepared local agent execution for Impl placeholder task."
    assert result.payload.metadata["mode"] == "placeholder"
