from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.models import Task, TokenUsage
from backend.task_constants import TaskStatus, TaskType


class StatsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build_stats(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tasks": self._build_task_stats(),
            "token_usage": self._build_token_usage_stats(),
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


def _empty_usage_bucket() -> dict[str, Any]:
    return {
        "entries_count": 0,
        "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
        "cost_usd": "0.000000",
    }


def _format_decimal(value: Decimal | int | float | None) -> str:
    normalized = Decimal("0") if value is None else Decimal(str(value))
    return format(normalized.quantize(Decimal("0.000001")), "f")


__all__ = ["StatsService"]
