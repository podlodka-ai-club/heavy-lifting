from __future__ import annotations

from dataclasses import dataclass, field

from backend.models import Task
from backend.schemas import PrFeedbackPayload, TaskContext, TaskInputPayload, TaskResultPayload
from backend.task_constants import TaskType


@dataclass(frozen=True, slots=True)
class TaskChainEntry:
    task: Task
    context: TaskContext | None = field(init=False)
    input_payload: TaskInputPayload | None = field(init=False)
    result_payload: TaskResultPayload | None = field(init=False)


@dataclass(frozen=True, slots=True)
class FeedbackHistoryEntry:
    task_id: int
    external_task_id: str | None
    feedback: PrFeedbackPayload
    result_payload: TaskResultPayload | None


@dataclass(frozen=True, slots=True)
class EffectiveTaskContext:
    flow_type: TaskType
    root_task: TaskChainEntry
    current_task: TaskChainEntry
    lineage: tuple[TaskChainEntry, ...]
    fetch_task: TaskChainEntry | None
    execute_task: TaskChainEntry | None
    deliver_task: TaskChainEntry | None
    feedback_task: TaskChainEntry | None
    feedback_history: tuple[FeedbackHistoryEntry, ...]
    repo_url: str | None
    repo_ref: str | None
    workspace_key: str | None
    branch_name: str | None
    base_branch: str | None
    pr_external_id: str | None
    pr_url: str | None
    instructions: str | None
    commit_message_hint: str | None

    @property
    def tracker_context(self) -> TaskContext | None:
        return self.fetch_task.context if self.fetch_task is not None else self.root_task.context

    @property
    def execution_context(self) -> TaskContext | None:
        if self.execute_task is not None and self.execute_task.context is not None:
            return self.execute_task.context
        return self.current_task.context

    @property
    def current_feedback(self) -> PrFeedbackPayload | None:
        if self.feedback_task is None or self.feedback_task.input_payload is None:
            return None
        return self.feedback_task.input_payload.pr_feedback

    @property
    def execute_result(self) -> TaskResultPayload | None:
        if self.execute_task is None:
            return None
        return self.execute_task.result_payload


__all__ = ["EffectiveTaskContext", "FeedbackHistoryEntry", "TaskChainEntry"]
