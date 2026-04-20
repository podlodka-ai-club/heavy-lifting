from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TaskType(StrEnum):
    FETCH = "fetch"
    EXECUTE = "execute"
    DELIVER = "deliver"
    PR_FEEDBACK = "pr_feedback"


class TaskStatus(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


TASK_TYPE_VALUES = tuple(task_type.value for task_type in TaskType)
TASK_STATUS_VALUES = tuple(status.value for status in TaskStatus)

task_type_enum = Enum(
    TaskType,
    name="task_type_enum",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
    values_callable=lambda members: [member.value for member in members],
)

task_status_enum = Enum(
    TaskStatus,
    name="task_status_enum",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
    values_callable=lambda members: [member.value for member in members],
)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_task_type_updated_at", "status", "task_type", "updated_at"),
        Index("ix_tasks_root_id", "root_id"),
        Index("ix_tasks_parent_id", "parent_id"),
        Index("ix_tasks_pr_external_id", "pr_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    task_type: Mapped[TaskType] = mapped_column(task_type_enum, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum,
        nullable=False,
        default=TaskStatus.NEW,
        server_default=TaskStatus.NEW.value,
    )
    tracker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_parent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    repo_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )

    root: Mapped[Task | None] = relationship(
        "Task",
        foreign_keys=[root_id],
        remote_side="Task.id",
    )
    parent: Mapped[Task | None] = relationship(
        "Task",
        foreign_keys=[parent_id],
        remote_side="Task.id",
        back_populates="children",
    )
    children: Mapped[list[Task]] = relationship(
        "Task",
        foreign_keys=[parent_id],
        back_populates="parent",
    )


__all__ = [
    "Base",
    "TASK_STATUS_VALUES",
    "TASK_TYPE_VALUES",
    "Task",
    "TaskStatus",
    "TaskType",
    "task_status_enum",
    "task_type_enum",
]
