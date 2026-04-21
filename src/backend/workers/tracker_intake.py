from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.protocols.tracker import TrackerProtocol
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import SchemaModel, TrackerFetchTasksQuery, TrackerTask
from backend.task_constants import TaskStatus, TaskType


@dataclass(frozen=True, slots=True)
class TrackerIntakeReport:
    fetched_count: int = 0
    created_fetch_tasks: int = 0
    created_execute_tasks: int = 0
    skipped_tasks: int = 0


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    created_fetch_task: bool = False
    created_execute_task: bool = False


@dataclass(slots=True)
class TrackerIntakeWorker:
    tracker: TrackerProtocol
    tracker_name: str
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    fetch_limit: int = 100
    fetch_statuses: Sequence[TaskStatus] = (TaskStatus.NEW,)

    def poll_once(self) -> TrackerIntakeReport:
        tracker_tasks = self.tracker.fetch_tasks(
            TrackerFetchTasksQuery(statuses=list(self.fetch_statuses), limit=self.fetch_limit)
        )
        report = TrackerIntakeReport(fetched_count=len(tracker_tasks))

        with session_scope(session_factory=self.session_factory) as session:
            repository = TaskRepository(session)
            for tracker_task in tracker_tasks:
                outcome = self._ingest_tracker_task(
                    repository=repository,
                    tracker_task=tracker_task,
                )
                report = TrackerIntakeReport(
                    fetched_count=report.fetched_count,
                    created_fetch_tasks=report.created_fetch_tasks
                    + int(outcome.created_fetch_task),
                    created_execute_tasks=report.created_execute_tasks
                    + int(outcome.created_execute_task),
                    skipped_tasks=report.skipped_tasks
                    + int(not outcome.created_fetch_task and not outcome.created_execute_task),
                )

        return report

    def run_forever(
        self,
        *,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            self.poll_once()
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            sleep_fn(self.poll_interval)

    def _ingest_tracker_task(
        self,
        *,
        repository: TaskRepository,
        tracker_task: TrackerTask,
    ) -> IntakeOutcome:
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name=self.tracker_name,
            external_task_id=tracker_task.external_id,
        )
        created_fetch_task = False

        if fetch_task is None:
            fetch_task = repository.create_task(
                TaskCreateParams(
                    task_type=TaskType.FETCH,
                    status=TaskStatus.DONE,
                    tracker_name=self.tracker_name,
                    external_task_id=tracker_task.external_id,
                    external_parent_id=tracker_task.parent_external_id,
                    repo_url=tracker_task.repo_url,
                    repo_ref=tracker_task.repo_ref,
                    workspace_key=tracker_task.workspace_key,
                    context=tracker_task.context.model_dump(mode="python"),
                    input_payload=_dump_model_or_none(tracker_task.input_payload),
                )
            )
            created_fetch_task = True

        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        created_execute_task = False

        if execute_task is None:
            repository.create_task(
                TaskCreateParams(
                    task_type=TaskType.EXECUTE,
                    parent_id=fetch_task.id,
                    status=TaskStatus.NEW,
                    tracker_name=self.tracker_name,
                    external_parent_id=tracker_task.external_id,
                    repo_url=tracker_task.repo_url,
                    repo_ref=tracker_task.repo_ref,
                    workspace_key=tracker_task.workspace_key,
                    context=tracker_task.context.model_dump(mode="python"),
                    input_payload=_dump_model_or_none(tracker_task.input_payload),
                )
            )
            created_execute_task = True

        return IntakeOutcome(
            created_fetch_task=created_fetch_task,
            created_execute_task=created_execute_task,
        )


def build_tracker_intake_worker(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> TrackerIntakeWorker:
    active_runtime = runtime or create_runtime_container()
    return TrackerIntakeWorker(
        tracker=active_runtime.tracker,
        tracker_name=active_runtime.settings.tracker_adapter,
        session_factory=session_factory or get_session_factory(),
        poll_interval=active_runtime.settings.tracker_poll_interval,
    )


def _dump_model_or_none(value: SchemaModel | None) -> dict[str, object] | None:
    if value is None:
        return None
    return value.model_dump(mode="python")


__all__ = [
    "IntakeOutcome",
    "TrackerIntakeReport",
    "TrackerIntakeWorker",
    "build_tracker_intake_worker",
]
