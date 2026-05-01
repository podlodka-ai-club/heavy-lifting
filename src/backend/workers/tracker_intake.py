from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.logging_setup import get_logger
from backend.protocols.scm import ScmProtocol
from backend.protocols.telegram import TelegramProtocol
from backend.protocols.tracker import TrackerProtocol
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import (
    SchemaModel,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmReadPrFeedbackQuery,
    TaskInputPayload,
    TaskResultPayload,
    TelegramPollUpdatesQuery,
    TelegramSendMessagePayload,
    TelegramUpdateEnvelope,
    TrackerCommentCreatePayload,
    TrackerFetchTasksQuery,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
)
from backend.services.context_builder import parse_task_context, parse_task_result_payload
from backend.services.telegram_clarification import (
    TELEGRAM_CLARIFICATION_ROLE,
    build_proposal,
    dump_proposal,
    format_proposal_message,
    is_confirmation,
    load_proposal,
    proposal_subtask_to_tracker_payload,
)
from backend.task_constants import TaskStatus, TaskType


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
    processed_telegram_updates: int = 0
    proposed_telegram_clarifications: int = 0
    finalized_telegram_clarifications: int = 0
    failed_telegram_clarifications: int = 0


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
    telegram: TelegramProtocol | None = None
    poll_interval: int = 30
    pr_poll_interval: int = 60
    telegram_poll_interval: int = 15
    fetch_limit: int = 100
    feedback_limit: int = 100
    telegram_fetch_limit: int = 100
    telegram_group_chat_id: str | None = None
    telegram_message_thread_id: int | None = None
    fetch_statuses: Sequence[TaskStatus] = (TaskStatus.NEW,)

    _PR_FEEDBACK_CURSOR_METADATA_KEY = "scm_pr_feedback_cursor"
    _PR_FEEDBACK_UNRESOLVED_KEY = "_hl_unresolved"

    def poll_once(self) -> TrackerIntakeReport:
        logger = _worker_logger(tracker_name=self.tracker_name)
        report = self.poll_tracker_once()
        feedback_report = self.poll_pr_feedback_once()
        telegram_report = self.poll_telegram_once()
        combined_report = TrackerIntakeReport(
            fetched_count=report.fetched_count,
            created_fetch_tasks=report.created_fetch_tasks,
            created_execute_tasks=report.created_execute_tasks,
            skipped_tasks=report.skipped_tasks,
            fetched_feedback_items=feedback_report.fetched_feedback_items,
            created_pr_feedback_tasks=feedback_report.created_pr_feedback_tasks,
            skipped_feedback_items=feedback_report.skipped_feedback_items,
            unmapped_feedback_items=feedback_report.unmapped_feedback_items,
            processed_telegram_updates=telegram_report.processed_telegram_updates,
            proposed_telegram_clarifications=telegram_report.proposed_telegram_clarifications,
            finalized_telegram_clarifications=telegram_report.finalized_telegram_clarifications,
            failed_telegram_clarifications=telegram_report.failed_telegram_clarifications,
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
            processed_telegram_updates=combined_report.processed_telegram_updates,
            proposed_telegram_clarifications=combined_report.proposed_telegram_clarifications,
            finalized_telegram_clarifications=combined_report.finalized_telegram_clarifications,
            failed_telegram_clarifications=combined_report.failed_telegram_clarifications,
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

    def poll_telegram_once(self) -> TrackerIntakeReport:
        if self.telegram is None or not self.telegram_group_chat_id:
            return TrackerIntakeReport()

        logger = _worker_logger(tracker_name=self.tracker_name)
        logger.info(
            "telegram_clarification_poll_started",
            fetch_limit=self.telegram_fetch_limit,
            telegram_chat_id=self.telegram_group_chat_id,
        )
        report = TrackerIntakeReport()
        try:
            with session_scope(session_factory=self.session_factory) as session:
                repository = TaskRepository(session)
                tasks = repository.list_pending_telegram_clarification_tasks(
                    role=TELEGRAM_CLARIFICATION_ROLE
                )
                for task in tasks:
                    report = self._poll_telegram_clarification_task(
                        repository=repository,
                        task=task,
                        report=report,
                    )
        except Exception as exc:
            logger.exception("telegram_clarification_poll_failed", error=str(exc))
            raise

        logger.info(
            "telegram_clarification_poll_completed",
            processed_telegram_updates=report.processed_telegram_updates,
            proposed_telegram_clarifications=report.proposed_telegram_clarifications,
            finalized_telegram_clarifications=report.finalized_telegram_clarifications,
            failed_telegram_clarifications=report.failed_telegram_clarifications,
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
        telegram_elapsed = self.telegram_poll_interval

        while max_iterations is None or iteration < max_iterations:
            if tracker_elapsed >= self.poll_interval:
                self.poll_tracker_once()
                tracker_elapsed = 0

            if feedback_elapsed >= self.pr_poll_interval:
                self.poll_pr_feedback_once()
                feedback_elapsed = 0

            if telegram_elapsed >= self.telegram_poll_interval:
                self.poll_telegram_once()
                telegram_elapsed = 0

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break

            sleep_seconds = min(
                self.poll_interval - tracker_elapsed,
                self.pr_poll_interval - feedback_elapsed,
                self.telegram_poll_interval - telegram_elapsed,
            )
            sleep_fn(sleep_seconds)
            tracker_elapsed += sleep_seconds
            feedback_elapsed += sleep_seconds
            telegram_elapsed += sleep_seconds

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
                    input_payload=_dump_model_or_none(tracker_task.input_payload),
                )
            )
            created_execute_task = True

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

    def _poll_telegram_clarification_task(
        self,
        *,
        repository: TaskRepository,
        task,
        report: TrackerIntakeReport,
    ) -> TrackerIntakeReport:
        logger = _task_logger(task)
        try:
            if self.telegram is None:
                return report
            metadata = self._telegram_metadata(task)
            offset = metadata.get("update_offset")
            updates = self.telegram.poll_updates(
                TelegramPollUpdatesQuery(
                    offset=offset if isinstance(offset, int) else None,
                    limit=self.telegram_fetch_limit,
                )
            )

            transcript = _normalize_transcript(metadata.get("transcript"))
            seen_update_ids = {item.get("update_id") for item in transcript}
            accepted_updates: list[TelegramUpdateEnvelope] = []
            latest_update_id = offset if isinstance(offset, int) else None
            discussion_message_ids = self._telegram_discussion_message_ids(
                metadata=metadata,
                transcript=transcript,
            )
            for update in updates:
                latest_update_id = (
                    update.update_id
                    if latest_update_id is None
                    else max(latest_update_id, update.update_id)
                )
                if not self._is_relevant_telegram_update(
                    update=update,
                    discussion_message_ids=discussion_message_ids,
                ):
                    continue
                if update.update_id in seen_update_ids:
                    continue
                transcript.append(
                    {
                        "update_id": update.update_id,
                        "message_id": update.message_id,
                        "author": update.author,
                        "text": update.text,
                        "reply_to_message_id": update.reply_to_message_id,
                        "message_thread_id": update.message_thread_id,
                    }
                )
                accepted_updates.append(update)
                seen_update_ids.add(update.update_id)
                discussion_message_ids.add(update.message_id)

            if latest_update_id is not None:
                metadata["update_offset"] = latest_update_id + 1
            metadata["transcript"] = transcript
            self._store_telegram_metadata(task, metadata)

            updated_count = len(accepted_updates)
            report = _merge_telegram_report(
                report,
                TrackerIntakeReport(processed_telegram_updates=updated_count),
            )

            confirmation_update = self._find_confirmation_update(
                metadata=metadata,
                updates=accepted_updates,
            )
            if confirmation_update is not None:
                self._finalize_telegram_clarification(
                    repository=repository,
                    task=task,
                    metadata=metadata,
                    confirmation_update=confirmation_update,
                )
                logger.info(
                    "telegram_clarification_finalized",
                    confirmation_update_id=confirmation_update.update_id,
                )
                return _merge_telegram_report(
                    report,
                    TrackerIntakeReport(finalized_telegram_clarifications=1),
                )

            if self._should_send_telegram_proposal(metadata=metadata, updates=accepted_updates):
                agent_payload = self._telegram_agent_payload(metadata)
                original_context = (
                    parse_task_context(task.parent) if task.parent is not None else None
                )
                proposal = build_proposal(
                    original_context=original_context or parse_task_context(task),
                    agent_payload=agent_payload,
                    transcript=transcript,
                )
                if proposal.open_questions:
                    return report
                proposal_message = self.telegram.send_message(
                    TelegramSendMessagePayload(
                        chat_id=self.telegram_group_chat_id or str(metadata.get("chat_id")),
                        text=format_proposal_message(proposal),
                        message_thread_id=self.telegram_message_thread_id,
                        reply_to_message_id=self._metadata_int(metadata, "root_message_id"),
                        metadata={"task_id": task.id, "role": TELEGRAM_CLARIFICATION_ROLE},
                    )
                )
                metadata["proposal"] = dump_proposal(proposal)
                metadata["proposal_message_id"] = proposal_message.message_id
                metadata["proposal_update_floor"] = metadata.get("update_offset")
                self._store_telegram_metadata(task, metadata)
                logger.info(
                    "telegram_clarification_proposed",
                    proposal_message_id=proposal_message.message_id,
                    subtask_count=len(proposal.subtasks),
                )
                return _merge_telegram_report(
                    report,
                    TrackerIntakeReport(proposed_telegram_clarifications=1),
                )

            return report
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            logger.exception("telegram_clarification_task_failed", error=str(exc))
            return _merge_telegram_report(
                report,
                TrackerIntakeReport(failed_telegram_clarifications=1),
            )

    def _is_relevant_telegram_update(
        self,
        *,
        update: TelegramUpdateEnvelope,
        discussion_message_ids: set[int],
    ) -> bool:
        if update.chat_id != self.telegram_group_chat_id:
            return False
        configured_thread_id = self.telegram_message_thread_id
        if configured_thread_id is not None and update.message_thread_id != configured_thread_id:
            return False
        if update.reply_to_message_id in discussion_message_ids:
            return True
        return update.message_id in discussion_message_ids

    def _telegram_discussion_message_ids(
        self,
        *,
        metadata: dict[str, object],
        transcript: list[dict[str, object]],
    ) -> set[int]:
        message_ids = {
            value
            for value in (
                self._metadata_int(metadata, "root_message_id"),
                self._metadata_int(metadata, "proposal_message_id"),
            )
            if value is not None
        }
        for item in transcript:
            message_id = item.get("message_id")
            if isinstance(message_id, int):
                message_ids.add(message_id)
        return message_ids

    def _find_confirmation_update(
        self,
        *,
        metadata: dict[str, object],
        updates: Sequence[TelegramUpdateEnvelope],
    ) -> TelegramUpdateEnvelope | None:
        proposal_message_id = self._metadata_int(metadata, "proposal_message_id")
        if proposal_message_id is None:
            return None
        proposal_floor = self._metadata_int(metadata, "proposal_update_floor") or 0
        for update in updates:
            if update.update_id < proposal_floor:
                continue
            if is_confirmation(update.text):
                return update
        return None

    def _should_send_telegram_proposal(
        self,
        *,
        metadata: dict[str, object],
        updates: Sequence[TelegramUpdateEnvelope],
    ) -> bool:
        if not metadata.get("transcript"):
            return False
        proposal_message_id = self._metadata_int(metadata, "proposal_message_id")
        if proposal_message_id is None:
            return True
        proposal_floor = self._metadata_int(metadata, "proposal_update_floor") or 0
        return any(
            update.update_id >= proposal_floor and not is_confirmation(update.text)
            for update in updates
        )

    def _finalize_telegram_clarification(
        self,
        *,
        repository: TaskRepository,
        task,
        metadata: dict[str, object],
        confirmation_update: TelegramUpdateEnvelope,
    ) -> None:
        proposal = load_proposal(metadata.get("proposal"))
        if proposal is None:
            raise ValueError("Telegram clarification has no valid proposal to finalize")
        tracker_task_id = self._resolve_clarification_tracker_task_id(task)
        self._persist_telegram_finalization_guard(
            repository=repository,
            task=task,
            metadata=metadata,
            tracker_task_id=tracker_task_id,
            confirmation_update=confirmation_update,
            subtask_count=len(proposal.subtasks),
        )

        final_comment = format_proposal_message(proposal)
        self.tracker.add_comment(
            TrackerCommentCreatePayload(
                external_task_id=tracker_task_id,
                body=final_comment,
                metadata={
                    "task_id": task.id,
                    "role": TELEGRAM_CLARIFICATION_ROLE,
                    "telegram_root_message_id": metadata.get("root_message_id"),
                },
            )
        )
        for subtask in proposal.subtasks:
            context, input_payload = proposal_subtask_to_tracker_payload(
                subtask=subtask,
                source_metadata={"clarification_task_id": task.id},
            )
            self.tracker.create_subtask(
                TrackerSubtaskCreatePayload(
                    parent_external_id=tracker_task_id,
                    context=context,
                    task_type=TaskType.EXECUTE,
                    status=TaskStatus.NEW,
                    input_payload=input_payload,
                    repo_url=task.repo_url,
                    repo_ref=task.repo_ref,
                    workspace_key=task.workspace_key,
                    metadata={"source": TELEGRAM_CLARIFICATION_ROLE},
                )
            )
        self.tracker.update_status(
            TrackerStatusUpdatePayload(
                external_task_id=tracker_task_id,
                status=TaskStatus.DONE,
            )
        )
        agent_payload = self._telegram_agent_payload(metadata)
        finalization = dict(metadata.get("finalization") or {})
        finalization["status"] = "completed"
        metadata["finalization"] = finalization
        result_metadata = dict(agent_payload.metadata)
        result_metadata.update(
            {
                "delivery_mode": TELEGRAM_CLARIFICATION_ROLE,
                "tracker_external_id": tracker_task_id,
                "subtasks_created": len(proposal.subtasks),
                "telegram": metadata,
            }
        )
        task.status = TaskStatus.DONE
        task.error = None
        task.result_payload = TaskResultPayload(
            summary=proposal.summary,
            details=final_comment,
            metadata=result_metadata,
        ).model_dump(mode="json")

    def _persist_telegram_finalization_guard(
        self,
        *,
        repository: TaskRepository,
        task,
        metadata: dict[str, object],
        tracker_task_id: str,
        confirmation_update: TelegramUpdateEnvelope,
        subtask_count: int,
    ) -> None:
        if task.status == TaskStatus.DONE:
            raise ValueError("Telegram clarification finalization is already guarded")
        if task.status != TaskStatus.PROCESSING:
            raise ValueError(
                f"Telegram clarification task must be processing, got {task.status.value}"
            )

        guarded_metadata = dict(metadata)
        guarded_metadata["finalization"] = {
            "status": "started",
            "tracker_external_id": tracker_task_id,
            "confirmation_update_id": confirmation_update.update_id,
            "subtasks_planned": subtask_count,
            "manual_repair_required_on_interruption": True,
        }
        metadata.clear()
        metadata.update(guarded_metadata)
        task.status = TaskStatus.DONE
        task.error = None
        task.result_payload = TaskResultPayload(
            summary="Telegram clarification finalization started.",
            details=(
                "Local guard was persisted before external tracker side effects. "
                "If finalization is interrupted, manual repair is required."
            ),
            metadata={
                "delivery_mode": TELEGRAM_CLARIFICATION_ROLE,
                "tracker_external_id": tracker_task_id,
                "telegram": guarded_metadata,
            },
        ).model_dump(mode="json")
        repository.session.commit()

    def _resolve_clarification_tracker_task_id(self, task) -> str:
        if task.external_parent_id:
            return task.external_parent_id
        if task.parent is not None and task.parent.external_parent_id:
            return task.parent.external_parent_id
        root = task.root
        if root is not None and root.external_task_id:
            return root.external_task_id
        raise ValueError("Telegram clarification task requires tracker external id")

    def _telegram_metadata(self, task) -> dict[str, object]:
        result_payload = parse_task_result_payload(task)
        if result_payload is None:
            raise ValueError("Telegram clarification task requires result_payload")
        telegram = result_payload.metadata.get("telegram")
        if not isinstance(telegram, dict):
            raise ValueError("Telegram clarification task requires metadata.telegram")
        return {str(key): value for key, value in telegram.items() if isinstance(key, str)}

    def _telegram_agent_payload(self, metadata: dict[str, object]) -> TaskResultPayload:
        payload = metadata.get("agent_payload")
        if isinstance(payload, dict):
            return TaskResultPayload.model_validate(payload)
        return TaskResultPayload(summary="Telegram clarification")

    def _store_telegram_metadata(self, task, metadata: dict[str, object]) -> None:
        result_payload = parse_task_result_payload(task)
        if result_payload is None:
            result_payload = TaskResultPayload(summary="Telegram clarification pending.")
        result_metadata = dict(result_payload.metadata)
        result_metadata["telegram"] = metadata
        task.result_payload = result_payload.model_copy(
            update={"metadata": result_metadata}
        ).model_dump(mode="json")

    @staticmethod
    def _metadata_int(metadata: dict[str, object], key: str) -> int | None:
        value = metadata.get(key)
        return value if isinstance(value, int) else None


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
        telegram=active_runtime.telegram,
        poll_interval=active_runtime.settings.tracker_poll_interval,
        pr_poll_interval=active_runtime.settings.pr_poll_interval,
        telegram_poll_interval=active_runtime.settings.telegram_poll_interval,
        fetch_limit=active_runtime.settings.tracker_fetch_limit,
        feedback_limit=active_runtime.settings.pr_feedback_fetch_limit,
        telegram_fetch_limit=active_runtime.settings.telegram_fetch_limit,
        telegram_group_chat_id=active_runtime.settings.telegram_group_chat_id,
        telegram_message_thread_id=active_runtime.settings.telegram_message_thread_id,
    )


def _dump_model_or_none(value: SchemaModel | None) -> dict[str, object] | None:
    if value is None:
        return None
    return value.model_dump(mode="python")


def _normalize_transcript(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    transcript: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        transcript.append(
            {str(key): item_value for key, item_value in item.items() if isinstance(key, str)}
        )
    return transcript


def _merge_telegram_report(
    left: TrackerIntakeReport,
    right: TrackerIntakeReport,
) -> TrackerIntakeReport:
    return TrackerIntakeReport(
        fetched_count=left.fetched_count + right.fetched_count,
        created_fetch_tasks=left.created_fetch_tasks + right.created_fetch_tasks,
        created_execute_tasks=left.created_execute_tasks + right.created_execute_tasks,
        skipped_tasks=left.skipped_tasks + right.skipped_tasks,
        fetched_feedback_items=left.fetched_feedback_items + right.fetched_feedback_items,
        created_pr_feedback_tasks=(
            left.created_pr_feedback_tasks + right.created_pr_feedback_tasks
        ),
        skipped_feedback_items=left.skipped_feedback_items + right.skipped_feedback_items,
        unmapped_feedback_items=left.unmapped_feedback_items + right.unmapped_feedback_items,
        processed_telegram_updates=(
            left.processed_telegram_updates + right.processed_telegram_updates
        ),
        proposed_telegram_clarifications=(
            left.proposed_telegram_clarifications + right.proposed_telegram_clarifications
        ),
        finalized_telegram_clarifications=(
            left.finalized_telegram_clarifications + right.finalized_telegram_clarifications
        ),
        failed_telegram_clarifications=(
            left.failed_telegram_clarifications + right.failed_telegram_clarifications
        ),
    )


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
