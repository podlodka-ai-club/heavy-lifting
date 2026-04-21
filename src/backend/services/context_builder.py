from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from backend.models import Task
from backend.schemas import (
    SchemaModel,
    TaskContext,
    TaskInputPayload,
    TaskResultPayload,
)
from backend.task_constants import TaskType
from backend.task_context import EffectiveTaskContext, FeedbackHistoryEntry, TaskChainEntry

SchemaModelT = TypeVar("SchemaModelT", bound=SchemaModel)


def parse_task_context(task: Task) -> TaskContext | None:
    return _parse_task_field(task=task, field_name="context", model=TaskContext)


def parse_task_input_payload(task: Task) -> TaskInputPayload | None:
    return _parse_task_field(task=task, field_name="input_payload", model=TaskInputPayload)


def parse_task_result_payload(task: Task) -> TaskResultPayload | None:
    return _parse_task_field(task=task, field_name="result_payload", model=TaskResultPayload)


@dataclass(slots=True)
class ContextBuilder:
    name: str = "context-builder"

    def build_for_task(self, *, task: Task, task_chain: Sequence[Task]) -> EffectiveTaskContext:
        if not task_chain:
            raise ValueError("task_chain must not be empty")

        ordered_tasks = _normalize_tasks(task_chain)
        task_by_id = {chain_task.id: chain_task for chain_task in ordered_tasks}

        try:
            current_task = task_by_id[task.id]
        except KeyError as exc:
            raise ValueError(f"Task {task.id} is not part of the provided chain") from exc

        root_entry = self._resolve_root_entry(current_task=current_task, task_by_id=task_by_id)
        lineage = self._build_lineage(current_task=current_task, task_by_id=task_by_id)
        current_entry = lineage[-1]

        fetch_entry = _find_first_task(lineage, TaskType.FETCH)
        execute_entry = _find_first_task(lineage, TaskType.EXECUTE)
        deliver_entry = current_entry if current_entry.task.task_type == TaskType.DELIVER else None
        feedback_entry = (
            current_entry if current_entry.task.task_type == TaskType.PR_FEEDBACK else None
        )

        self._validate_flow(
            current_entry=current_entry, fetch_entry=fetch_entry, execute_entry=execute_entry
        )

        current_index = {chain_task.id: index for index, chain_task in enumerate(ordered_tasks)}[
            task.id
        ]
        feedback_history = self._build_feedback_history(
            ordered_tasks=ordered_tasks,
            execute_entry=execute_entry,
            current_task=current_task,
            current_index=current_index,
        )

        return EffectiveTaskContext(
            flow_type=current_entry.task.task_type,
            root_task=root_entry,
            current_task=current_entry,
            lineage=lineage,
            fetch_task=fetch_entry,
            execute_task=execute_entry,
            deliver_task=deliver_entry,
            feedback_task=feedback_entry,
            feedback_history=feedback_history,
            repo_url=_resolve_task_attr(lineage, "repo_url"),
            repo_ref=_resolve_task_attr(lineage, "repo_ref"),
            workspace_key=_resolve_task_attr(lineage, "workspace_key"),
            branch_name=_first_non_empty(
                _resolve_task_attr(lineage, "branch_name"),
                _resolve_input_attr(lineage, "branch_name"),
                execute_entry.result_payload.branch_name
                if execute_entry and execute_entry.result_payload
                else None,
            ),
            base_branch=_resolve_input_attr(lineage, "base_branch"),
            pr_external_id=_first_non_empty(
                _resolve_task_attr(lineage, "pr_external_id"),
                feedback_entry.input_payload.pr_feedback.pr_external_id
                if feedback_entry
                and feedback_entry.input_payload
                and feedback_entry.input_payload.pr_feedback
                else None,
            ),
            pr_url=_first_non_empty(
                _resolve_task_attr(lineage, "pr_url"),
                execute_entry.result_payload.pr_url
                if execute_entry and execute_entry.result_payload
                else None,
                feedback_entry.input_payload.pr_feedback.pr_url
                if feedback_entry
                and feedback_entry.input_payload
                and feedback_entry.input_payload.pr_feedback
                else None,
            ),
            instructions=_resolve_input_attr(lineage, "instructions"),
            commit_message_hint=_resolve_input_attr(lineage, "commit_message_hint"),
        )

    def _resolve_root_entry(
        self,
        *,
        current_task: Task,
        task_by_id: dict[int, Task],
    ) -> TaskChainEntry:
        root_id = current_task.root_id or current_task.id
        root_task = task_by_id.get(root_id)
        if root_task is None:
            raise ValueError(f"Task chain is missing root task {root_id}")
        return _task_chain_entry(root_task)

    def _build_lineage(
        self,
        *,
        current_task: Task,
        task_by_id: dict[int, Task],
    ) -> tuple[TaskChainEntry, ...]:
        lineage: list[TaskChainEntry] = []
        cursor: Task | None = current_task

        while cursor is not None:
            lineage.append(_task_chain_entry(cursor))
            parent_id = cursor.parent_id
            if parent_id is None:
                cursor = None
                continue

            cursor = task_by_id.get(parent_id)
            if cursor is None:
                raise ValueError(f"Task chain is missing parent task {parent_id}")

        lineage.reverse()
        return tuple(lineage)

    def _build_feedback_history(
        self,
        *,
        ordered_tasks: Sequence[Task],
        execute_entry: TaskChainEntry | None,
        current_task: Task,
        current_index: int,
    ) -> tuple[FeedbackHistoryEntry, ...]:
        if execute_entry is None:
            return ()

        history: list[FeedbackHistoryEntry] = []
        for index, task in enumerate(ordered_tasks):
            if index >= current_index:
                break
            if task.task_type != TaskType.PR_FEEDBACK:
                continue
            if task.parent_id != execute_entry.task.id:
                continue
            if task.id == current_task.id:
                continue
            entry = _task_chain_entry(task)
            if entry.input_payload is None or entry.input_payload.pr_feedback is None:
                continue
            history.append(
                FeedbackHistoryEntry(
                    task_id=task.id,
                    external_task_id=task.external_task_id,
                    feedback=entry.input_payload.pr_feedback,
                    result_payload=entry.result_payload,
                )
            )

        return tuple(history)

    def _validate_flow(
        self,
        *,
        current_entry: TaskChainEntry,
        fetch_entry: TaskChainEntry | None,
        execute_entry: TaskChainEntry | None,
    ) -> None:
        task_type = current_entry.task.task_type

        if task_type not in {TaskType.EXECUTE, TaskType.DELIVER, TaskType.PR_FEEDBACK}:
            raise ValueError(f"Unsupported flow for task type {task_type.value}")

        if fetch_entry is None:
            raise ValueError("Task chain must include a fetch ancestor")

        if task_type == TaskType.EXECUTE:
            return

        if execute_entry is None:
            raise ValueError(f"Task type {task_type.value} requires an execute ancestor")

        if task_type == TaskType.PR_FEEDBACK:
            input_payload = current_entry.input_payload
            if input_payload is None or input_payload.pr_feedback is None:
                raise ValueError("pr_feedback task requires input_payload.pr_feedback")


def _normalize_tasks(tasks: Iterable[Task]) -> list[Task]:
    normalized_tasks: list[Task] = []
    for task in tasks:
        if task.id is None:
            raise ValueError("Task chain cannot contain transient tasks without an id")
        normalized_tasks.append(task)
    return sorted(normalized_tasks, key=lambda chain_task: chain_task.id)


def _task_chain_entry(task: Task) -> TaskChainEntry:
    entry = TaskChainEntry(task=task)
    object.__setattr__(entry, "context", parse_task_context(task))
    object.__setattr__(entry, "input_payload", parse_task_input_payload(task))
    object.__setattr__(entry, "result_payload", parse_task_result_payload(task))
    return entry


def _parse_task_field(
    *, task: Task, field_name: str, model: type[SchemaModelT]
) -> SchemaModelT | None:
    payload = getattr(task, field_name)
    if payload is None:
        return None

    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"Task {task.id} has invalid {field_name}") from exc


def _find_first_task(
    lineage: Sequence[TaskChainEntry], task_type: TaskType
) -> TaskChainEntry | None:
    for entry in lineage:
        if entry.task.task_type == task_type:
            return entry
    return None


def _resolve_task_attr(lineage: Sequence[TaskChainEntry], field_name: str) -> str | None:
    return _first_non_empty(*(getattr(entry.task, field_name) for entry in reversed(lineage)))


def _resolve_input_attr(lineage: Sequence[TaskChainEntry], field_name: str) -> str | None:
    values = []
    for entry in reversed(lineage):
        if entry.input_payload is None:
            continue
        values.append(getattr(entry.input_payload, field_name))
    return _first_non_empty(*values)


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


__all__ = [
    "ContextBuilder",
    "EffectiveTaskContext",
    "FeedbackHistoryEntry",
    "TaskChainEntry",
    "parse_task_context",
    "parse_task_input_payload",
    "parse_task_result_payload",
]
