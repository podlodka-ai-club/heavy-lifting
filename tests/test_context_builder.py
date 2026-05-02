from __future__ import annotations

import pytest

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.context_builder import ContextBuilder
from backend.task_constants import TaskType
from backend.task_context import TaskChainEntry


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_context_builder_reconstructs_execute_flow(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-23",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-23",
                context={
                    "title": "Implement token pricing",
                    "description": "Carry tracker context into execute worker.",
                    "acceptance_criteria": ["Build effective context"],
                },
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task23/context-builder",
                context={
                    "title": "Implement task23",
                    "description": "Add context builder and token cost service.",
                },
                input_payload={
                    "instructions": "Implement services and tests.",
                    "base_branch": "main",
                    "branch_name": "task23/context-builder",
                    "commit_message_hint": "task23 реализовать сервисы контекста и цены токенов",
                },
            )
        )

        context = ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

        assert context.flow_type == TaskType.EXECUTE
        assert context.tracker_context is not None
        assert context.tracker_context.title == "Implement token pricing"
        assert context.execution_context is not None
        assert context.execution_context.title == "Implement task23"
        assert context.instructions == "Implement services and tests."
        assert context.base_branch == "main"
        assert context.branch_name == "task23/context-builder"
        assert context.repo_url == "https://example.test/repo.git"
        assert context.workspace_key == "repo-23"
        assert [entry.task.id for entry in context.lineage] == [fetch_task.id, execute_task.id]
        assert context.feedback_history == ()


def test_context_builder_reconstructs_deliver_flow_from_execute_result(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={"title": "Root tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task23/deliver-flow",
                pr_external_id="pr-23",
                pr_url="https://example.test/pr/23",
                context={"title": "Execute coding task"},
                input_payload={"base_branch": "develop"},
                result_payload={
                    "summary": "Execution completed",
                    "branch_name": "task23/deliver-flow",
                    "pr_url": "https://example.test/pr/23",
                },
            )
        )
        deliver_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                context={"title": "Deliver result"},
            )
        )

        context = ContextBuilder().build_for_task(
            task=deliver_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

        assert context.flow_type == TaskType.DELIVER
        assert context.execute_task is not None
        assert context.execute_result is not None
        assert context.execute_result.summary == "Execution completed"
        assert context.base_branch == "develop"
        assert context.branch_name == "task23/deliver-flow"
        assert context.pr_external_id == "pr-23"
        assert context.pr_url == "https://example.test/pr/23"


def test_context_builder_reconstructs_pr_feedback_flow_with_history(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task23/pr-feedback",
                pr_external_id="pr-77",
                pr_url="https://example.test/pr/77",
                context={"title": "Execute implementation"},
                input_payload={
                    "instructions": "Apply review feedback.",
                    "base_branch": "main",
                    "commit_message_hint": "task23 ответить на замечания review",
                },
                result_payload={
                    "summary": "Opened PR",
                    "pr_url": "https://example.test/pr/77",
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                branch_name="task23/pr-feedback",
                input_payload={
                    "instructions": "Address prior review.",
                    "pr_feedback": {
                        "pr_external_id": "pr-77",
                        "comment_id": "c-1",
                        "body": "Please add tests.",
                        "author": "reviewer-1",
                    },
                },
                result_payload={"summary": "Tests added"},
            )
        )
        current_feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                branch_name="task23/pr-feedback",
                input_payload={
                    "instructions": "Address latest review.",
                    "pr_feedback": {
                        "pr_external_id": "pr-77",
                        "comment_id": "c-2",
                        "body": "Please simplify the helper.",
                        "author": "reviewer-2",
                        "pr_url": "https://example.test/pr/77",
                    },
                },
            )
        )

        context = ContextBuilder().build_for_task(
            task=current_feedback_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

        assert context.flow_type == TaskType.PR_FEEDBACK
        assert context.execution_context is not None
        assert context.execution_context.title == "Execute implementation"
        assert context.current_feedback is not None
        assert context.current_feedback.comment_id == "c-2"
        assert context.instructions == "Address latest review."
        assert context.commit_message_hint == "task23 ответить на замечания review"
        assert context.branch_name == "task23/pr-feedback"
        assert context.pr_external_id == "pr-77"
        assert len(context.feedback_history) == 1
        assert context.feedback_history[0].feedback.comment_id == "c-1"
        assert context.feedback_history[0].result_payload is not None
        assert context.feedback_history[0].result_payload.summary == "Tests added"


def test_context_builder_rejects_pr_feedback_without_feedback_payload(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.FETCH, context={"title": "Tracker task"})
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                context={"title": "Execute task"},
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={"instructions": "Missing review payload."},
            )
        )

        with pytest.raises(ValueError, match="pr_feedback task requires input_payload.pr_feedback"):
            ContextBuilder().build_for_task(
                task=feedback_task,
                task_chain=repository.load_task_chain(fetch_task.root_id),
            )


def test_context_builder_ignores_invalid_sibling_payload_outside_lineage_and_history(
    session_factory,
) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={"title": "Tracker task"},
            )
        )
        primary_execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task23/primary",
                context={"title": "Primary execute"},
                input_payload={
                    "instructions": "Build the main change.",
                    "base_branch": "main",
                },
            )
        )
        sibling_execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task23/sibling",
                context={"title": "Sibling execute"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=sibling_execute_task.id,
                input_payload={
                    "instructions": "Broken sibling review payload.",
                    "pr_feedback": {
                        "pr_external_id": "pr-broken",
                        "comment_id": None,
                        "body": "This payload should stay isolated.",
                        "unexpected": True,
                    },
                },
            )
        )
        deliver_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=primary_execute_task.id,
                context={"title": "Deliver result"},
            )
        )

        context = ContextBuilder().build_for_task(
            task=deliver_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

        assert context.flow_type == TaskType.DELIVER
        assert context.execute_task is not None
        assert context.execute_task.task.id == primary_execute_task.id
        assert context.instructions == "Build the main change."
        assert context.feedback_history == ()


def test_context_builder_falls_back_to_execute_result_branch_and_feedback_pr_url(
    session_factory,
) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.FETCH, context={"title": "Tracker task"})
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                context={"title": "Execute task"},
                result_payload={
                    "summary": "Opened PR",
                    "branch_name": "task32/result-branch",
                },
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "pr_feedback": {
                        "pr_external_id": "pr-32",
                        "comment_id": "c-32",
                        "body": "Please keep the regression test.",
                        "pr_url": "https://example.test/pr/32",
                    }
                },
            )
        )

        context = ContextBuilder().build_for_task(
            task=feedback_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

        assert context.branch_name == "task32/result-branch"
        assert context.pr_external_id == "pr-32"
        assert context.pr_url == "https://example.test/pr/32"


def _make_chain_entry(*, task_id: int, task_type: TaskType) -> TaskChainEntry:
    """Build a transient ``TaskChainEntry`` for unit-testing pure lineage logic.

    No DB session is involved — the underlying ``Task`` is constructed directly with
    the bare minimum of attributes needed by ``_find_relevant_execute_for_current``.
    """
    task = Task(id=task_id, task_type=task_type)
    entry = TaskChainEntry(task=task)
    object.__setattr__(entry, "context", None)
    object.__setattr__(entry, "input_payload", None)
    object.__setattr__(entry, "result_payload", None)
    return entry


def test_find_relevant_execute_returns_self_when_current_is_execute() -> None:
    fetch_entry = _make_chain_entry(task_id=1, task_type=TaskType.FETCH)
    execute_entry = _make_chain_entry(task_id=2, task_type=TaskType.EXECUTE)
    lineage = (fetch_entry, execute_entry)

    found = ContextBuilder()._find_relevant_execute_for_current(
        current_entry=execute_entry, lineage=lineage
    )

    assert found is execute_entry


def test_find_relevant_execute_returns_last_ancestor_for_deliver() -> None:
    fetch_entry = _make_chain_entry(task_id=1, task_type=TaskType.FETCH)
    impl_execute_entry = _make_chain_entry(task_id=2, task_type=TaskType.EXECUTE)
    deliver_entry = _make_chain_entry(task_id=3, task_type=TaskType.DELIVER)
    lineage = (fetch_entry, impl_execute_entry, deliver_entry)

    found = ContextBuilder()._find_relevant_execute_for_current(
        current_entry=deliver_entry, lineage=lineage
    )

    assert found is impl_execute_entry


def test_find_relevant_execute_returns_none_when_no_execute_in_lineage() -> None:
    fetch_entry = _make_chain_entry(task_id=1, task_type=TaskType.FETCH)
    lineage = (fetch_entry,)

    found = ContextBuilder()._find_relevant_execute_for_current(
        current_entry=fetch_entry, lineage=lineage
    )

    assert found is None


def test_find_relevant_execute_picks_last_when_two_executes_in_lineage() -> None:
    """Regression for gap #10: with [fetch, triage_execute, impl_execute, deliver]
    the deliver-task must see the implementation-execute, not the triage-execute."""

    fetch_entry = _make_chain_entry(task_id=1, task_type=TaskType.FETCH)
    triage_execute_entry = _make_chain_entry(task_id=2, task_type=TaskType.EXECUTE)
    impl_execute_entry = _make_chain_entry(task_id=3, task_type=TaskType.EXECUTE)
    deliver_entry = _make_chain_entry(task_id=4, task_type=TaskType.DELIVER)
    lineage = (fetch_entry, triage_execute_entry, impl_execute_entry, deliver_entry)

    found = ContextBuilder()._find_relevant_execute_for_current(
        current_entry=deliver_entry, lineage=lineage
    )

    assert found is impl_execute_entry
