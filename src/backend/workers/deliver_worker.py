from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.logging_setup import configure_logging, get_logger
from backend.models import Task
from backend.protocols.tracker import TrackerProtocol
from backend.repositories.task_repository import TaskRepository
from backend.schemas import (
    TaskLink,
    TaskResultPayload,
    TrackerCommentCreatePayload,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerTaskEstimateUpdatePayload,
)
from backend.services.context_builder import ContextBuilder
from backend.services.tracker_task_resolution import resolve_tracker_external_task_id
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class DeliverWorkerReport:
    processed_deliver_tasks: int = 0
    failed_deliver_tasks: int = 0


@dataclass(slots=True)
class DeliverWorker:
    tracker: TrackerProtocol
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)

    def poll_once(self) -> DeliverWorkerReport:
        with session_scope(session_factory=self.session_factory) as session:
            repository = TaskRepository(session)
            task = repository.poll_task(task_type=TaskType.DELIVER)
            if task is None:
                return DeliverWorkerReport()

            task.attempt += 1
            logger = _task_logger(task, attempt=task.attempt)

            try:
                task_chain = repository.load_task_chain(task.root_id or task.id)
                task_context = self.context_builder.build_for_task(task=task, task_chain=task_chain)
                delivery_result = self._resolve_delivery_result(task_context=task_context)
                if delivery_result is None:
                    raise ValueError("deliver task requires a completed execute result")

                tracker_task_id = self._resolve_tracker_task_id(task_context=task_context)
                comment_body = self._build_comment_body(execute_result=delivery_result)
                links = self._build_links(execute_result=delivery_result)
                logger.info(
                    "delivery_started",
                    tracker_external_id=tracker_task_id,
                    execute_task_id=task_context.execute_task.task.id
                    if task_context.execute_task is not None
                    else None,
                    link_count=len(links),
                )

                self.tracker.add_comment(
                    TrackerCommentCreatePayload(
                        external_task_id=tracker_task_id,
                        body=comment_body,
                        metadata={
                            "source": "heavy_lifting",
                            "task_id": task.id,
                            "flow_type": task.task_type.value,
                            "execute_task_id": task_context.execute_task.task.id
                            if task_context.execute_task is not None
                            else None,
                        },
                    )
                )
                estimate_metadata = _extract_estimate_metadata(execute_result=delivery_result)
                if estimate_metadata is not None:
                    self.tracker.update_task_estimate(
                        TrackerTaskEstimateUpdatePayload(
                            external_task_id=tracker_task_id,
                            story_points=estimate_metadata["story_points"],
                            can_take_in_work=estimate_metadata["can_take_in_work"],
                            rationale=estimate_metadata["rationale"],
                        )
                    )
                if links:
                    self.tracker.attach_links(
                        TrackerLinksAttachPayload(
                            external_task_id=tracker_task_id,
                            links=links,
                        )
                    )
                self.tracker.update_status(
                    TrackerStatusUpdatePayload(
                        external_task_id=tracker_task_id,
                        status=TaskStatus.DONE,
                    )
                )

                task.status = TaskStatus.DONE
                task.error = None
                task.branch_name = delivery_result.branch_name or task_context.branch_name
                task.pr_url = delivery_result.pr_url or task_context.pr_url
                task.result_payload = _dump_result_payload(
                    TaskResultPayload(
                        summary=f"Delivered result to tracker task {tracker_task_id}.",
                        details=comment_body,
                        branch_name=task.branch_name,
                        commit_sha=delivery_result.commit_sha,
                        pr_url=task.pr_url,
                        links=links,
                        metadata={
                            "tracker_external_id": tracker_task_id,
                            "tracker_status": TaskStatus.DONE.value,
                            "comment_posted": True,
                            "links_attached": len(links),
                        },
                    )
                )
                logger.info(
                    "delivery_completed",
                    tracker_external_id=tracker_task_id,
                    comment_posted=True,
                    link_count=len(links),
                )
                return DeliverWorkerReport(processed_deliver_tasks=1)
            except Exception as exc:
                logger.exception("task_failed", error=str(exc))
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                return DeliverWorkerReport(failed_deliver_tasks=1)

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

    def _resolve_tracker_task_id(self, *, task_context: EffectiveTaskContext) -> str:
        tracker_task_id = resolve_tracker_external_task_id(
            task=task_context.current_task.task,
            task_chain=[entry.task for entry in task_context.lineage],
        )
        if tracker_task_id is None:
            raise ValueError("deliver task requires a tracker external task id")
        return tracker_task_id

    def _build_comment_body(self, *, execute_result: TaskResultPayload) -> str:
        estimate_metadata = _extract_estimate_metadata(execute_result=execute_result)
        if estimate_metadata is not None:
            can_take_text = "да" if estimate_metadata["can_take_in_work"] else "нет"
            return (
                "Оценка задачи:\n"
                f"- Стоимость: {estimate_metadata['story_points']} SP\n"
                f"- Можно брать в работу сейчас: {can_take_text}\n"
                f"- Обоснование: {estimate_metadata['rationale']}"
            )
        if execute_result.tracker_comment:
            return execute_result.tracker_comment

        parts = [execute_result.summary]
        if execute_result.details:
            parts.append(execute_result.details)
        return "\n\n".join(parts)

    def _build_links(self, *, execute_result: TaskResultPayload) -> list[TaskLink]:
        links = [link.model_copy(deep=True) for link in execute_result.links]
        if execute_result.pr_url and not any(link.url == execute_result.pr_url for link in links):
            links.append(TaskLink(label="pull_request", url=execute_result.pr_url))
        return links

    def _resolve_delivery_result(
        self, *, task_context: EffectiveTaskContext
    ) -> TaskResultPayload | None:
        if (
            task_context.feedback_task is not None
            and task_context.feedback_task.task.task_type == TaskType.TRACKER_FEEDBACK
            and task_context.feedback_task.result_payload is not None
        ):
            return task_context.feedback_task.result_payload
        return task_context.execute_result


def build_deliver_worker(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> DeliverWorker:
    active_runtime = runtime or create_runtime_container()
    return DeliverWorker(
        tracker=active_runtime.tracker,
        session_factory=session_factory or get_session_factory(),
        poll_interval=active_runtime.settings.tracker_poll_interval,
    )


def run(
    *,
    once: bool = False,
    max_iterations: int | None = None,
) -> DeliverWorker:
    settings = get_settings()
    logger = configure_logging(app_name=settings.app_name, component="worker3")
    logger.info("worker_started", once=once, max_iterations=max_iterations)
    worker = build_deliver_worker()
    if once:
        worker.poll_once()
    else:
        worker.run_forever(max_iterations=max_iterations, sleep_fn=time.sleep)
    return worker


def _dump_result_payload(payload: TaskResultPayload) -> dict[str, object]:
    return payload.model_dump(mode="json")


def _task_logger(task: Task, **fields: Any):
    log_fields = {
        "task_id": task.id,
        "root_task_id": task.root_id or task.id,
        "parent_id": task.parent_id,
        "task_type": task.task_type.value,
        "task_status": task.status.value,
        "tracker_name": task.tracker_name,
        "tracker_external_id": task.external_task_id,
        "tracker_parent_external_id": task.external_parent_id,
        "workspace_key": task.workspace_key,
        "branch_name": task.branch_name,
        "pr_external_id": task.pr_external_id,
        "pr_url": task.pr_url,
    }
    log_fields.update(fields)
    return get_logger(__name__, component="worker3").bind(**log_fields)


def _extract_estimate_metadata(*, execute_result: TaskResultPayload) -> dict[str, Any] | None:
    estimate = execute_result.metadata.get("estimate")
    if not isinstance(estimate, dict):
        return None
    story_points = estimate.get("story_points")
    rationale = estimate.get("rationale")
    if not isinstance(story_points, int) or not isinstance(rationale, str) or not rationale.strip():
        return None
    return {
        "story_points": story_points,
        "can_take_in_work": story_points <= 2,
        "rationale": rationale.strip(),
    }


__all__ = [
    "DeliverWorker",
    "DeliverWorkerReport",
    "build_deliver_worker",
    "run",
]
