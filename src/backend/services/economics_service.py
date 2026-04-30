from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import RevenueConfidence, RevenueSource, Task, TaskRevenue, TokenUsage
from backend.task_constants import TaskStatus, TaskType

type Bucket = Literal["day", "week", "month"]

_MONEY_QUANT = Decimal("0.000001")
_ECONOMICS_DATA_GAPS = (
    "infra_cost",
    "runner_hours",
    "external_accounting_import",
    "retry_waste",
)
_DEFAULT_PERIOD = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class ClosedRoot:
    root_task_id: int
    closed_at: datetime


@dataclass(frozen=True, slots=True)
class RevenueUpsert:
    amount_usd: Decimal
    source: RevenueSource
    confidence: RevenueConfidence
    metadata_payload: dict[str, Any] | None = None


class EconomicsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build_snapshot(
        self,
        *,
        from_value: datetime | None = None,
        to_value: datetime | None = None,
        bucket: Bucket = "day",
    ) -> dict[str, Any]:
        from_value, to_value = resolve_period(from_value=from_value, to_value=to_value)
        closed_roots = self._list_closed_roots(from_value=from_value, to_value=to_value)
        root_ids = [root.root_task_id for root in closed_roots]
        root_tasks = self._load_root_tasks(root_ids)
        revenue_by_root = self._load_revenue_by_root(root_ids)
        cost_by_root = self._load_cost_by_root(root_ids)

        roots = [
            self._serialize_root(
                closed_root=root,
                root_task=root_tasks.get(root.root_task_id),
                revenue=revenue_by_root.get(root.root_task_id),
                token_cost_usd=cost_by_root[root.root_task_id],
            )
            for root in closed_roots
        ]

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "period": {
                "from": _serialize_datetime(from_value),
                "to": _serialize_datetime(to_value),
                "bucket": bucket,
            },
            "totals": self._build_totals(roots),
            "series": self._build_series(
                bucket=bucket,
                closed_roots=closed_roots,
                revenue_by_root=revenue_by_root,
                cost_by_root=cost_by_root,
            ),
            "roots": roots,
            "data_gaps": list(_ECONOMICS_DATA_GAPS),
        }

    def generate_mock_revenue(
        self,
        *,
        min_usd: Decimal = Decimal("100"),
        max_usd: Decimal = Decimal("2500"),
        seed: str = "heavy-lifting-economics-v1",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        closed_roots = self._list_closed_roots(from_value=None, to_value=None)
        root_ids = [root.root_task_id for root in closed_roots]
        revenue_by_root = self._load_revenue_by_root(root_ids)
        created_ids: list[int] = []
        updated_ids: list[int] = []

        for root_id in root_ids:
            existing_revenue = revenue_by_root.get(root_id)
            if existing_revenue is not None and not overwrite:
                continue

            amount_usd = _deterministic_amount(
                seed=seed,
                root_task_id=root_id,
                min_usd=min_usd,
                max_usd=max_usd,
            )
            metadata_payload = {
                "seed": seed,
                "min_usd": _format_decimal(min_usd),
                "max_usd": _format_decimal(max_usd),
            }

            if existing_revenue is None:
                self._session.add(
                    TaskRevenue(
                        root_task_id=root_id,
                        amount_usd=amount_usd,
                        source=RevenueSource.MOCK,
                        confidence=RevenueConfidence.ESTIMATED,
                        metadata_payload=metadata_payload,
                    )
                )
                created_ids.append(root_id)
                continue

            existing_revenue.amount_usd = amount_usd
            existing_revenue.source = RevenueSource.MOCK
            existing_revenue.confidence = RevenueConfidence.ESTIMATED
            existing_revenue.metadata_payload = metadata_payload
            updated_ids.append(root_id)

        self._session.flush()
        return {
            "created_count": len(created_ids),
            "updated_count": len(updated_ids),
            "created_root_task_ids": created_ids,
            "updated_root_task_ids": updated_ids,
        }

    def upsert_revenue(self, root_task_id: int, payload: RevenueUpsert) -> TaskRevenue | None:
        root_task = self._session.get(Task, root_task_id)
        if root_task is None or root_task.root_id not in (None, root_task_id):
            return None

        revenue = (
            self._session.execute(
                select(TaskRevenue).where(TaskRevenue.root_task_id == root_task_id)
            )
            .scalars()
            .one_or_none()
        )
        if revenue is None:
            revenue = TaskRevenue(
                root_task_id=root_task_id,
                amount_usd=payload.amount_usd,
                source=payload.source,
                confidence=payload.confidence,
                metadata_payload=payload.metadata_payload,
            )
            self._session.add(revenue)
        else:
            revenue.amount_usd = payload.amount_usd
            revenue.source = payload.source
            revenue.confidence = payload.confidence
            revenue.metadata_payload = payload.metadata_payload

        self._session.flush()
        return revenue

    def _list_closed_roots(
        self,
        *,
        from_value: datetime | None,
        to_value: datetime | None,
    ) -> list[ClosedRoot]:
        root_key = func.coalesce(Task.root_id, Task.id)
        rows = self._session.execute(
            select(root_key.label("root_task_id"), func.min(Task.updated_at).label("closed_at"))
            .where(Task.task_type == TaskType.DELIVER, Task.status == TaskStatus.DONE)
            .group_by(root_key)
            .order_by(func.min(Task.updated_at).asc(), root_key.asc())
        )

        closed_roots: list[ClosedRoot] = []
        for root_task_id, closed_at in rows:
            aware_closed_at = _as_aware_utc(closed_at)
            if from_value is not None and aware_closed_at < from_value:
                continue
            if to_value is not None and aware_closed_at > to_value:
                continue

            closed_roots.append(
                ClosedRoot(root_task_id=int(root_task_id), closed_at=aware_closed_at)
            )
        return closed_roots

    def _load_root_tasks(self, root_ids: list[int]) -> dict[int, Task]:
        if not root_ids:
            return {}

        tasks = self._session.execute(select(Task).where(Task.id.in_(root_ids))).scalars()
        return {task.id: task for task in tasks}

    def _load_revenue_by_root(self, root_ids: list[int]) -> dict[int, TaskRevenue]:
        if not root_ids:
            return {}

        revenues = self._session.execute(
            select(TaskRevenue).where(TaskRevenue.root_task_id.in_(root_ids))
        ).scalars()
        return {revenue.root_task_id: revenue for revenue in revenues}

    def _load_cost_by_root(self, root_ids: list[int]) -> defaultdict[int, Decimal]:
        costs: defaultdict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        if not root_ids:
            return costs

        root_key = func.coalesce(Task.root_id, Task.id)
        rows = self._session.execute(
            select(root_key.label("root_task_id"), func.coalesce(func.sum(TokenUsage.cost_usd), 0))
            .join(Task, Task.id == TokenUsage.task_id)
            .where(root_key.in_(root_ids))
            .group_by(root_key)
        )
        for root_task_id, cost_usd in rows:
            costs[int(root_task_id)] = Decimal(str(cost_usd))
        return costs

    def _serialize_root(
        self,
        *,
        closed_root: ClosedRoot,
        root_task: Task | None,
        revenue: TaskRevenue | None,
        token_cost_usd: Decimal,
    ) -> dict[str, Any]:
        revenue_usd = revenue.amount_usd if revenue is not None else None
        profit_usd = revenue_usd - token_cost_usd if revenue_usd is not None else None

        return {
            "root_task_id": closed_root.root_task_id,
            "external_task_id": root_task.external_task_id if root_task is not None else None,
            "tracker_name": root_task.tracker_name if root_task is not None else None,
            "closed_at": closed_root.closed_at.isoformat(),
            "revenue_usd": _format_decimal(revenue_usd) if revenue_usd is not None else None,
            "token_cost_usd": _format_decimal(token_cost_usd),
            "profit_usd": _format_decimal(profit_usd) if profit_usd is not None else None,
            "revenue_source": revenue.source.value if revenue is not None else None,
            "revenue_confidence": revenue.confidence.value if revenue is not None else None,
        }

    def _build_totals(self, roots: list[dict[str, Any]]) -> dict[str, Any]:
        revenue_total = Decimal("0")
        token_cost_total = Decimal("0")
        monetized_roots_count = 0

        for root in roots:
            token_cost_total += Decimal(root["token_cost_usd"])
            if root["revenue_usd"] is None:
                continue

            monetized_roots_count += 1
            revenue_total += Decimal(root["revenue_usd"])

        closed_roots_count = len(roots)
        return {
            "closed_roots_count": closed_roots_count,
            "monetized_roots_count": monetized_roots_count,
            "missing_revenue_count": closed_roots_count - monetized_roots_count,
            "revenue_usd": _format_decimal(revenue_total),
            "token_cost_usd": _format_decimal(token_cost_total),
            "profit_usd": _format_decimal(revenue_total - token_cost_total),
        }

    def _build_series(
        self,
        *,
        bucket: Bucket,
        closed_roots: list[ClosedRoot],
        revenue_by_root: dict[int, TaskRevenue],
        cost_by_root: defaultdict[int, Decimal],
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}

        for root in closed_roots:
            bucket_key = _bucket_key(root.closed_at, bucket)
            item = buckets.setdefault(
                bucket_key,
                {
                    "bucket": bucket_key,
                    "closed_roots_count": 0,
                    "monetized_roots_count": 0,
                    "missing_revenue_count": 0,
                    "revenue_usd": Decimal("0"),
                    "token_cost_usd": Decimal("0"),
                    "profit_usd": Decimal("0"),
                },
            )
            item["closed_roots_count"] += 1
            item["token_cost_usd"] += cost_by_root[root.root_task_id]

            revenue = revenue_by_root.get(root.root_task_id)
            if revenue is None:
                item["missing_revenue_count"] += 1
                continue

            item["monetized_roots_count"] += 1
            item["revenue_usd"] += revenue.amount_usd

        return [
            {
                **item,
                "revenue_usd": _format_decimal(item["revenue_usd"]),
                "token_cost_usd": _format_decimal(item["token_cost_usd"]),
                "profit_usd": _format_decimal(item["revenue_usd"] - item["token_cost_usd"]),
            }
            for _, item in sorted(buckets.items())
        ]


def parse_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc

    return _as_aware_utc(parsed)


def resolve_period(
    *,
    from_value: datetime | None,
    to_value: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    resolved_now = _as_aware_utc(now or datetime.now(UTC))
    resolved_to = to_value or resolved_now
    resolved_from = from_value or (resolved_to - _DEFAULT_PERIOD)

    if resolved_from > resolved_to:
        raise ValueError("from must be earlier than or equal to to")

    return resolved_from, resolved_to


def parse_money(value: Any, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal number") from exc

    if amount < 0:
        raise ValueError(f"{field_name} must be non-negative")

    return amount.quantize(_MONEY_QUANT)


def _bucket_key(value: datetime, bucket: Bucket) -> str:
    if bucket == "day":
        return value.date().isoformat()

    if bucket == "week":
        monday = value.date()
        monday = monday.fromordinal(monday.toordinal() - monday.weekday())
        return monday.isoformat()

    return f"{value.year:04d}-{value.month:02d}"


def _deterministic_amount(
    *,
    seed: str,
    root_task_id: int,
    min_usd: Decimal,
    max_usd: Decimal,
) -> Decimal:
    digest = sha256(f"{seed}:{root_task_id}".encode()).digest()
    fraction = Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64 - 1)
    return (min_usd + ((max_usd - min_usd) * fraction)).quantize(_MONEY_QUANT)


def _format_decimal(value: Decimal | int | float | None) -> str:
    normalized = Decimal("0") if value is None else Decimal(str(value))
    return format(normalized.quantize(_MONEY_QUANT), "f")


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "EconomicsService",
    "RevenueUpsert",
    "parse_datetime",
    "parse_money",
    "resolve_period",
]
