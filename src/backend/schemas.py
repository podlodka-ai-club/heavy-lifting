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


class TrackerFetchTasksQuery(SchemaModel):
    statuses: list[TaskStatus] = Field(default_factory=lambda: [TaskStatus.NEW])
    task_type: TaskType | None = None
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


class TrackerLinksAttachPayload(SchemaModel):
    external_task_id: str
    links: list[TaskLink] = Field(min_length=1)


__all__ = [
    "JsonObject",
    "JsonValue",
    "PrFeedbackPayload",
    "SchemaModel",
    "TrackerCommentCreatePayload",
    "TrackerCommentReference",
    "TrackerFetchTasksQuery",
    "TrackerLinksAttachPayload",
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
