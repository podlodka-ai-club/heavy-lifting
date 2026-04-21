from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Task, TokenUsage
from backend.task_constants import TaskStatus, TaskType

type JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskCreateParams:
    task_type: TaskType
    status: TaskStatus = TaskStatus.NEW
    parent_id: int | None = None
    root_id: int | None = None
    tracker_name: str | None = None
    external_task_id: str | None = None
    external_parent_id: str | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    workspace_key: str | None = None
    branch_name: str | None = None
    pr_external_id: str | None = None
    pr_url: str | None = None
    role: str | None = None
    context: JsonObject | None = None
    input_payload: JsonObject | None = None
    result_payload: JsonObject | None = None
    error: str | None = None
    attempt: int = 0


@dataclass(frozen=True, slots=True)
class TokenUsageCreateParams:
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False
    cost_usd: Decimal = Decimal("0")


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_task(self, params: TaskCreateParams) -> Task:
        if params.parent_id is None and params.root_id is not None:
            raise ValueError("root_id cannot be set without parent_id")

        resolved_root_id = params.root_id

        if params.parent_id is not None:
            parent = self._session.get(Task, params.parent_id)
            if parent is None:
                raise ValueError(f"Parent task {params.parent_id} does not exist")

            parent_root_id = parent.root_id or parent.id
            if resolved_root_id is None:
                resolved_root_id = parent_root_id
            elif resolved_root_id != parent_root_id:
                raise ValueError("root_id must match the parent task chain")

        task = Task(
            root_id=resolved_root_id,
            parent_id=params.parent_id,
            task_type=params.task_type,
            status=params.status,
            tracker_name=params.tracker_name,
            external_task_id=params.external_task_id,
            external_parent_id=params.external_parent_id,
            repo_url=params.repo_url,
            repo_ref=params.repo_ref,
            workspace_key=params.workspace_key,
            branch_name=params.branch_name,
            pr_external_id=params.pr_external_id,
            pr_url=params.pr_url,
            role=params.role,
            context=params.context,
            input_payload=params.input_payload,
            result_payload=params.result_payload,
            error=params.error,
            attempt=params.attempt,
        )
        self._session.add(task)
        self._session.flush()

        if task.root_id is None:
            task.root_id = task.id
            self._session.flush()

        return task

    def load_task_chain(self, root_id: int) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.root_id == root_id)
            .order_by(Task.created_at.asc(), Task.id.asc())
        )
        return list(self._session.execute(statement).scalars())

    def poll_task(
        self,
        *,
        task_type: TaskType,
        status: TaskStatus = TaskStatus.NEW,
        claimed_status: TaskStatus | None = TaskStatus.PROCESSING,
    ) -> Task | None:
        statement = (
            select(Task)
            .where(Task.task_type == task_type, Task.status == status)
            .order_by(Task.updated_at.asc(), Task.id.asc())
            .with_for_update(skip_locked=True)
        )
        task = self._session.execute(statement).scalars().first()
        if task is None:
            return None

        if claimed_status is not None and task.status != claimed_status:
            task.status = claimed_status
            self._session.flush()

        return task

    def find_execute_task_by_pr_external_id(self, pr_external_id: str) -> Task | None:
        statement = (
            select(Task)
            .where(
                Task.task_type == TaskType.EXECUTE,
                Task.pr_external_id == pr_external_id,
            )
            .order_by(Task.id.asc())
        )
        return self._session.execute(statement).scalars().first()

    def find_fetch_task_by_tracker_task(
        self,
        *,
        tracker_name: str,
        external_task_id: str,
    ) -> Task | None:
        statement = (
            select(Task)
            .where(
                Task.task_type == TaskType.FETCH,
                Task.tracker_name == tracker_name,
                Task.external_task_id == external_task_id,
            )
            .order_by(Task.id.asc())
        )
        return self._session.execute(statement).scalars().first()

    def find_child_task(self, *, parent_id: int, task_type: TaskType) -> Task | None:
        statement = (
            select(Task)
            .where(
                Task.parent_id == parent_id,
                Task.task_type == task_type,
            )
            .order_by(Task.id.asc())
        )
        return self._session.execute(statement).scalars().first()

    def record_token_usage(self, *, task_id: int, usage: TokenUsageCreateParams) -> TokenUsage:
        entry = TokenUsage(
            task_id=task_id,
            model=usage.model,
            provider=usage.provider,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            estimated=usage.estimated,
            cost_usd=usage.cost_usd,
        )
        self._session.add(entry)
        self._session.flush()
        return entry


__all__ = [
    "TaskCreateParams",
    "TaskRepository",
    "TokenUsageCreateParams",
]
