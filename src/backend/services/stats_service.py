from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.models import Task, TokenUsage
from backend.task_constants import TaskStatus, TaskType

_FACTORY_STATIONS = (
    TaskType.FETCH,
    TaskType.EXECUTE,
    TaskType.PR_FEEDBACK,
    TaskType.TRACKER_FEEDBACK,
    TaskType.DELIVER,
)

_FACTORY_DATA_GAPS = (
    "transition_history",
    "throughput_per_hour",
    "worker_capacity",
    "rework_loops",
    "business_task_kind",
)


class StatsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build_stats(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tasks": self._build_task_stats(),
            "token_usage": self._build_token_usage_stats(),
        }

    def build_factory(self) -> dict[str, Any]:
        generated_at = datetime.now(UTC)
        stations = [
            self._build_factory_station(task_type, generated_at) for task_type in _FACTORY_STATIONS
        ]
        bottleneck = _find_bottleneck(stations)

        return {
            "generated_at": generated_at.isoformat(),
            "stations": stations,
            "bottleneck": bottleneck,
            "data_gaps": list(_FACTORY_DATA_GAPS),
        }

    def _build_task_stats(self) -> dict[str, Any]:
        total = self._session.execute(select(func.count(Task.id))).scalar_one()
        by_status = {status.value: 0 for status in TaskStatus}
        by_type = {task_type.value: 0 for task_type in TaskType}
        by_type_and_status = {
            task_type.value: {status.value: 0 for status in TaskStatus} for task_type in TaskType
        }

        for status, count in self._session.execute(
            select(Task.status, func.count(Task.id))
            .group_by(Task.status)
            .order_by(Task.status.asc())
        ):
            by_status[status.value] = count

        for task_type, count in self._session.execute(
            select(Task.task_type, func.count(Task.id))
            .group_by(Task.task_type)
            .order_by(Task.task_type.asc())
        ):
            by_type[task_type.value] = count

        for task_type, status, count in self._session.execute(
            select(Task.task_type, Task.status, func.count(Task.id))
            .group_by(Task.task_type, Task.status)
            .order_by(Task.task_type.asc(), Task.status.asc())
        ):
            by_type_and_status[task_type.value][status.value] = count

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_type_and_status": by_type_and_status,
        }

    def _build_token_usage_stats(self) -> dict[str, Any]:
        totals = self._session.execute(
            select(
                func.count(TokenUsage.id),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cached_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost_usd), 0),
                func.coalesce(
                    func.sum(case((TokenUsage.estimated.is_(True), 1), else_=0)),
                    0,
                ),
            )
        ).one()

        (
            entries_count,
            input_tokens,
            output_tokens,
            cached_tokens,
            total_cost_usd,
            estimated_count,
        ) = totals

        return {
            "entries_count": entries_count,
            "estimated_entries_count": estimated_count,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cached": cached_tokens,
                "total": input_tokens + output_tokens + cached_tokens,
            },
            "cost_usd": {
                "total": _format_decimal(total_cost_usd),
                "estimated_share": _format_decimal(
                    self._session.execute(
                        select(
                            func.coalesce(
                                func.sum(
                                    case(
                                        (TokenUsage.estimated.is_(True), TokenUsage.cost_usd),
                                        else_=Decimal("0"),
                                    )
                                ),
                                0,
                            )
                        )
                    ).scalar_one()
                ),
            },
            "by_provider": self._build_usage_breakdown(TokenUsage.provider),
            "by_model": self._build_usage_breakdown(TokenUsage.model),
            "by_task_type": self._build_usage_by_task_type(),
        }

    def _build_usage_breakdown(self, dimension) -> dict[str, Any]:
        rows = self._session.execute(
            select(
                dimension,
                func.count(TokenUsage.id),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cached_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost_usd), 0),
            )
            .group_by(dimension)
            .order_by(dimension.asc())
        )

        return {
            key: {
                "entries_count": entries_count,
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cached": cached_tokens,
                    "total": input_tokens + output_tokens + cached_tokens,
                },
                "cost_usd": _format_decimal(cost_usd),
            }
            for key, entries_count, input_tokens, output_tokens, cached_tokens, cost_usd in rows
        }

    def _build_usage_by_task_type(self) -> dict[str, Any]:
        rows = self._session.execute(
            select(
                Task.task_type,
                func.count(TokenUsage.id),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cached_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost_usd), 0),
            )
            .join(Task, Task.id == TokenUsage.task_id)
            .group_by(Task.task_type)
            .order_by(Task.task_type.asc())
        )

        breakdown = {task_type.value: _empty_usage_bucket() for task_type in TaskType}
        for task_type, entries_count, input_tokens, output_tokens, cached_tokens, cost_usd in rows:
            breakdown[task_type.value] = {
                "entries_count": entries_count,
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cached": cached_tokens,
                    "total": input_tokens + output_tokens + cached_tokens,
                },
                "cost_usd": _format_decimal(cost_usd),
            }
        return breakdown

    def _build_factory_station(self, task_type: TaskType, generated_at: datetime) -> dict[str, Any]:
        counts_by_status = {status.value: 0 for status in TaskStatus}
        for status, count in self._session.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.task_type == task_type)
            .group_by(Task.status)
            .order_by(Task.status.asc())
        ):
            counts_by_status[status.value] = count

        total_count = sum(counts_by_status.values())
        queue_count = counts_by_status[TaskStatus.NEW.value]
        active_count = counts_by_status[TaskStatus.PROCESSING.value]
        failed_count = counts_by_status[TaskStatus.FAILED.value]

        return {
            "name": task_type.value,
            "counts_by_status": counts_by_status,
            "total_count": total_count,
            "wip_count": queue_count + active_count,
            "queue_count": queue_count,
            "active_count": active_count,
            "failed_count": failed_count,
            "oldest_queue_age_seconds": self._oldest_status_age_seconds(
                task_type,
                TaskStatus.NEW,
                generated_at,
            ),
            "oldest_active_age_seconds": self._oldest_status_age_seconds(
                task_type,
                TaskStatus.PROCESSING,
                generated_at,
            ),
        }

    def _oldest_status_age_seconds(
        self,
        task_type: TaskType,
        status: TaskStatus,
        generated_at: datetime,
    ) -> int | None:
        oldest_updated_at = self._session.execute(
            select(func.min(Task.updated_at)).where(
                Task.task_type == task_type,
                Task.status == status,
            )
        ).scalar_one()
        if oldest_updated_at is None:
            return None

        return max(0, int((generated_at - _as_aware_utc(oldest_updated_at)).total_seconds()))


def _empty_usage_bucket() -> dict[str, Any]:
    return {
        "entries_count": 0,
        "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
        "cost_usd": "0.000000",
    }


def _format_decimal(value: Decimal | int | float | None) -> str:
    normalized = Decimal("0") if value is None else Decimal(str(value))
    return format(normalized.quantize(Decimal("0.000001")), "f")


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _find_bottleneck(stations: list[dict[str, Any]]) -> dict[str, Any] | None:
    bottleneck = max(stations, key=lambda station: station["wip_count"])
    if bottleneck["wip_count"] == 0:
        return None

    return {
        "station": bottleneck["name"],
        "wip_count": bottleneck["wip_count"],
    }


__all__ = ["StatsService"]
