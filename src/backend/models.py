from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.task_constants import TASK_STATUS_VALUES, TASK_TYPE_VALUES, TaskStatus, TaskType


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


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
    token_usage_entries: Mapped[list[TokenUsage]] = relationship(
        back_populates="task",
    )
    agent_feedback_entries: Mapped[list[AgentFeedbackEntry]] = relationship(
        back_populates="task",
    )


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (
        CheckConstraint("input_tokens >= 0", name="ck_token_usage_input_tokens_non_negative"),
        CheckConstraint("output_tokens >= 0", name="ck_token_usage_output_tokens_non_negative"),
        CheckConstraint("cached_tokens >= 0", name="ck_token_usage_cached_tokens_non_negative"),
        CheckConstraint("cost_usd >= 0", name="ck_token_usage_cost_usd_non_negative"),
        Index("ix_token_usage_task_id", "task_id"),
        Index("ix_token_usage_provider_model_created_at", "provider", "model", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    cached_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    estimated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )

    task: Mapped[Task] = relationship(back_populates="token_usage_entries")


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"
    __table_args__ = (
        UniqueConstraint("prompt_key", name="uq_agent_prompts_prompt_key"),
        Index("ix_agent_prompts_prompt_key", "prompt_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source_path: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
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


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    __table_args__ = (
        UniqueConstraint("setting_key", name="uq_application_settings_setting_key"),
        CheckConstraint(
            "value_type IN ('int', 'string')",
            name="ck_application_settings_value_type",
        ),
        Index("ix_application_settings_setting_key", "setting_key"),
        Index("ix_application_settings_display_order", "display_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(100), nullable=False)
    env_var: Mapped[str] = mapped_column(String(100), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    default_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
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


class AgentFeedbackEntry(Base):
    __tablename__ = "agent_feedback_entries"
    __table_args__ = (
        Index("ix_agent_feedback_entries_task_id", "task_id"),
        Index("ix_agent_feedback_entries_tag_created_at", "tag", "created_at"),
        Index(
            "ix_agent_feedback_entries_task_type_created_at",
            "task_type",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    root_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[TaskType] = mapped_column(task_type_enum, nullable=False)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="agent",
        server_default="agent",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="other",
        server_default="other",
    )
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    entry_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )

    task: Mapped[Task] = relationship(back_populates="agent_feedback_entries")


__all__ = [
    "AgentFeedbackEntry",
    "AgentPrompt",
    "ApplicationSetting",
    "Base",
    "TASK_STATUS_VALUES",
    "TASK_TYPE_VALUES",
    "Task",
    "TaskStatus",
    "TaskType",
    "TokenUsage",
    "task_status_enum",
    "task_type_enum",
]
