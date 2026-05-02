from __future__ import annotations

from collections.abc import Sequence

from backend.models import Task
from backend.task_constants import TaskType


def resolve_tracker_external_task_id(*, task: Task, task_chain: Sequence[Task]) -> str | None:
    if task.id is None:
        raise ValueError("Task must be persisted before tracker resolution")

    task_by_id = {
        chain_task.id: chain_task for chain_task in task_chain if chain_task.id is not None
    }
    current_task = task_by_id.get(task.id)
    if current_task is None:
        raise ValueError(f"Task {task.id} is not part of the provided chain")

    lineage = _build_lineage(current_task=current_task, task_by_id=task_by_id)
    root_task = lineage[0]
    fetch_task = _find_first_task(lineage=lineage, task_type=TaskType.FETCH)
    execute_task = _find_first_task(lineage=lineage, task_type=TaskType.EXECUTE)

    current_tracker_id = None
    if current_task.task_type in {TaskType.EXECUTE, TaskType.DELIVER, TaskType.TRACKER_FEEDBACK}:
        current_tracker_id = current_task.external_parent_id
    elif current_task.task_type == TaskType.FETCH:
        current_tracker_id = current_task.external_task_id

    candidates = (
        current_tracker_id,
        execute_task.external_parent_id if execute_task is not None else None,
        fetch_task.external_task_id if fetch_task is not None else None,
        root_task.external_task_id,
    )
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _build_lineage(*, current_task: Task, task_by_id: dict[int, Task]) -> tuple[Task, ...]:
    lineage: list[Task] = []
    cursor: Task | None = current_task

    while cursor is not None:
        lineage.append(cursor)
        parent_id = cursor.parent_id
        if parent_id is None:
            break
        cursor = task_by_id.get(parent_id)
        if cursor is None:
            raise ValueError(f"Task chain is missing parent task {parent_id}")

    lineage.reverse()
    return tuple(lineage)


def _find_first_task(*, lineage: Sequence[Task], task_type: TaskType) -> Task | None:
    for entry in lineage:
        if entry.task_type == task_type:
            return entry
    return None


__all__ = ["resolve_tracker_external_task_id"]
