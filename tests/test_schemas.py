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
    TaskArtifactsPayload,
    TaskClassificationPayload,
    TaskContext,
    TaskDeliveryPayload,
    TaskEstimatePayload,
    TaskHandoffPayload,
    TaskInputPayload,
    TaskResultPayload,
    TaskRoutingPayload,
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
        "references": [{"label": "spec", "url": "https://example.test/spec", "origin": None}],
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
        "schema_version": 1,
        "action": None,
        "role": None,
        "handoff": None,
        "expected_output": None,
        "constraints": {},
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
        "schema_version": 1,
        "outcome": None,
        "classification": None,
        "estimate": None,
        "routing": None,
        "delivery": None,
        "artifacts": None,
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
            "references": [{"label": "spec", "url": "https://example.test/spec", "origin": None}],
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


@pytest.mark.parametrize(
    "action",
    ["triage", "research", "implementation", "respond_pr", "deliver"],
)
def test_task_input_payload_action_field_accepts_all_values(action: str) -> None:
    payload = TaskInputPayload(action=action)  # type: ignore[arg-type]
    assert payload.action == action


def test_task_input_payload_handoff_field_optional() -> None:
    payload_none = TaskInputPayload()
    assert payload_none.handoff is None

    payload_with_handoff = TaskInputPayload(
        handoff=TaskHandoffPayload(
            from_task_id=42,
            from_role="triage",
            reason="route to research",
            decision_ref="docs/decisions/triage.md",
            brief_markdown="## brief",
        )
    )
    assert payload_with_handoff.handoff is not None
    assert payload_with_handoff.handoff.from_task_id == 42
    assert payload_with_handoff.handoff.from_role == "triage"


def test_task_input_payload_constraints_default_empty_dict() -> None:
    payload = TaskInputPayload()
    assert payload.constraints == {}


def test_task_input_payload_schema_version_default_1() -> None:
    payload = TaskInputPayload()
    assert payload.schema_version == 1


def test_task_input_payload_backwards_compat_without_new_fields() -> None:
    payload = TaskInputPayload(
        instructions="Run update",
        base_branch="main",
        branch_name="feature/x",
        commit_message_hint="task01 ok",
        metadata={"k": "v"},
    )
    assert payload.instructions == "Run update"
    assert payload.base_branch == "main"
    assert payload.branch_name == "feature/x"
    assert payload.commit_message_hint == "task01 ok"
    assert payload.metadata == {"k": "v"}
    assert payload.schema_version == 1
    assert payload.action is None
    assert payload.role is None
    assert payload.handoff is None
    assert payload.expected_output is None
    assert payload.constraints == {}


@pytest.mark.parametrize("story_points", [1, 2, 3, 5, 8, 13])
def test_task_result_payload_estimate_story_points_literal_validates_set(
    story_points: int,
) -> None:
    estimate = TaskEstimatePayload(
        story_points=story_points,  # type: ignore[arg-type]
        complexity="low",
        can_take_in_work=True,
    )
    assert estimate.story_points == story_points


@pytest.mark.parametrize("invalid_points", [4, 6, 10])
def test_task_result_payload_estimate_story_points_rejects_4_6_10(
    invalid_points: int,
) -> None:
    with pytest.raises(ValidationError):
        TaskEstimatePayload.model_validate(
            {
                "story_points": invalid_points,
                "complexity": "low",
                "can_take_in_work": True,
            }
        )


@pytest.mark.parametrize(
    "task_kind",
    ["research", "implementation", "clarification", "review_response", "rejected"],
)
def test_task_result_payload_classification_task_kind_literal(task_kind: str) -> None:
    classification = TaskClassificationPayload(task_kind=task_kind)  # type: ignore[arg-type]
    assert classification.task_kind == task_kind

    with pytest.raises(ValidationError):
        TaskClassificationPayload.model_validate({"task_kind": "unknown"})


@pytest.mark.parametrize(
    "next_task_type",
    ["execute", "deliver", "pr_feedback"],
)
def test_task_result_payload_routing_next_task_type_literal(next_task_type: str) -> None:
    routing = TaskRoutingPayload(next_task_type=next_task_type)  # type: ignore[arg-type]
    assert routing.next_task_type == next_task_type

    with pytest.raises(ValidationError):
        TaskRoutingPayload.model_validate({"next_task_type": "fetch"})


def test_task_result_payload_delivery_tracker_status_uses_task_status_enum() -> None:
    delivery = TaskDeliveryPayload(tracker_status=TaskStatus.DONE)
    assert delivery.tracker_status is TaskStatus.DONE

    delivery_from_value = TaskDeliveryPayload.model_validate({"tracker_status": "processing"})
    assert delivery_from_value.tracker_status is TaskStatus.PROCESSING

    with pytest.raises(ValidationError):
        TaskDeliveryPayload.model_validate({"tracker_status": "not_a_status"})


@pytest.mark.parametrize(
    "escalation_kind",
    ["rfi", "decomposition", "system_design"],
)
def test_task_result_payload_delivery_escalation_kind_literal(escalation_kind: str) -> None:
    delivery = TaskDeliveryPayload(escalation_kind=escalation_kind)  # type: ignore[arg-type]
    assert delivery.escalation_kind == escalation_kind

    with pytest.raises(ValidationError):
        TaskDeliveryPayload.model_validate({"escalation_kind": "other"})


def test_task_result_payload_artifacts_optional_fields() -> None:
    artifacts = TaskArtifactsPayload()
    assert artifacts.branch_name is None
    assert artifacts.commit_sha is None
    assert artifacts.pr_url is None

    populated = TaskArtifactsPayload(
        branch_name="feature/x",
        commit_sha="abc123",
        pr_url="https://example.test/pr/1",
    )
    assert populated.branch_name == "feature/x"
    assert populated.commit_sha == "abc123"
    assert populated.pr_url == "https://example.test/pr/1"


@pytest.mark.parametrize(
    "outcome",
    ["completed", "routed", "needs_clarification", "blocked", "failed"],
)
def test_task_result_payload_outcome_literal(outcome: str) -> None:
    payload = TaskResultPayload(summary="ok", outcome=outcome)  # type: ignore[arg-type]
    assert payload.outcome == outcome

    with pytest.raises(ValidationError):
        TaskResultPayload.model_validate({"summary": "ok", "outcome": "unknown"})


def test_task_result_payload_schema_version_default_1() -> None:
    payload = TaskResultPayload(summary="ok")
    assert payload.schema_version == 1


def test_task_result_payload_backwards_compat_without_new_fields() -> None:
    payload = TaskResultPayload(summary="x")
    assert payload.summary == "x"
    assert payload.schema_version == 1
    assert payload.outcome is None
    assert payload.classification is None
    assert payload.estimate is None
    assert payload.routing is None
    assert payload.delivery is None
    assert payload.artifacts is None
    assert payload.details is None
    assert payload.branch_name is None
    assert payload.commit_sha is None
    assert payload.pr_title is None
    assert payload.pr_url is None
    assert payload.tracker_comment is None
    assert payload.links == []
    assert payload.token_usage == []
    assert payload.metadata == {}


def test_task_handoff_payload_required_fields() -> None:
    handoff = TaskHandoffPayload(from_task_id=7, from_role="triage")
    assert handoff.from_task_id == 7
    assert handoff.from_role == "triage"
    assert handoff.reason is None
    assert handoff.decision_ref is None
    assert handoff.brief_markdown is None

    with pytest.raises(ValidationError):
        TaskHandoffPayload.model_validate({"from_role": "triage"})

    with pytest.raises(ValidationError):
        TaskHandoffPayload.model_validate({"from_task_id": 7})


@pytest.mark.parametrize(
    ("schema", "valid_payload"),
    [
        (
            TaskHandoffPayload,
            {"from_task_id": 1, "from_role": "triage"},
        ),
        (
            TaskClassificationPayload,
            {"task_kind": "research"},
        ),
        (
            TaskEstimatePayload,
            {"story_points": 1, "complexity": "trivial", "can_take_in_work": True},
        ),
        (
            TaskRoutingPayload,
            {},
        ),
        (
            TaskDeliveryPayload,
            {},
        ),
        (
            TaskArtifactsPayload,
            {},
        ),
    ],
)
def test_extra_forbid_on_all_new_models(
    schema: object,
    valid_payload: dict[str, object],
) -> None:
    schema.model_validate(valid_payload)  # baseline succeeds
    with pytest.raises(ValidationError):
        schema.model_validate({**valid_payload, "unexpected_extra_field": True})
