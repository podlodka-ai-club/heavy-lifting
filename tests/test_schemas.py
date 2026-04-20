from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.schemas import (
    PrFeedbackPayload,
    TaskContext,
    TaskInputPayload,
    TaskResultPayload,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerTask,
    TrackerTaskCreatePayload,
)
from backend.task_constants import TaskStatus, TaskType


def test_task_context_serializes_mvp_fields() -> None:
    context = TaskContext(
        title="Add worker flow",
        description="Implement the execute worker.",
        acceptance_criteria=["Create PR", "Persist task result"],
        references=[{"label": "spec", "url": "https://example.test/spec"}],
        metadata={"tracker": "mock"},
    )

    assert context.model_dump(mode="json") == {
        "title": "Add worker flow",
        "description": "Implement the execute worker.",
        "acceptance_criteria": ["Create PR", "Persist task result"],
        "references": [{"label": "spec", "url": "https://example.test/spec"}],
        "metadata": {"tracker": "mock"},
    }


def test_task_input_payload_supports_pr_feedback() -> None:
    payload = TaskInputPayload(
        instructions="Address PR review comments.",
        branch_name="feature/task-16",
        pr_feedback=PrFeedbackPayload(
            pr_external_id="42",
            comment_id="c-7",
            body="Please rename this field.",
            path="src/backend/schemas.py",
            line=12,
            author="reviewer",
        ),
    )

    assert payload.model_dump(mode="json") == {
        "instructions": "Address PR review comments.",
        "base_branch": None,
        "branch_name": "feature/task-16",
        "commit_message_hint": None,
        "pr_feedback": {
            "pr_external_id": "42",
            "comment_id": "c-7",
            "body": "Please rename this field.",
            "author": "reviewer",
            "path": "src/backend/schemas.py",
            "line": 12,
            "side": None,
            "commit_sha": None,
            "pr_url": None,
            "metadata": {},
        },
        "metadata": {},
    }


def test_task_result_payload_serializes_token_usage_for_json_storage() -> None:
    payload = TaskResultPayload(
        summary="Execution completed",
        pr_url="https://example.test/pr/42",
        token_usage=[
            {
                "model": "gpt-5.4",
                "provider": "openai",
                "input_tokens": 120,
                "output_tokens": 80,
                "cached_tokens": 20,
                "estimated": True,
                "cost_usd": Decimal("0.125"),
            }
        ],
        metadata={"changed_files": 3},
    )

    assert payload.model_dump(mode="json") == {
        "summary": "Execution completed",
        "details": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_title": None,
        "pr_url": "https://example.test/pr/42",
        "tracker_comment": None,
        "links": [],
        "token_usage": [
            {
                "model": "gpt-5.4",
                "provider": "openai",
                "input_tokens": 120,
                "output_tokens": 80,
                "cached_tokens": 20,
                "estimated": True,
                "cost_usd": "0.125",
            }
        ],
        "metadata": {"changed_files": 3},
    }


def test_schemas_reject_non_json_metadata_values() -> None:
    with pytest.raises(ValidationError):
        TaskInputPayload.model_validate(
            {
                "instructions": "Run update",
                "metadata": {"not_json": object()},
            }
        )


def test_tracker_task_reuses_shared_task_context_and_enums() -> None:
    tracker_task = TrackerTask(
        external_id="TASK-17",
        status=TaskStatus.PROCESSING,
        task_type=TaskType.EXECUTE,
        context=TaskContext(
            title="Implement tracker boundary",
            references=[{"label": "spec", "url": "https://example.test/spec"}],
        ),
        metadata={"tracker": "mock"},
    )

    assert tracker_task.model_dump(mode="json") == {
        "external_id": "TASK-17",
        "parent_external_id": None,
        "status": "processing",
        "task_type": "execute",
        "context": {
            "title": "Implement tracker boundary",
            "description": None,
            "acceptance_criteria": [],
            "references": [{"label": "spec", "url": "https://example.test/spec"}],
            "metadata": {},
        },
        "input_payload": None,
        "repo_url": None,
        "repo_ref": None,
        "workspace_key": None,
        "metadata": {"tracker": "mock"},
    }


def test_tracker_create_payload_and_fetch_query_apply_mvp_defaults() -> None:
    payload = TrackerTaskCreatePayload(
        context=TaskContext(title="Create deliver task"),
        repo_url="https://example.test/repo.git",
    )
    query = TrackerFetchTasksQuery()

    assert payload.model_dump(mode="json") == {
        "context": {
            "title": "Create deliver task",
            "description": None,
            "acceptance_criteria": [],
            "references": [],
            "metadata": {},
        },
        "task_type": None,
        "status": "new",
        "input_payload": None,
        "repo_url": "https://example.test/repo.git",
        "repo_ref": None,
        "workspace_key": None,
        "metadata": {},
    }
    assert query.model_dump(mode="json") == {
        "statuses": ["new"],
        "task_type": None,
        "limit": 100,
    }


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (TaskContext, {"title": "Task", "unexpected": True}),
        (
            PrFeedbackPayload,
            {"pr_external_id": "42", "comment_id": "c-7", "body": "ok", "line": 0},
        ),
        (
            TaskResultPayload,
            {
                "summary": "Done",
                "token_usage": [{"model": "gpt-5.4", "provider": "openai", "input_tokens": -1}],
            },
        ),
        (
            TrackerLinksAttachPayload,
            {"external_task_id": "TASK-17", "links": []},
        ),
        (
            TrackerFetchTasksQuery,
            {"limit": 0},
        ),
    ],
)
def test_schemas_validate_mvp_constraints(schema: object, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
