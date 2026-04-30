from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from backend.task_constants import TaskStatus, TaskType


def _validate_json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return value

    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_value(item)
        return value

    raise ValueError("Value is not JSON-compatible")


type JsonValue = object
type JsonObject = Annotated[dict[str, JsonValue], AfterValidator(_validate_json_value)]


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskLink(SchemaModel):
    label: str
    url: str


class PrFeedbackPayload(SchemaModel):
    pr_external_id: str
    comment_id: str
    body: str
    author: str | None = None
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    side: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class TaskContext(SchemaModel):
    title: str
    description: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    references: list[TaskLink] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)


class TaskInputPayload(SchemaModel):
    instructions: str | None = None
    base_branch: str | None = None
    branch_name: str | None = None
    commit_message_hint: str | None = None
    pr_feedback: PrFeedbackPayload | None = None
    metadata: JsonObject = Field(default_factory=dict)


class TokenUsagePayload(SchemaModel):
    model: str
    provider: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    estimated: bool = False
    cost_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class AgentRetroFeedbackItem(SchemaModel):
    tag: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=100)
    category: str = Field(
        default="other",
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        min_length=1,
        max_length=50,
    )
    severity: str = Field(
        default="info",
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        min_length=1,
        max_length=50,
    )
    message: str = Field(min_length=1)
    suggested_action: str | None = None
    metadata: JsonObject | None = None


class TaskResultPayload(SchemaModel):
    summary: str
    details: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_title: str | None = None
    pr_url: str | None = None
    tracker_comment: str | None = None
    links: list[TaskLink] = Field(default_factory=list)
    token_usage: list[TokenUsagePayload] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)


class TrackerTaskReference(SchemaModel):
    external_id: str
    url: str | None = None


class TrackerCommentReference(SchemaModel):
    comment_id: str


class TrackerTask(SchemaModel):
    external_id: str
    parent_external_id: str | None = None
    status: TaskStatus = TaskStatus.NEW
    task_type: TaskType | None = None
    context: TaskContext
    input_payload: TaskInputPayload | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    workspace_key: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class TrackerEstimatedSelectionQuery(SchemaModel):
    max_story_points: int | None = Field(default=None, ge=0)
    can_take_in_work: bool | None = None
    taken_in_work: bool | None = None
    only_parent_tasks: bool = False


class TrackerFetchTasksQuery(SchemaModel):
    statuses: list[TaskStatus] = Field(default_factory=lambda: [TaskStatus.NEW])
    task_type: TaskType | None = None
    estimated_selection: TrackerEstimatedSelectionQuery | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    limit: int = Field(default=100, ge=1, le=1000)


class TrackerTaskCreatePayload(SchemaModel):
    context: TaskContext
    task_type: TaskType | None = None
    status: TaskStatus = TaskStatus.NEW
    input_payload: TaskInputPayload | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    workspace_key: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class TrackerSubtaskCreatePayload(TrackerTaskCreatePayload):
    parent_external_id: str


class TrackerCommentCreatePayload(SchemaModel):
    external_task_id: str
    body: str
    metadata: JsonObject = Field(default_factory=dict)


class TrackerStatusUpdatePayload(SchemaModel):
    external_task_id: str
    status: TaskStatus


class TrackerTaskSelectionClaimPayload(SchemaModel):
    external_task_id: str


class TrackerLinksAttachPayload(SchemaModel):
    external_task_id: str
    links: list[TaskLink] = Field(min_length=1)


class ScmWorkspaceEnsurePayload(SchemaModel):
    repo_url: str | None = None
    workspace_key: str
    repo_ref: str | None = None
    branch_name: str | None = Field(default=None, exclude_if=lambda value: value is None)
    metadata: JsonObject = Field(default_factory=dict)


class ScmWorkspace(SchemaModel):
    repo_url: str
    workspace_key: str
    repo_ref: str | None = None
    local_path: str
    branch_name: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ScmBranchCreatePayload(SchemaModel):
    workspace_key: str
    branch_name: str
    from_ref: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ScmBranchReference(SchemaModel):
    workspace_key: str
    branch_name: str
    from_ref: str | None = None
    head_commit_sha: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ScmCommitChangesPayload(SchemaModel):
    workspace_key: str
    branch_name: str
    message: str = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)


class ScmCommitReference(SchemaModel):
    workspace_key: str
    branch_name: str
    commit_sha: str
    message: str
    metadata: JsonObject = Field(default_factory=dict)


class ScmPushBranchPayload(SchemaModel):
    workspace_key: str
    branch_name: str
    remote_name: str = "origin"
    metadata: JsonObject = Field(default_factory=dict)


class ScmPushReference(SchemaModel):
    workspace_key: str
    branch_name: str
    remote_name: str
    remote_branch_name: str
    branch_url: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ScmPullRequestMetadata(SchemaModel):
    execute_task_external_id: str
    tracker_name: str | None = None
    workspace_key: str | None = None
    repo_url: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ScmPullRequestCreatePayload(SchemaModel):
    workspace_key: str
    branch_name: str
    base_branch: str
    title: str = Field(min_length=1)
    body: str | None = None
    pr_metadata: ScmPullRequestMetadata
    metadata: JsonObject = Field(default_factory=dict)


class ScmPullRequestReference(SchemaModel):
    external_id: str
    url: str
    workspace_key: str
    branch_name: str
    base_branch: str
    pr_metadata: ScmPullRequestMetadata
    metadata: JsonObject = Field(default_factory=dict)


class ScmPullRequestFeedback(PrFeedbackPayload):
    pr_metadata: ScmPullRequestMetadata


class ScmReadPrFeedbackResult(SchemaModel):
    items: list[ScmPullRequestFeedback] = Field(default_factory=list)
    next_page_cursor: str | None = None
    latest_cursor: str | None = None


class ScmReadPrFeedbackQuery(SchemaModel):
    workspace_key: str | None = None
    repo_url: str | None = None
    pr_external_id: str | None = None
    branch_name: str | None = None
    since_cursor: str | None = None
    page_cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


__all__ = [
    "JsonObject",
    "JsonValue",
    "AgentRetroFeedbackItem",
    "PrFeedbackPayload",
    "ScmBranchCreatePayload",
    "ScmBranchReference",
    "ScmCommitChangesPayload",
    "ScmCommitReference",
    "ScmPullRequestCreatePayload",
    "ScmPullRequestFeedback",
    "ScmPullRequestMetadata",
    "ScmPullRequestReference",
    "ScmReadPrFeedbackResult",
    "ScmPushBranchPayload",
    "ScmPushReference",
    "ScmReadPrFeedbackQuery",
    "SchemaModel",
    "ScmWorkspace",
    "ScmWorkspaceEnsurePayload",
    "TrackerCommentCreatePayload",
    "TrackerCommentReference",
    "TrackerEstimatedSelectionQuery",
    "TrackerFetchTasksQuery",
    "TrackerLinksAttachPayload",
    "TrackerTaskSelectionClaimPayload",
    "TrackerStatusUpdatePayload",
    "TrackerSubtaskCreatePayload",
    "TrackerTask",
    "TrackerTaskCreatePayload",
    "TrackerTaskReference",
    "TaskContext",
    "TaskInputPayload",
    "TaskLink",
    "TaskResultPayload",
    "TokenUsagePayload",
]
