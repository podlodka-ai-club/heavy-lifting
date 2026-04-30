from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.bootstrap_db import bootstrap_schema
from backend.db import build_engine, build_session_factory, get_session_factory, session_scope
from backend.models import RevenueConfidence, RevenueSource, Task, TaskRevenue, TokenUsage
from backend.repositories.task_repository import (
    TaskCreateParams,
    TaskRepository,
    TokenUsageCreateParams,
)
from backend.task_constants import TaskStatus, TaskType

DEMO_EXTERNAL_ID_PREFIX = "FRONTEND-DEMO-"
DEMO_TRACKER_NAME = "frontend-demo"
DEMO_WORKSPACE_PREFIX = "frontend-demo"


@dataclass(frozen=True, slots=True)
class FrontendDemoSeedResult:
    tasks_count: int
    token_usage_count: int
    revenue_count: int


@dataclass(frozen=True, slots=True)
class ClosedRootSpec:
    slug: str
    title: str
    revenue_usd: Decimal
    revenue_source: RevenueSource
    revenue_confidence: RevenueConfidence
    closed_days_ago: int
    token_costs: tuple[tuple[TaskType, Decimal], ...]


@dataclass(frozen=True, slots=True)
class StationTaskSpec:
    slug: str
    task_type: TaskType
    status: TaskStatus
    age_hours: int
    error: str | None = None


_CLOSED_ROOT_SPECS = (
    ClosedRootSpec(
        slug="billing-alerts",
        title="Billing alerts rollout",
        revenue_usd=Decimal("1800.000000"),
        revenue_source=RevenueSource.EXPERT,
        revenue_confidence=RevenueConfidence.ACTUAL,
        closed_days_ago=2,
        token_costs=(
            (TaskType.EXECUTE, Decimal("4.150000")),
            (TaskType.PR_FEEDBACK, Decimal("1.250000")),
            (TaskType.DELIVER, Decimal("0.650000")),
        ),
    ),
    ClosedRootSpec(
        slug="ops-console",
        title="Operations console cleanup",
        revenue_usd=Decimal("950.000000"),
        revenue_source=RevenueSource.EXTERNAL,
        revenue_confidence=RevenueConfidence.ESTIMATED,
        closed_days_ago=8,
        token_costs=(
            (TaskType.EXECUTE, Decimal("2.900000")),
            (TaskType.DELIVER, Decimal("0.450000")),
        ),
    ),
    ClosedRootSpec(
        slug="release-guard",
        title="Release guard automation",
        revenue_usd=Decimal("2400.000000"),
        revenue_source=RevenueSource.EXPERT,
        revenue_confidence=RevenueConfidence.ESTIMATED,
        closed_days_ago=16,
        token_costs=(
            (TaskType.EXECUTE, Decimal("5.350000")),
            (TaskType.PR_FEEDBACK, Decimal("1.700000")),
            (TaskType.DELIVER, Decimal("0.800000")),
        ),
    ),
)

_STATION_TASK_SPECS = (
    StationTaskSpec("intake-queue", TaskType.FETCH, TaskStatus.NEW, 9),
    StationTaskSpec("intake-worker", TaskType.FETCH, TaskStatus.PROCESSING, 3),
    StationTaskSpec("execute-api-new", TaskType.EXECUTE, TaskStatus.NEW, 14),
    StationTaskSpec("execute-auth-new", TaskType.EXECUTE, TaskStatus.NEW, 11),
    StationTaskSpec("execute-docs-new", TaskType.EXECUTE, TaskStatus.NEW, 8),
    StationTaskSpec("execute-payments-active", TaskType.EXECUTE, TaskStatus.PROCESSING, 6),
    StationTaskSpec("execute-worker-active", TaskType.EXECUTE, TaskStatus.PROCESSING, 4),
    StationTaskSpec("execute-ui-active", TaskType.EXECUTE, TaskStatus.PROCESSING, 2),
    StationTaskSpec(
        "execute-flaky-failed",
        TaskType.EXECUTE,
        TaskStatus.FAILED,
        7,
        error="Demo failure: flaky integration test",
    ),
    StationTaskSpec(
        "execute-schema-failed",
        TaskType.EXECUTE,
        TaskStatus.FAILED,
        5,
        error="Demo failure: schema drift",
    ),
    StationTaskSpec("feedback-queue", TaskType.PR_FEEDBACK, TaskStatus.NEW, 10),
    StationTaskSpec("feedback-active", TaskType.PR_FEEDBACK, TaskStatus.PROCESSING, 4),
    StationTaskSpec(
        "feedback-blocked",
        TaskType.PR_FEEDBACK,
        TaskStatus.FAILED,
        6,
        error="Demo failure: reviewer requested changes",
    ),
    StationTaskSpec("deliver-queue", TaskType.DELIVER, TaskStatus.NEW, 5),
    StationTaskSpec("deliver-active", TaskType.DELIVER, TaskStatus.PROCESSING, 2),
)


def seed_frontend_demo(
    *,
    session_factory: sessionmaker[Session] | None = None,
) -> FrontendDemoSeedResult:
    active_session_factory = session_factory or get_session_factory()
    with session_scope(session_factory=active_session_factory) as session:
        _remove_existing_demo_rows(session)
        now = datetime.now(UTC)
        repository = TaskRepository(session)
        created_tasks: list[Task] = []
        created_token_usage: list[TokenUsage] = []
        created_revenues: list[TaskRevenue] = []

        for closed_root_spec in _CLOSED_ROOT_SPECS:
            tasks_by_type = _create_closed_root(
                repository,
                spec=closed_root_spec,
                now=now,
            )
            created_tasks.extend(tasks_by_type.values())
            for task_type, cost_usd in closed_root_spec.token_costs:
                created_token_usage.append(
                    repository.record_token_usage(
                        task_id=tasks_by_type[task_type].id,
                        usage=TokenUsageCreateParams(
                            model="gpt-5.4",
                            provider="openai",
                            input_tokens=18_000,
                            output_tokens=4_500,
                            cached_tokens=2_000,
                            estimated=False,
                            cost_usd=cost_usd,
                        ),
                    )
                )

            revenue = TaskRevenue(
                root_task_id=tasks_by_type[TaskType.FETCH].id,
                amount_usd=closed_root_spec.revenue_usd,
                source=closed_root_spec.revenue_source,
                confidence=closed_root_spec.revenue_confidence,
                metadata_payload={
                    "seed": "frontend-demo",
                    "scenario": closed_root_spec.slug,
                    "title": closed_root_spec.title,
                },
            )
            session.add(revenue)
            created_revenues.append(revenue)

        for station_task_spec in _STATION_TASK_SPECS:
            task = _create_station_task(repository, spec=station_task_spec, now=now)
            created_tasks.append(task)

        session.flush()

        return FrontendDemoSeedResult(
            tasks_count=len(created_tasks),
            token_usage_count=len(created_token_usage),
            revenue_count=len(created_revenues),
        )


def _remove_existing_demo_rows(session: Session) -> None:
    demo_task_ids = list(
        session.execute(
            select(Task.id).where(Task.external_task_id.like(f"{DEMO_EXTERNAL_ID_PREFIX}%"))
        ).scalars()
    )
    if not demo_task_ids:
        return

    demo_root_ids = list(
        session.execute(
            select(Task.id).where(
                Task.id.in_(demo_task_ids),
                Task.root_id == Task.id,
            )
        ).scalars()
    )

    session.execute(delete(TokenUsage).where(TokenUsage.task_id.in_(demo_task_ids)))
    if demo_root_ids:
        session.execute(delete(TaskRevenue).where(TaskRevenue.root_task_id.in_(demo_root_ids)))

    demo_tasks = list(
        session.execute(select(Task).where(Task.id.in_(demo_task_ids))).scalars()
    )
    for task in demo_tasks:
        if task.root_id == task.id:
            task.root_id = None
    session.flush()

    child_ids = [task.id for task in demo_tasks if task.parent_id is not None]
    if child_ids:
        session.execute(delete(Task).where(Task.id.in_(child_ids)))

    root_ids = [task.id for task in demo_tasks if task.parent_id is None]
    if root_ids:
        session.execute(delete(Task).where(Task.id.in_(root_ids)))


def _create_closed_root(
    repository: TaskRepository,
    *,
    spec: ClosedRootSpec,
    now: datetime,
) -> dict[TaskType, Task]:
    closed_at = now - timedelta(days=spec.closed_days_ago)
    fetch = repository.create_task(
        _task_params(
            task_type=TaskType.FETCH,
            status=TaskStatus.DONE,
            slug=f"{spec.slug}-fetch",
            title=spec.title,
        )
    )
    execute = repository.create_task(
        _task_params(
            task_type=TaskType.EXECUTE,
            status=TaskStatus.DONE,
            slug=f"{spec.slug}-execute",
            title=spec.title,
            parent_id=fetch.id,
        )
    )
    feedback = repository.create_task(
        _task_params(
            task_type=TaskType.PR_FEEDBACK,
            status=TaskStatus.DONE,
            slug=f"{spec.slug}-feedback",
            title=spec.title,
            parent_id=execute.id,
        )
    )
    deliver = repository.create_task(
        _task_params(
            task_type=TaskType.DELIVER,
            status=TaskStatus.DONE,
            slug=f"{spec.slug}-deliver",
            title=spec.title,
            parent_id=feedback.id,
        )
    )

    for index, task in enumerate((fetch, execute, feedback, deliver)):
        _set_task_times(
            task,
            created_at=closed_at - timedelta(hours=12 - index * 2),
            updated_at=closed_at - timedelta(hours=6 - index * 2),
        )
    _set_task_times(deliver, created_at=closed_at - timedelta(hours=2), updated_at=closed_at)

    return {
        TaskType.FETCH: fetch,
        TaskType.EXECUTE: execute,
        TaskType.PR_FEEDBACK: feedback,
        TaskType.DELIVER: deliver,
    }


def _create_station_task(
    repository: TaskRepository,
    *,
    spec: StationTaskSpec,
    now: datetime,
) -> Task:
    task = repository.create_task(
        _task_params(
            task_type=spec.task_type,
            status=spec.status,
            slug=spec.slug,
            title=f"Factory demo {spec.slug}",
            error=spec.error,
        )
    )
    updated_at = now - timedelta(hours=spec.age_hours)
    _set_task_times(task, created_at=updated_at - timedelta(hours=2), updated_at=updated_at)
    return task


def _task_params(
    *,
    task_type: TaskType,
    status: TaskStatus,
    slug: str,
    title: str,
    parent_id: int | None = None,
    error: str | None = None,
) -> TaskCreateParams:
    external_task_id = f"{DEMO_EXTERNAL_ID_PREFIX}{slug}"
    return TaskCreateParams(
        task_type=task_type,
        status=status,
        parent_id=parent_id,
        tracker_name=DEMO_TRACKER_NAME,
        external_task_id=external_task_id,
        repo_url="https://example.com/frontend-demo/heavy-lifting.git",
        repo_ref="main",
        workspace_key=f"{DEMO_WORKSPACE_PREFIX}-{slug}",
        branch_name=f"frontend-demo/{slug}",
        role="demo-seed",
        context={"title": title, "demo_seed": "frontend"},
        input_payload={"source": "frontend-demo-seed", "station": task_type.value},
        result_payload={"demo": True} if status == TaskStatus.DONE else None,
        error=error,
    )


def _set_task_times(task: Task, *, created_at: datetime, updated_at: datetime) -> None:
    task.created_at = created_at
    task.updated_at = updated_at


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed presentation demo data for the local frontend.",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="Override DATABASE_URL for a single seed run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.database_url:
        bootstrap_schema(database_url=args.database_url)
        engine = build_engine(args.database_url)
        session_factory = build_session_factory(engine)
    else:
        bootstrap_schema()
        session_factory = get_session_factory()

    result = seed_frontend_demo(session_factory=session_factory)
    print(
        "Frontend demo data is ready; "
        f"tasks={result.tasks_count}, "
        f"token_usage={result.token_usage_count}, "
        f"revenues={result.revenue_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
