from decimal import Decimal

import pytest

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task, TokenUsage
from backend.repositories.task_repository import (
    TaskCreateParams,
    TaskRepository,
    TokenUsageCreateParams,
)
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_create_task_sets_root_id_for_root_and_child_tasks(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        root_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="T-1",
            )
        )
        child_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=root_task.id,
                external_parent_id="T-1",
            )
        )

        assert root_task.root_id == root_task.id
        assert child_task.parent_id == root_task.id
        assert child_task.root_id == root_task.id


def test_create_task_rejects_conflicting_parent_chain_root_id(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        first_root = repository.create_task(TaskCreateParams(task_type=TaskType.FETCH))
        second_root = repository.create_task(TaskCreateParams(task_type=TaskType.FETCH))

        with pytest.raises(ValueError, match="root_id must match the parent task chain"):
            repository.create_task(
                TaskCreateParams(
                    task_type=TaskType.EXECUTE,
                    parent_id=first_root.id,
                    root_id=second_root.id,
                )
            )


def test_create_task_rejects_root_id_for_parentless_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        with pytest.raises(ValueError, match="root_id cannot be set without parent_id"):
            repository.create_task(
                TaskCreateParams(
                    task_type=TaskType.FETCH,
                    root_id=999,
                )
            )


def test_load_task_chain_returns_all_tasks_in_creation_order(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        root_task = repository.create_task(TaskCreateParams(task_type=TaskType.FETCH))
        execute_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, parent_id=root_task.id)
        )
        deliver_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.DELIVER, parent_id=execute_task.id)
        )

        chain = repository.load_task_chain(root_task.id)

        assert [task.id for task in chain] == [root_task.id, execute_task.id, deliver_task.id]


def test_list_tasks_returns_all_tasks_in_creation_order(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        first_task = repository.create_task(TaskCreateParams(task_type=TaskType.FETCH))
        second_task = repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))

        tasks = repository.list_tasks()

        assert [task.id for task in tasks] == [first_task.id, second_task.id]


def test_get_task_returns_matching_task_by_id(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        created_task = repository.create_task(TaskCreateParams(task_type=TaskType.FETCH))

        found_task = repository.get_task(created_task.id)

        assert found_task is not None
        assert found_task.id == created_task.id


def test_poll_task_claims_oldest_matching_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        first_task = repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))
        second_task = repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))
        repository.create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, status=TaskStatus.PROCESSING)
        )

        claimed_task = repository.poll_task(task_type=TaskType.EXECUTE)

        assert claimed_task is not None
        assert claimed_task.id == first_task.id
        assert claimed_task.status == TaskStatus.PROCESSING
        assert session.get(Task, second_task.id).status == TaskStatus.NEW


def test_find_execute_task_by_pr_external_id_ignores_other_task_types(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                pr_external_id="pr-123",
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                pr_external_id="pr-123",
            )
        )

        found_task = repository.find_execute_task_by_pr_external_id("pr-123")

        assert found_task is not None
        assert found_task.id == execute_task.id


def test_list_execute_tasks_with_prs_returns_only_execute_tasks_with_pr_ids(
    session_factory,
) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        expected_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                pr_external_id="pr-123",
            )
        )
        repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                pr_external_id="pr-456",
            )
        )

        tasks = repository.list_execute_tasks_with_prs()

        assert [task.id for task in tasks] == [expected_task.id]


def test_find_child_task_helpers_support_dedupe_and_cursor_lookups(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        parent_task = repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))
        first_feedback = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=parent_task.id,
                external_task_id="comment-1",
            )
        )
        latest_feedback = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=parent_task.id,
                external_task_id="comment-2",
            )
        )

        matched_task = repository.find_child_task_by_external_id(
            parent_id=parent_task.id,
            task_type=TaskType.PR_FEEDBACK,
            external_task_id="comment-1",
        )
        last_task = repository.find_latest_child_task(
            parent_id=parent_task.id,
            task_type=TaskType.PR_FEEDBACK,
        )

        assert matched_task is not None
        assert matched_task.id == first_feedback.id
        assert last_task is not None
        assert last_task.id == latest_feedback.id


def test_update_task_workspace_context_overwrites_only_provided_fields(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                repo_url="https://example.test/old.git",
                repo_ref="main",
                workspace_key="repo-1",
            )
        )

        repository.update_task_workspace_context(
            task.id,
            repo_url="https://example.test/new.git",
        )

        refreshed = session.get(Task, task.id)
        assert refreshed is not None
        assert refreshed.repo_url == "https://example.test/new.git"
        assert refreshed.repo_ref == "main"
        assert refreshed.workspace_key == "repo-1"


def test_update_task_workspace_context_preserves_existing_when_none_passed(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                repo_url="https://example.test/old.git",
                repo_ref="main",
                workspace_key="repo-1",
            )
        )

        repository.update_task_workspace_context(task.id)

        refreshed = session.get(Task, task.id)
        assert refreshed is not None
        assert refreshed.repo_url == "https://example.test/old.git"
        assert refreshed.repo_ref == "main"
        assert refreshed.workspace_key == "repo-1"


def test_update_task_workspace_context_raises_for_unknown_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)

        with pytest.raises(ValueError, match="Task 999 does not exist"):
            repository.update_task_workspace_context(999, repo_url="x")


def test_record_token_usage_persists_entry_for_task(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        task = repository.create_task(TaskCreateParams(task_type=TaskType.EXECUTE))

        usage = repository.record_token_usage(
            task_id=task.id,
            usage=TokenUsageCreateParams(
                model="gpt-5.4",
                provider="openai",
                input_tokens=10,
                output_tokens=5,
                cached_tokens=2,
                estimated=True,
                cost_usd=Decimal("0.123456"),
            ),
        )

        persisted_usage = session.get(TokenUsage, usage.id)

        assert persisted_usage is not None
        assert persisted_usage.task_id == task.id
        assert persisted_usage.model == "gpt-5.4"
        assert persisted_usage.provider == "openai"
        assert persisted_usage.input_tokens == 10
        assert persisted_usage.output_tokens == 5
        assert persisted_usage.cached_tokens == 2
        assert persisted_usage.estimated is True
        assert persisted_usage.cost_usd == Decimal("0.123456")
