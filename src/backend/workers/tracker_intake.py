from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.estimate_mode import mark_input_payload_estimate_only
from backend.logging_setup import get_logger
from backend.protocols.scm import ScmProtocol
from backend.protocols.tracker import TrackerProtocol
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import (
    SchemaModel,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmReadPrFeedbackQuery,
    TaskInputPayload,
    TrackerCommentPayload,
    TrackerFetchTasksQuery,
    TrackerReadCommentsQuery,
    TrackerTask,
)
from backend.services.context_builder import ContextBuilder
from backend.task_constants import TaskStatus, TaskType
from backend.workers.execute_worker import should_skip_scm_artifacts


@dataclass(frozen=True, slots=True)
class TrackerIntakeReport:
    fetched_count: int = 0
    created_fetch_tasks: int = 0
    created_execute_tasks: int = 0
    skipped_tasks: int = 0
    fetched_feedback_items: int = 0
    created_pr_feedback_tasks: int = 0
    created_tracker_feedback_tasks: int = 0
    skipped_feedback_items: int = 0
    unmapped_feedback_items: int = 0


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    created_fetch_task: bool = False
    created_execute_task: bool = False


@dataclass(frozen=True, slots=True)
class PrFeedbackIntakeOutcome:
    created_pr_feedback_task: bool = False
    skipped_feedback_item: bool = False
    unmapped_feedback_item: bool = False


@dataclass(frozen=True, slots=True)
class TrackerFeedbackIntakeOutcome:
    created_tracker_feedback_task: bool = False
    skipped_feedback_item: bool = False


@dataclass(slots=True)
class TrackerIntakeWorker:
    tracker: TrackerProtocol
    scm: ScmProtocol
    tracker_name: str
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    pr_poll_interval: int = 60
    fetch_limit: int = 100
    feedback_limit: int = 100
    fetch_statuses: Sequence[TaskStatus] = (TaskStatus.NEW,)

    _PR_FEEDBACK_CURSOR_METADATA_KEY = "scm_pr_feedback_cursor"
    _TRACKER_FEEDBACK_CURSOR_METADATA_KEY = "tracker_comment_cursor"
    _PR_FEEDBACK_UNRESOLVED_KEY = "_hl_unresolved"
    _SYSTEM_COMMENT_SOURCE_KEY = "source"
    _SYSTEM_COMMENT_SOURCE_VALUE = "heavy_lifting"

    def poll_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        report = self.poll_tracker_once()
        feedback_report = self.poll_pr_feedback_once()
        tracker_feedback_report = self.poll_tracker_feedback_once()
        combined_report = TrackerIntakeReport(
            fetched_count=report.fetched_count,
            created_fetch_tasks=report.created_fetch_tasks,
            created_execute_tasks=report.created_execute_tasks,
            skipped_tasks=report.skipped_tasks,
            fetched_feedback_items=feedback_report.fetched_feedback_items,
            created_pr_feedback_tasks=feedback_report.created_pr_feedback_tasks,
            created_tracker_feedback_tasks=tracker_feedback_report.created_tracker_feedback_tasks,
            skipped_feedback_items=(
                feedback_report.skipped_feedback_items
                + tracker_feedback_report.skipped_feedback_items
            ),
            unmapped_feedback_items=(
                feedback_report.unmapped_feedback_items
                + tracker_feedback_report.unmapped_feedback_items
            ),
        )
        logger.info(
            "tracker_intake_cycle_completed",
            fetched_count=combined_report.fetched_count,
            created_fetch_tasks=combined_report.created_fetch_tasks,
            created_execute_tasks=combined_report.created_execute_tasks,
            skipped_tasks=combined_report.skipped_tasks,
            fetched_feedback_items=combined_report.fetched_feedback_items,
            created_pr_feedback_tasks=combined_report.created_pr_feedback_tasks,
            created_tracker_feedback_tasks=combined_report.created_tracker_feedback_tasks,
            skipped_feedback_items=combined_report.skipped_feedback_items,
            unmapped_feedback_items=combined_report.unmapped_feedback_items,
        )
        return combined_report

    def poll_tracker_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        logger.info(
            "tracker_poll_started",
            fetch_limit=self.fetch_limit,
            fetch_statuses=[status.value for status in self.fetch_statuses],
        )
        try:
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
        except Exception as exc:
            logger.exception(
                "tracker_poll_failed",
                error=str(exc),
                fetch_limit=self.fetch_limit,
                fetch_statuses=[status.value for status in self.fetch_statuses],
            )
            raise

        logger.info(
            "tracker_poll_completed",
            fetched_count=report.fetched_count,
            created_fetch_tasks=report.created_fetch_tasks,
            created_execute_tasks=report.created_execute_tasks,
            skipped_tasks=report.skipped_tasks,
        )
        return report

    def poll_pr_feedback_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        logger.info("pr_feedback_poll_started", feedback_limit=self.feedback_limit)
        try:
            report = TrackerIntakeReport()

            with session_scope(session_factory=self.session_factory) as session:
                repository = TaskRepository(session)
                execute_tasks = repository.list_execute_tasks_with_prs()

                for execute_task in execute_tasks:
                    report = self._poll_execute_pr_feedback(
                        repository=repository,
                        execute_task=execute_task,
                        report=report,
                    )
        except Exception as exc:
            logger.exception(
                "pr_feedback_poll_failed",
                error=str(exc),
                feedback_limit=self.feedback_limit,
            )
            raise

        logger.info(
            "pr_feedback_poll_completed",
            fetched_feedback_items=report.fetched_feedback_items,
            created_pr_feedback_tasks=report.created_pr_feedback_tasks,
            skipped_feedback_items=report.skipped_feedback_items,
            unmapped_feedback_items=report.unmapped_feedback_items,
        )
        return report

    def poll_tracker_feedback_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        logger.info("tracker_feedback_poll_started", feedback_limit=self.feedback_limit)
        try:
            report = TrackerIntakeReport()
            with session_scope(session_factory=self.session_factory) as session:
                repository = TaskRepository(session)
                for execute_task in repository.list_execute_tasks():
                    report = self._poll_execute_tracker_feedback(
                        repository=repository,
                        execute_task=execute_task,
                        report=report,
                    )
        except Exception as exc:
            logger.exception(
                "tracker_feedback_poll_failed",
                error=str(exc),
                feedback_limit=self.feedback_limit,
            )
            raise

        logger.info(
            "tracker_feedback_poll_completed",
            fetched_feedback_items=report.fetched_feedback_items,
            created_tracker_feedback_tasks=report.created_tracker_feedback_tasks,
            skipped_feedback_items=report.skipped_feedback_items,
        )
        return report

    def run_forever(
        self,
        *,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        iteration = 0
        tracker_elapsed = self.poll_interval
        feedback_elapsed = self.pr_poll_interval

        while max_iterations is None or iteration < max_iterations:
            if tracker_elapsed >= self.poll_interval:
                self.poll_tracker_once()
                tracker_elapsed = 0

            if feedback_elapsed >= self.pr_poll_interval:
                self.poll_pr_feedback_once()
                self.poll_tracker_feedback_once()
                feedback_elapsed = 0

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break

            sleep_seconds = min(
                self.poll_interval - tracker_elapsed,
                self.pr_poll_interval - feedback_elapsed,
            )
            sleep_fn(sleep_seconds)
            tracker_elapsed += sleep_seconds
            feedback_elapsed += sleep_seconds

    def _ingest_tracker_task(
        self,
        *,
        repository: TaskRepository,
        tracker_task: TrackerTask,
    ) -> IntakeOutcome:
        logger = _tracker_task_logger(tracker_task=tracker_task, tracker_name=self.tracker_name)
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
            logger.info(
                "fetch_task_created",
                task_id=fetch_task.id,
                root_task_id=fetch_task.root_id or fetch_task.id,
                repo_url=fetch_task.repo_url,
                repo_ref=fetch_task.repo_ref,
                workspace_key=fetch_task.workspace_key,
            )

        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        created_execute_task = False
        execute_payload = self._build_execute_input_payload(tracker_task=tracker_task)

        if execute_task is None:
            execute_task = repository.create_task(
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
                    input_payload=execute_payload,
                )
            )
            created_execute_task = True
        elif execute_task.input_payload != execute_payload:
            execute_task.input_payload = execute_payload

        if created_execute_task:
            logger.info(
                "execute_task_created",
                task_id=execute_task.id,
                root_task_id=execute_task.root_id or execute_task.id,
                parent_id=execute_task.parent_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
            )

        if not created_fetch_task and not created_execute_task:
            logger.info("task_intake_skipped")

        return IntakeOutcome(
            created_fetch_task=created_fetch_task,
            created_execute_task=created_execute_task,
        )

    def _build_execute_input_payload(
        self, *, tracker_task: TrackerTask
    ) -> dict[str, object] | None:
        input_payload = tracker_task.input_payload
        if tracker_task.parent_external_id is None:
            input_payload = mark_input_payload_estimate_only(payload=input_payload)
        return _dump_model_or_none(input_payload)

    def _ingest_pr_feedback(
        self,
        *,
        repository: TaskRepository,
        feedback_item: ScmPullRequestFeedback,
    ) -> PrFeedbackIntakeOutcome:
        logger = _worker_logger(
            tracker_name=self.tracker_name,
            pr_external_id=feedback_item.pr_external_id,
            feedback_comment_id=feedback_item.comment_id,
        )
        execute_task = repository.find_execute_task_by_pr_external_id(feedback_item.pr_external_id)
        if execute_task is None:
            logger.info("pr_feedback_unmapped")
            return PrFeedbackIntakeOutcome(unmapped_feedback_item=True)

        existing_feedback_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.PR_FEEDBACK,
            external_task_id=feedback_item.comment_id,
        )
        if existing_feedback_task is not None:
            logger.info(
                "pr_feedback_skipped",
                task_id=existing_feedback_task.id,
                root_task_id=existing_feedback_task.root_id or existing_feedback_task.id,
                parent_id=existing_feedback_task.parent_id,
            )
            return PrFeedbackIntakeOutcome(skipped_feedback_item=True)

        enriched_item = self._maybe_enrich_pr_metadata(
            feedback_item=feedback_item, execute_task=execute_task
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                status=TaskStatus.NEW,
                tracker_name=execute_task.tracker_name,
                external_task_id=enriched_item.comment_id,
                external_parent_id=enriched_item.pr_external_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                branch_name=execute_task.branch_name,
                pr_external_id=enriched_item.pr_external_id,
                pr_url=enriched_item.pr_url or execute_task.pr_url,
                input_payload=TaskInputPayload(pr_feedback=enriched_item).model_dump(mode="python"),
            )
        )
        logger.info(
            "pr_feedback_task_created",
            task_id=feedback_task.id,
            root_task_id=feedback_task.root_id or feedback_task.id,
            parent_id=feedback_task.parent_id,
            branch_name=feedback_task.branch_name,
            workspace_key=feedback_task.workspace_key,
        )
        return PrFeedbackIntakeOutcome(created_pr_feedback_task=True)

    def _maybe_enrich_pr_metadata(
        self,
        *,
        feedback_item: ScmPullRequestFeedback,
        execute_task,
    ) -> ScmPullRequestFeedback:
        if not feedback_item.pr_metadata.metadata.get(self._PR_FEEDBACK_UNRESOLVED_KEY):
            return feedback_item
        enriched_metadata = ScmPullRequestMetadata(
            execute_task_external_id=execute_task.external_task_id
            or execute_task.external_parent_id
            or str(execute_task.id),
            tracker_name=execute_task.tracker_name,
            workspace_key=execute_task.workspace_key,
            repo_url=execute_task.repo_url,
        )
        return feedback_item.model_copy(update={"pr_metadata": enriched_metadata})

    def _ingest_tracker_feedback(
        self,
        *,
        repository: TaskRepository,
        execute_task,
        feedback_item: TrackerCommentPayload,
    ) -> TrackerFeedbackIntakeOutcome:
        logger = _worker_logger(
            tracker_name=self.tracker_name,
            tracker_external_id=feedback_item.external_task_id,
            feedback_comment_id=feedback_item.comment_id,
        )
        if self._is_system_tracker_comment(feedback_item):
            logger.info("tracker_feedback_skipped_system_comment")
            return TrackerFeedbackIntakeOutcome(skipped_feedback_item=True)

        existing_feedback_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.TRACKER_FEEDBACK,
            external_task_id=feedback_item.comment_id,
        )
        if existing_feedback_task is not None:
            logger.info(
                "tracker_feedback_skipped",
                task_id=existing_feedback_task.id,
                root_task_id=existing_feedback_task.root_id or existing_feedback_task.id,
                parent_id=existing_feedback_task.parent_id,
            )
            return TrackerFeedbackIntakeOutcome(skipped_feedback_item=True)

        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.TRACKER_FEEDBACK,
                parent_id=execute_task.id,
                status=TaskStatus.NEW,
                tracker_name=execute_task.tracker_name,
                external_task_id=feedback_item.comment_id,
                external_parent_id=feedback_item.external_task_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                input_payload=TaskInputPayload(
                    tracker_feedback=feedback_item,
                    metadata={"source": "tracker_comment_poll"},
                ).model_dump(mode="python"),
            )
        )
        logger.info(
            "tracker_feedback_task_created",
            task_id=feedback_task.id,
            root_task_id=feedback_task.root_id or feedback_task.id,
            parent_id=feedback_task.parent_id,
            workspace_key=feedback_task.workspace_key,
        )
        return TrackerFeedbackIntakeOutcome(created_tracker_feedback_task=True)

    def _poll_execute_pr_feedback(
        self,
        *,
        repository: TaskRepository,
        execute_task,
        report: TrackerIntakeReport,
    ) -> TrackerIntakeReport:
        logger = _task_logger(execute_task)
        since_cursor = self._get_pr_feedback_cursor(execute_task)
        latest_cursor = since_cursor
        page_cursor: str | None = None

        logger.info(
            "pr_feedback_intake_started",
            since_cursor=since_cursor,
            feedback_limit=self.feedback_limit,
        )

        while True:
            feedback_page = self.scm.read_pr_feedback(
                ScmReadPrFeedbackQuery(
                    pr_external_id=execute_task.pr_external_id,
                    repo_url=execute_task.repo_url,
                    workspace_key=execute_task.workspace_key,
                    branch_name=execute_task.branch_name,
                    since_cursor=since_cursor,
                    page_cursor=page_cursor,
                    limit=self.feedback_limit,
                )
            )
            report = TrackerIntakeReport(
                fetched_feedback_items=report.fetched_feedback_items + len(feedback_page.items),
                created_pr_feedback_tasks=report.created_pr_feedback_tasks,
                skipped_feedback_items=report.skipped_feedback_items,
                unmapped_feedback_items=report.unmapped_feedback_items,
            )

            for feedback_item in feedback_page.items:
                outcome = self._ingest_pr_feedback(
                    repository=repository,
                    feedback_item=feedback_item,
                )
                report = TrackerIntakeReport(
                    fetched_feedback_items=report.fetched_feedback_items,
                    created_pr_feedback_tasks=report.created_pr_feedback_tasks
                    + int(outcome.created_pr_feedback_task),
                    skipped_feedback_items=report.skipped_feedback_items
                    + int(outcome.skipped_feedback_item),
                    unmapped_feedback_items=report.unmapped_feedback_items
                    + int(outcome.unmapped_feedback_item),
                )

            if feedback_page.latest_cursor is not None:
                latest_cursor = feedback_page.latest_cursor

            if feedback_page.next_page_cursor is None:
                break
            page_cursor = feedback_page.next_page_cursor

        self._set_pr_feedback_cursor(execute_task, latest_cursor)
        logger.info("pr_feedback_intake_completed", latest_cursor=latest_cursor)
        return report

    def _poll_execute_tracker_feedback(
        self,
        *,
        repository: TaskRepository,
        execute_task,
        report: TrackerIntakeReport,
    ) -> TrackerIntakeReport:
        task_context = self._build_task_context(repository=repository, task=execute_task)
        if task_context is None or not self._should_poll_tracker_feedback(
            execute_task, task_context
        ):
            return report

        logger = _task_logger(execute_task)
        since_cursor = self._get_feedback_cursor(
            execute_task, self._TRACKER_FEEDBACK_CURSOR_METADATA_KEY
        )
        latest_cursor = since_cursor
        page_cursor: str | None = None
        tracker_external_id = execute_task.external_parent_id
        if not tracker_external_id:
            return report

        logger.info(
            "tracker_feedback_intake_started",
            since_cursor=since_cursor,
            feedback_limit=self.feedback_limit,
            tracker_external_id=tracker_external_id,
        )

        while True:
            feedback_page = self.tracker.read_comments(
                TrackerReadCommentsQuery(
                    external_task_id=tracker_external_id,
                    since_cursor=since_cursor,
                    page_cursor=page_cursor,
                    limit=self.feedback_limit,
                )
            )
            report = TrackerIntakeReport(
                fetched_feedback_items=report.fetched_feedback_items + len(feedback_page.items),
                created_pr_feedback_tasks=report.created_pr_feedback_tasks,
                created_tracker_feedback_tasks=report.created_tracker_feedback_tasks,
                skipped_feedback_items=report.skipped_feedback_items,
                unmapped_feedback_items=report.unmapped_feedback_items,
            )

            for feedback_item in feedback_page.items:
                outcome = self._ingest_tracker_feedback(
                    repository=repository,
                    execute_task=execute_task,
                    feedback_item=feedback_item,
                )
                report = TrackerIntakeReport(
                    fetched_feedback_items=report.fetched_feedback_items,
                    created_pr_feedback_tasks=report.created_pr_feedback_tasks,
                    created_tracker_feedback_tasks=report.created_tracker_feedback_tasks
                    + int(outcome.created_tracker_feedback_task),
                    skipped_feedback_items=report.skipped_feedback_items
                    + int(outcome.skipped_feedback_item),
                    unmapped_feedback_items=report.unmapped_feedback_items,
                )

            if feedback_page.latest_cursor is not None:
                latest_cursor = feedback_page.latest_cursor

            if feedback_page.next_page_cursor is None:
                break
            page_cursor = feedback_page.next_page_cursor

        self._set_feedback_cursor(
            execute_task, self._TRACKER_FEEDBACK_CURSOR_METADATA_KEY, latest_cursor
        )
        logger.info("tracker_feedback_intake_completed", latest_cursor=latest_cursor)
        return report

    def _get_pr_feedback_cursor(self, execute_task) -> str | None:
        return self._get_feedback_cursor(execute_task, self._PR_FEEDBACK_CURSOR_METADATA_KEY)

    def _set_pr_feedback_cursor(self, execute_task, cursor: str | None) -> None:
        self._set_feedback_cursor(execute_task, self._PR_FEEDBACK_CURSOR_METADATA_KEY, cursor)

    def _get_feedback_cursor(self, execute_task, metadata_key: str) -> str | None:
        if execute_task.context is None:
            return None
        metadata = execute_task.context.get("metadata")
        if not isinstance(metadata, dict):
            return None
        cursor = metadata.get(metadata_key)
        return cursor if isinstance(cursor, str) else None

    def _set_feedback_cursor(self, execute_task, metadata_key: str, cursor: str | None) -> None:
        if cursor is None:
            return
        context = dict(execute_task.context or {})
        metadata = dict(context.get("metadata") or {})
        metadata[metadata_key] = cursor
        context["metadata"] = metadata
        execute_task.context = context

    def _is_system_tracker_comment(self, feedback_item: TrackerCommentPayload) -> bool:
        source = feedback_item.metadata.get(self._SYSTEM_COMMENT_SOURCE_KEY)
        return source == self._SYSTEM_COMMENT_SOURCE_VALUE

    def _should_poll_tracker_feedback(self, execute_task, task_context) -> bool:
        return execute_task.pr_external_id is None and should_skip_scm_artifacts(
            task_context=task_context
        )

    def _build_task_context(self, *, repository: TaskRepository, task):
        try:
            return ContextBuilder().build_for_task(
                task=task,
                task_chain=repository.load_task_chain(task.root_id or task.id),
            )
        except ValueError:
            return None


def build_tracker_intake_worker(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> TrackerIntakeWorker:
    active_runtime = runtime or create_runtime_container()
    return TrackerIntakeWorker(
        tracker=active_runtime.tracker,
        scm=active_runtime.scm,
        tracker_name=active_runtime.settings.tracker_adapter,
        session_factory=session_factory or get_session_factory(),
        poll_interval=active_runtime.settings.tracker_poll_interval,
        pr_poll_interval=active_runtime.settings.pr_poll_interval,
        fetch_limit=active_runtime.settings.tracker_fetch_limit,
        feedback_limit=active_runtime.settings.pr_feedback_fetch_limit,
    )


def _dump_model_or_none(value: SchemaModel | None) -> dict[str, object] | None:
    if value is None:
        return None
    return value.model_dump(mode="python")


def _worker_logger(**fields: object):
    return get_logger(__name__, component="worker1").bind(**fields)


def _tracker_task_logger(*, tracker_task: TrackerTask, tracker_name: str):
    return _worker_logger(
        tracker_name=tracker_name,
        tracker_external_id=tracker_task.external_id,
        tracker_parent_external_id=tracker_task.parent_external_id,
        repo_url=tracker_task.repo_url,
        repo_ref=tracker_task.repo_ref,
        workspace_key=tracker_task.workspace_key,
    )


def _task_logger(task):
    return _worker_logger(
        task_id=task.id,
        root_task_id=task.root_id or task.id,
        parent_id=task.parent_id,
        task_type=task.task_type.value,
        tracker_name=task.tracker_name,
        tracker_external_id=task.external_task_id,
        tracker_parent_external_id=task.external_parent_id,
        workspace_key=task.workspace_key,
        branch_name=task.branch_name,
        pr_external_id=task.pr_external_id,
    )


__all__ = [
    "IntakeOutcome",
    "PrFeedbackIntakeOutcome",
    "TrackerIntakeReport",
    "TrackerIntakeWorker",
    "build_tracker_intake_worker",
]
