from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.schemas import (
    PrFeedbackPayload,
    ScmCommitChangesPayload,
    ScmPullRequestCreatePayload,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmReadPrFeedbackQuery,
    ScmWorkspaceEnsurePayload,
    TaskContext,
    TaskInputPayload,
    TaskResultPayload,
    TrackerCommentPayload,
    TrackerEstimatedSelectionQuery,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerReadCommentsQuery,
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
            "url": None,
            "path": "src/backend/schemas.py",
            "line": 12,
            "side": None,
            "commit_sha": None,
            "pr_url": None,
            "metadata": {},
        },
        "tracker_feedback": None,
        "metadata": {},
    }


def test_task_input_payload_supports_tracker_feedback() -> None:
    payload = TaskInputPayload(
        instructions="Reply in the same tracker thread.",
        tracker_feedback=TrackerCommentPayload(
            external_task_id="LIN-42",
            comment_id="comment-9",
            body="Can you justify the estimate?",
            author="pm",
            url="https://linear.app/comment/9",
        ),
    )

    assert payload.model_dump(mode="json") == {
        "instructions": "Reply in the same tracker thread.",
        "base_branch": None,
        "branch_name": None,
        "commit_message_hint": None,
        "pr_feedback": None,
        "tracker_feedback": {
            "external_task_id": "LIN-42",
            "comment_id": "comment-9",
            "body": "Can you justify the estimate?",
            "author": "pm",
            "url": "https://linear.app/comment/9",
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


def test_schemas_reject_nested_non_string_json_keys() -> None:
    with pytest.raises(ValidationError):
        TaskContext.model_validate(
            {
                "title": "Task",
                "metadata": {"nested": {1: "bad key"}},
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


def test_tracker_fetch_query_serializes_estimated_selection_when_provided() -> None:
    query = TrackerFetchTasksQuery(
        estimated_selection=TrackerEstimatedSelectionQuery(
            max_story_points=5,
            can_take_in_work=True,
            taken_in_work=False,
            only_parent_tasks=True,
        ),
    )

    assert query.model_dump(mode="json") == {
        "statuses": ["new"],
        "task_type": None,
        "estimated_selection": {
            "max_story_points": 5,
            "can_take_in_work": True,
            "taken_in_work": False,
            "only_parent_tasks": True,
        },
        "limit": 100,
    }


def test_scm_pull_request_feedback_reuses_shared_feedback_fields() -> None:
    feedback = ScmPullRequestFeedback(
        pr_external_id="42",
        comment_id="comment-7",
        body="Please cover this path with tests.",
        author="reviewer",
        path="src/backend/protocols/scm.py",
        line=18,
        pr_url="https://example.test/repo/pull/42",
        pr_metadata=ScmPullRequestMetadata(
            execute_task_external_id="TASK-18",
            tracker_name="mock-tracker",
            workspace_key="repo-1",
            repo_url="https://example.test/repo.git",
        ),
        metadata={"severity": "medium"},
    )

    assert feedback.model_dump(mode="json") == {
        "pr_external_id": "42",
        "comment_id": "comment-7",
        "body": "Please cover this path with tests.",
        "author": "reviewer",
        "url": None,
        "path": "src/backend/protocols/scm.py",
        "line": 18,
        "side": None,
        "commit_sha": None,
        "pr_url": "https://example.test/repo/pull/42",
        "metadata": {"severity": "medium"},
        "pr_metadata": {
            "execute_task_external_id": "TASK-18",
            "tracker_name": "mock-tracker",
            "workspace_key": "repo-1",
            "repo_url": "https://example.test/repo.git",
            "metadata": {},
        },
    }


def test_scm_payloads_apply_mvp_defaults() -> None:
    ensure_workspace = ScmWorkspaceEnsurePayload(
        repo_url="https://example.test/repo.git",
        workspace_key="repo-1",
    )
    commit = ScmCommitChangesPayload(
        workspace_key="repo-1",
        branch_name="task18/scm-boundary",
        message="task18 define scm boundary",
    )
    create_pr = ScmPullRequestCreatePayload(
        workspace_key="repo-1",
        branch_name="task18/scm-boundary",
        base_branch="main",
        title="Define SCM boundary",
        pr_metadata=ScmPullRequestMetadata(execute_task_external_id="TASK-18"),
    )
    feedback_query = ScmReadPrFeedbackQuery()
    tracker_comments_query = TrackerReadCommentsQuery(external_task_id="LIN-42")

    assert ensure_workspace.model_dump(mode="json") == {
        "repo_url": "https://example.test/repo.git",
        "workspace_key": "repo-1",
        "repo_ref": None,
        "metadata": {},
    }
    workspace_without_repo = ScmWorkspaceEnsurePayload(workspace_key="repo-1")
    assert workspace_without_repo.repo_url is None
    assert commit.model_dump(mode="json") == {
        "workspace_key": "repo-1",
        "branch_name": "task18/scm-boundary",
        "message": "task18 define scm boundary",
        "pre_run_head_sha": None,
        "metadata": {},
    }
    assert create_pr.model_dump(mode="json") == {
        "workspace_key": "repo-1",
        "branch_name": "task18/scm-boundary",
        "base_branch": "main",
        "title": "Define SCM boundary",
        "body": None,
        "pr_metadata": {
            "execute_task_external_id": "TASK-18",
            "tracker_name": None,
            "workspace_key": None,
            "repo_url": None,
            "metadata": {},
        },
        "metadata": {},
    }
    assert feedback_query.model_dump(mode="json") == {
        "workspace_key": None,
        "repo_url": None,
        "pr_external_id": None,
        "branch_name": None,
        "since_cursor": None,
        "page_cursor": None,
        "limit": 100,
    }
    assert tracker_comments_query.model_dump(mode="json") == {
        "external_task_id": "LIN-42",
        "since_cursor": None,
        "page_cursor": None,
        "limit": 100,
    }


def test_scm_workspace_ensure_payload_serializes_branch_name_when_provided() -> None:
    payload = ScmWorkspaceEnsurePayload(
        repo_url="https://example.test/repo.git",
        workspace_key="repo-1",
        repo_ref="main",
        branch_name="task18/scm-boundary",
    )

    assert payload.model_dump(mode="json") == {
        "repo_url": "https://example.test/repo.git",
        "workspace_key": "repo-1",
        "repo_ref": "main",
        "branch_name": "task18/scm-boundary",
        "metadata": {},
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
        (
            ScmCommitChangesPayload,
            {"workspace_key": "repo-1", "branch_name": "task18/scm", "message": ""},
        ),
        (
            ScmPullRequestMetadata,
            {"execute_task_external_id": "TASK-18", "metadata": {"bad": object()}},
        ),
        (
            ScmPullRequestCreatePayload,
            {
                "workspace_key": "repo-1",
                "branch_name": "task18/scm",
                "base_branch": "main",
                "title": "",
                "pr_metadata": {"execute_task_external_id": "TASK-18"},
            },
        ),
        (
            ScmReadPrFeedbackQuery,
            {"limit": 1001},
        ),
    ],
)
def test_schemas_validate_mvp_constraints(schema: object, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
