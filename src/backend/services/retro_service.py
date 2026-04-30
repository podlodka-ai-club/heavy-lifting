from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from backend.logging_setup import get_logger
from backend.models import AgentFeedbackEntry, Task
from backend.schemas import AgentRetroFeedbackItem
from backend.task_constants import TaskType


@dataclass(frozen=True, slots=True)
class RetroEntriesQuery:
    task_type: TaskType | None = None
    tag: str | None = None
    severity: str | None = None
    source: str | None = None
    limit: int = 100


class RetroService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._logger = get_logger(__name__, component="retro")

    def record_agent_feedback(
        self,
        *,
        task: Task,
        result_metadata: dict[str, Any],
    ) -> list[AgentFeedbackEntry]:
        raw_feedback = result_metadata.get("agent_retro")
        if raw_feedback is None:
            return []

        raw_items = _extract_raw_items(raw_feedback)
        if raw_items is None:
            self._logger.warning(
                "agent_retro_invalid",
                task_id=task.id,
                reason="expected_list_or_entries_object",
            )
            return []

        entries: list[AgentFeedbackEntry] = []
        for index, raw_item in enumerate(raw_items):
            try:
                item = AgentRetroFeedbackItem.model_validate(raw_item)
            except ValidationError as exc:
                self._logger.warning(
                    "agent_retro_item_invalid",
                    task_id=task.id,
                    item_index=index,
                    validation_error_count=len(exc.errors()),
                )
                continue

            entry = AgentFeedbackEntry(
                task_id=task.id,
                root_id=task.root_id or task.id,
                task_type=task.task_type,
                role=task.role,
                attempt=task.attempt,
                source="agent",
                category=item.category,
                tag=item.tag,
                severity=item.severity,
                message=item.message,
                suggested_action=item.suggested_action,
                entry_metadata=item.metadata,
            )
            self._session.add(entry)
            entries.append(entry)

        if entries:
            self._session.flush()
            self._logger.info(
                "agent_retro_recorded",
                task_id=task.id,
                entries_count=len(entries),
            )

        return entries

    def list_entries(self, query: RetroEntriesQuery) -> list[AgentFeedbackEntry]:
        statement = select(AgentFeedbackEntry)
        if query.task_type is not None:
            statement = statement.where(AgentFeedbackEntry.task_type == query.task_type)
        if query.tag is not None:
            statement = statement.where(AgentFeedbackEntry.tag == query.tag)
        if query.severity is not None:
            statement = statement.where(AgentFeedbackEntry.severity == query.severity)
        if query.source is not None:
            statement = statement.where(AgentFeedbackEntry.source == query.source)

        statement = statement.order_by(
            AgentFeedbackEntry.created_at.desc(),
            AgentFeedbackEntry.id.desc(),
        ).limit(query.limit)
        return list(self._session.execute(statement).scalars())

    def list_tag_aggregates(self) -> list[dict[str, Any]]:
        aggregate_rows = self._session.execute(
            select(
                AgentFeedbackEntry.tag,
                func.count(AgentFeedbackEntry.id),
                func.min(AgentFeedbackEntry.created_at),
                func.max(AgentFeedbackEntry.created_at),
                func.count(distinct(AgentFeedbackEntry.task_id)),
            )
            .group_by(AgentFeedbackEntry.tag)
            .order_by(func.count(AgentFeedbackEntry.id).desc(), AgentFeedbackEntry.tag.asc())
        )

        severity_counts = self._build_severity_counts()
        return [
            {
                "tag": tag,
                "count": count,
                "severity_counts": severity_counts.get(tag, {}),
                "first_seen": _serialize_datetime(first_seen),
                "last_seen": _serialize_datetime(last_seen),
                "affected_tasks_count": affected_tasks_count,
            }
            for tag, count, first_seen, last_seen, affected_tasks_count in aggregate_rows
        ]

    def _build_severity_counts(self) -> dict[str, dict[str, int]]:
        rows = self._session.execute(
            select(
                AgentFeedbackEntry.tag,
                AgentFeedbackEntry.severity,
                func.count(AgentFeedbackEntry.id),
            )
            .group_by(AgentFeedbackEntry.tag, AgentFeedbackEntry.severity)
            .order_by(AgentFeedbackEntry.tag.asc(), AgentFeedbackEntry.severity.asc())
        )

        counts: dict[str, dict[str, int]] = {}
        for tag, severity, count in rows:
            counts.setdefault(tag, {})[severity] = count
        return counts


def _extract_raw_items(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        entries = value.get("entries")
        if isinstance(entries, list):
            return entries
    return None


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


__all__ = ["RetroEntriesQuery", "RetroService"]
