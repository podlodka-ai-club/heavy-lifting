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
from backend.models import (
    AgentFeedbackEntry,
    RevenueConfidence,
    RevenueSource,
    Task,
    TaskRevenue,
    TokenUsage,
)
from backend.repositories.task_repository import (
    TaskCreateParams,
    TaskRepository,
    TokenUsageCreateParams,
)
from backend.services.retro_service import RetroService
from backend.task_constants import TaskStatus, TaskType

DEMO_EXTERNAL_ID_PREFIX = "FRONTEND-DEMO-"
DEMO_TRACKER_NAME = "frontend-demo"
DEMO_WORKSPACE_PREFIX = "frontend-demo"


@dataclass(frozen=True, slots=True)
class FrontendDemoSeedResult:
    tasks_count: int
    token_usage_count: int
    revenue_count: int
    retro_entries_count: int


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


@dataclass(frozen=True, slots=True)
class RetroFeedbackSpec:
    task_slug: str
    tag: str
    category: str
    severity: str
    message: str
    suggested_action: str
    age_hours: int


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

_RETRO_FEEDBACK_SPECS = (
    RetroFeedbackSpec(
        task_slug="billing-alerts-execute",
        tag="acceptance-missing",
        category="requirements",
        severity="error",
        message=(
            "Implementation started before the acceptance criteria named the observable UI states."
        ),
        suggested_action="Ask for explicit acceptance criteria before editing source files.",
        age_hours=72,
    ),
    RetroFeedbackSpec(
        task_slug="execute-api-new",
        tag="acceptance-missing",
        category="requirements",
        severity="warning",
        message="The task needed a tighter definition of done for API response behavior.",
        suggested_action="Turn vague expected behavior into concrete request/response examples.",
        age_hours=44,
    ),
    RetroFeedbackSpec(
        task_slug="feedback-blocked",
        tag="acceptance-missing",
        category="review",
        severity="info",
        message="Review feedback found assumptions that were not written in the task.",
        suggested_action="Record assumptions in the worklog before implementation continues.",
        age_hours=20,
    ),
    RetroFeedbackSpec(
        task_slug="ops-console-feedback",
        tag="slow-ci",
        category="checks",
        severity="warning",
        message="Frontend and backend checks were rerun separately after a late routing fix.",
        suggested_action="Run focused checks first, then one final combined verification pass.",
        age_hours=66,
    ),
    RetroFeedbackSpec(
        task_slug="deliver-active",
        tag="slow-ci",
        category="checks",
        severity="info",
        message="Build output was healthy but slow enough to hide the failing test signal.",
        suggested_action="Keep the shortest failing command in the progress log.",
        age_hours=18,
    ),
    RetroFeedbackSpec(
        task_slug="execute-flaky-failed",
        tag="flaky-tests",
        category="testing",
        severity="error",
        message="A retry passed locally after the first test run failed on timing.",
        suggested_action="Stabilize async waits instead of accepting a green rerun.",
        age_hours=58,
    ),
    RetroFeedbackSpec(
        task_slug="release-guard-feedback",
        tag="flaky-tests",
        category="testing",
        severity="warning",
        message="Animation state made the UI assertion timing-sensitive.",
        suggested_action="Use reduced-motion test coverage for animated UI paths.",
        age_hours=38,
    ),
    RetroFeedbackSpec(
        task_slug="execute-docs-new",
        tag="ambiguous-reqs",
        category="requirements",
        severity="warning",
        message="The requested page concept mixed visual direction with missing data contracts.",
        suggested_action="Separate visual concept requirements from backend data availability.",
        age_hours=50,
    ),
    RetroFeedbackSpec(
        task_slug="intake-queue",
        tag="ambiguous-reqs",
        category="intake",
        severity="info",
        message="The initial task omitted which unrelated local files were safe to ignore.",
        suggested_action="List out-of-scope dirty files before the first edit.",
        age_hours=12,
    ),
    RetroFeedbackSpec(
        task_slug="execute-schema-failed",
        tag="docker-fail",
        category="environment",
        severity="error",
        message="Container bootstrap failed because the local database schema was older than code.",
        suggested_action="Run the explicit bootstrap command before demo presentation setup.",
        age_hours=30,
    ),
    RetroFeedbackSpec(
        task_slug="execute-auth-new",
        tag="auth-error",
        category="integration",
        severity="error",
        message="A mocked auth path masked the real token validation error until review.",
        suggested_action="Keep auth failures visible in mocked integration paths.",
        age_hours=8,
    ),
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
        created_retro_entries: list[AgentFeedbackEntry] = []

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

        tasks_by_slug = {
            task.external_task_id.removeprefix(DEMO_EXTERNAL_ID_PREFIX): task
            for task in created_tasks
            if task.external_task_id is not None
        }
        created_retro_entries.extend(
            _create_retro_feedback(session, tasks_by_slug=tasks_by_slug, now=now)
        )

        session.flush()

        return FrontendDemoSeedResult(
            tasks_count=len(created_tasks),
            token_usage_count=len(created_token_usage),
            revenue_count=len(created_revenues),
            retro_entries_count=len(created_retro_entries),
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

    session.execute(delete(AgentFeedbackEntry).where(AgentFeedbackEntry.task_id.in_(demo_task_ids)))
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


def _create_retro_feedback(
    session: Session,
    *,
    tasks_by_slug: dict[str, Task],
    now: datetime,
) -> list[AgentFeedbackEntry]:
    service = RetroService(session)
    entries: list[AgentFeedbackEntry] = []

    for spec in _RETRO_FEEDBACK_SPECS:
        task = tasks_by_slug[spec.task_slug]
        created_entries = service.record_agent_feedback(
            task=task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": spec.tag,
                        "category": spec.category,
                        "severity": spec.severity,
                        "message": spec.message,
                        "suggested_action": spec.suggested_action,
                        "metadata": {
                            "seed": "frontend-demo",
                            "task_slug": spec.task_slug,
                        },
                    }
                ]
            },
        )
        for entry in created_entries:
            entry.created_at = now - timedelta(hours=spec.age_hours)
            entries.append(entry)

    return entries


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
        f"revenues={result.revenue_count}, "
        f"retro_entries={result.retro_entries_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
