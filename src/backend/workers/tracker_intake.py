from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.logging_setup import get_logger
from backend.models import Task
from backend.protocols.scm import ScmProtocol
from backend.protocols.tracker import TrackerProtocol
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import (
    SchemaModel,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmReadPrFeedbackQuery,
    TaskInputPayload,
    TrackerFetchTasksQuery,
    TrackerTask,
)
from backend.services.user_content_hash import compute_user_content_hash
from backend.task_constants import TaskStatus, TaskType

_LAST_TRIAGE_USER_CONTENT_HASH_KEY = "last_triage_user_content_hash"
_LAST_REOPEN_CONSUMED_DONE_IMPL_ID_KEY = "last_reopen_consumed_done_impl_id"


@dataclass(frozen=True, slots=True)
class TrackerIntakeReport:
    fetched_count: int = 0
    created_fetch_tasks: int = 0
    created_execute_tasks: int = 0
    skipped_tasks: int = 0
    fetched_feedback_items: int = 0
    created_pr_feedback_tasks: int = 0
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
    _PR_FEEDBACK_UNRESOLVED_KEY = "_hl_unresolved"

    def poll_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        report = self.poll_tracker_once()
        feedback_report = self.poll_pr_feedback_once()
        combined_report = TrackerIntakeReport(
            fetched_count=report.fetched_count,
            created_fetch_tasks=report.created_fetch_tasks,
            created_execute_tasks=report.created_execute_tasks,
            skipped_tasks=report.skipped_tasks,
            fetched_feedback_items=feedback_report.fetched_feedback_items,
            created_pr_feedback_tasks=feedback_report.created_pr_feedback_tasks,
            skipped_feedback_items=feedback_report.skipped_feedback_items,
            unmapped_feedback_items=feedback_report.unmapped_feedback_items,
        )
        logger.info(
            "tracker_intake_cycle_completed",
            fetched_count=combined_report.fetched_count,
            created_fetch_tasks=combined_report.created_fetch_tasks,
            created_execute_tasks=combined_report.created_execute_tasks,
            skipped_tasks=combined_report.skipped_tasks,
            fetched_feedback_items=combined_report.fetched_feedback_items,
            created_pr_feedback_tasks=combined_report.created_pr_feedback_tasks,
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

        if fetch_task is None:
            return self._create_initial_fetch_and_execute(
                repository=repository,
                tracker_task=tracker_task,
                logger=logger,
            )

        return self._handle_existing_fetch(
            repository=repository,
            fetch_task=fetch_task,
            tracker_task=tracker_task,
            logger=logger,
        )

    def _create_initial_fetch_and_execute(
        self,
        *,
        repository: TaskRepository,
        tracker_task: TrackerTask,
        logger,
    ) -> IntakeOutcome:
        incoming_hash = compute_user_content_hash(tracker_task)
        initial_context = tracker_task.context.model_dump(mode="python")
        initial_metadata = dict(initial_context.get("metadata") or {})
        initial_metadata[_LAST_TRIAGE_USER_CONTENT_HASH_KEY] = incoming_hash
        initial_context["metadata"] = initial_metadata
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
                context=initial_context,
                input_payload=_dump_model_or_none(tracker_task.input_payload),
            )
        )
        logger.info(
            "fetch_task_created",
            task_id=fetch_task.id,
            root_task_id=fetch_task.root_id or fetch_task.id,
            repo_url=fetch_task.repo_url,
            repo_ref=fetch_task.repo_ref,
            workspace_key=fetch_task.workspace_key,
        )
        execute_task = self._create_triage_execute(
            repository=repository,
            fetch_task=fetch_task,
            tracker_task=tracker_task,
            logger=logger,
            event_name="execute_task_created",
        )
        return IntakeOutcome(
            created_fetch_task=True,
            created_execute_task=execute_task is not None,
        )

    def _handle_existing_fetch(
        self,
        *,
        repository: TaskRepository,
        fetch_task: Task,
        tracker_task: TrackerTask,
        logger,
    ) -> IntakeOutcome:
        """Re-triage protocol for an existing fetch (plan §6.7a).

        Detects user edits via content-hash, decides whether the cluster needs
        a new triage execute, supersedes pending impl tasks when needed, and
        defends against reopen self-loops via ``done_impl_delivered`` and the
        ``last_reopen_consumed_done_impl_id`` marker.
        """

        # Recovery path: fetch exists but its first execute child is missing
        # (defective cluster state — possible after a partial migration or a
        # crash between fetch and execute creation). Restore by creating the
        # initial triage execute so the cluster can make forward progress.
        if (
            repository.find_child_task(
                parent_id=fetch_task.id, task_type=TaskType.EXECUTE
            )
            is None
        ):
            execute_task = self._create_triage_execute(
                repository=repository,
                fetch_task=fetch_task,
                tracker_task=tracker_task,
                logger=logger,
                event_name="execute_task_created",
            )
            return IntakeOutcome(created_execute_task=execute_task is not None)

        incoming_hash = compute_user_content_hash(tracker_task)
        existing_context = fetch_task.context or {}
        existing_metadata = dict(existing_context.get("metadata") or {})
        stored_hash = existing_metadata.get(_LAST_TRIAGE_USER_CONTENT_HASH_KEY)
        content_changed = incoming_hash != stored_hash

        pending_triage = repository.find_pending_triage_execute(parent_id=fetch_task.id)
        processing_triage = repository.find_processing_triage_execute(parent_id=fetch_task.id)
        root_id = fetch_task.root_id or fetch_task.id
        pending_impl = repository.find_pending_implementation_execute_for_root(
            root_id=root_id
        )
        processing_impl = repository.find_processing_implementation_execute_for_root(
            root_id=root_id
        )
        done_impl = repository.find_done_implementation_execute_for_root(root_id=root_id)

        # Reopen detection (plan §6.7a — closures CC1 / DD1 / EE1).
        last_consumed_id = existing_metadata.get(_LAST_REOPEN_CONSUMED_DONE_IMPL_ID_KEY)
        reopen_already_consumed = (
            done_impl is not None and last_consumed_id == done_impl.id
        )

        deliver_for_done_impl = (
            repository.find_child_task(parent_id=done_impl.id, task_type=TaskType.DELIVER)
            if done_impl is not None
            else None
        )
        done_impl_delivered = (
            deliver_for_done_impl is not None
            and deliver_for_done_impl.status == TaskStatus.DONE
        )

        is_reopen = (
            tracker_task.status == TaskStatus.NEW
            and done_impl is not None
            and done_impl_delivered
            and pending_impl is None
            and processing_impl is None
            and pending_triage is None
            and processing_triage is None
            and not reopen_already_consumed
        )

        if not content_changed and not is_reopen:
            logger.info("task_intake_skipped")
            return IntakeOutcome()

        # Always refresh fetch.context (incl. references) when something changed.
        new_context = tracker_task.context.model_dump(mode="python")
        merged_metadata = dict(existing_metadata)
        merged_metadata.update(new_context.get("metadata") or {})
        if processing_triage is None:
            merged_metadata[_LAST_TRIAGE_USER_CONTENT_HASH_KEY] = incoming_hash
        new_context["metadata"] = merged_metadata
        fetch_task.context = new_context
        flag_modified(fetch_task, "context")
        logger.info(
            "fetch_context_refreshed_on_user_edit",
            task_id=fetch_task.id,
            root_task_id=root_id,
            processing_triage_present=processing_triage is not None,
            pending_triage_present=pending_triage is not None,
            hash_updated=processing_triage is None,
            content_changed=content_changed,
            is_reopen=is_reopen,
        )

        if processing_triage is not None:
            return IntakeOutcome()

        if pending_triage is not None:
            # Collapse subsequent edits into the still-pending triage snapshot.
            pending_triage.context = tracker_task.context.model_dump(mode="python")
            flag_modified(pending_triage, "context")
            logger.info(
                "pending_triage_context_refreshed",
                task_id=pending_triage.id,
                root_task_id=root_id,
            )
            return IntakeOutcome()

        last_triage = repository.find_last_completed_triage_execute(parent_id=fetch_task.id)
        last_was_escalation = (
            last_triage is not None
            and _read_escalation_kind(last_triage)
            in {"rfi", "decomposition", "system_design"}
        )

        if processing_impl is not None:
            # In-flight impl: edits during this window go through PR feedback.
            return IntakeOutcome()

        # Order is important (plan §6.7a — closure AA1): pending impl is
        # always fresher than any done impl in the same root_id, so it must be
        # checked first to avoid stale-Brief regressions on reopen+edit.
        if pending_impl is not None:
            superseded_marker = (
                f"superseded_by_user_edit_after_triage_"
                f"{last_triage.id if last_triage is not None else 'unknown'}"
            )
            pending_impl.status = TaskStatus.FAILED
            pending_impl.error = superseded_marker
            pending_impl.result_payload = {
                "schema_version": 1,
                "outcome": "blocked",
                "summary": (
                    "Implementation execute superseded by user edit before "
                    "start; re-triage created."
                ),
                "metadata": {
                    "superseded_reason": "user_edit",
                    "superseded_at": datetime.now(UTC).isoformat(),
                },
            }
            logger.info(
                "pending_implementation_execute_superseded",
                task_id=pending_impl.id,
                root_task_id=root_id,
                marker=superseded_marker,
            )
            execute_task = self._create_triage_execute(
                repository=repository,
                fetch_task=fetch_task,
                tracker_task=tracker_task,
                logger=logger,
                event_name="retriage_execute_task_created",
            )
            return IntakeOutcome(created_execute_task=execute_task is not None)

        if done_impl is not None:
            # Plan §6.7a closure EE1: reopen-branch must trigger on
            # ``is_reopen`` (which includes ``done_impl_delivered``), NOT on
            # the raw ``tracker_task.status == NEW``. Otherwise a user edit
            # during the impl-DONE / deliver_impl-DONE race would create a
            # phantom triage even though Linear had not yet been advanced to
            # DONE.
            if is_reopen:
                # Mark consumed BEFORE creating the new triage so a subsequent
                # poll without further changes does not loop (plan §6.7a DD1).
                merged_metadata[_LAST_REOPEN_CONSUMED_DONE_IMPL_ID_KEY] = done_impl.id
                new_context["metadata"] = merged_metadata
                fetch_task.context = new_context
                flag_modified(fetch_task, "context")
                logger.info(
                    "reopen_consumed_marker_set",
                    task_id=fetch_task.id,
                    root_task_id=root_id,
                    consumed_done_impl_id=done_impl.id,
                )
                execute_task = self._create_triage_execute(
                    repository=repository,
                    fetch_task=fetch_task,
                    tracker_task=tracker_task,
                    logger=logger,
                    event_name="retriage_execute_task_created",
                )
                return IntakeOutcome(created_execute_task=execute_task is not None)
            # Edit during deliver-window OR after pipeline completion without
            # a Linear reopen — snapshot already updated, no triage created.
            return IntakeOutcome()

        if last_was_escalation:
            execute_task = self._create_triage_execute(
                repository=repository,
                fetch_task=fetch_task,
                tracker_task=tracker_task,
                logger=logger,
                event_name="retriage_execute_task_created",
            )
            return IntakeOutcome(created_execute_task=execute_task is not None)

        # Strange state: last triage was SP=1/2/3 but no impl exists and no
        # earlier escalation either. Diagnosed via retro-feedback, not
        # auto-recovered.
        return IntakeOutcome()

    def _create_triage_execute(
        self,
        *,
        repository: TaskRepository,
        fetch_task: Task,
        tracker_task: TrackerTask,
        logger,
        event_name: str,
    ) -> Task | None:
        existing_payload = tracker_task.input_payload or TaskInputPayload()
        execute_input_payload = existing_payload.model_dump(mode="python")
        if execute_input_payload.get("action") is None:
            execute_input_payload["action"] = "triage"
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
                input_payload=execute_input_payload,
            )
        )
        logger.info(
            event_name,
            task_id=execute_task.id,
            root_task_id=execute_task.root_id or execute_task.id,
            parent_id=execute_task.parent_id,
            repo_url=execute_task.repo_url,
            repo_ref=execute_task.repo_ref,
            workspace_key=execute_task.workspace_key,
        )
        return execute_task

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

    def _get_pr_feedback_cursor(self, execute_task) -> str | None:
        if execute_task.context is None:
            return None
        metadata = execute_task.context.get("metadata")
        if not isinstance(metadata, dict):
            return None
        cursor = metadata.get(self._PR_FEEDBACK_CURSOR_METADATA_KEY)
        return cursor if isinstance(cursor, str) else None

    def _set_pr_feedback_cursor(self, execute_task, cursor: str | None) -> None:
        if cursor is None:
            return
        context = dict(execute_task.context or {})
        metadata = dict(context.get("metadata") or {})
        metadata[self._PR_FEEDBACK_CURSOR_METADATA_KEY] = cursor
        context["metadata"] = metadata
        execute_task.context = context


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


def _read_escalation_kind(task: Task) -> str | None:
    """Read ``result_payload.delivery.escalation_kind`` defensively.

    Returns ``None`` if the payload is missing or malformed — callers treat the
    ``None`` outcome as "not an escalation" so the re-triage flow stays
    permissive in the face of legacy or partial payloads.
    """
    payload = task.result_payload
    if not isinstance(payload, dict):
        return None
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        return None
    kind = delivery.get("escalation_kind")
    if isinstance(kind, str):
        return kind
    return None


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
