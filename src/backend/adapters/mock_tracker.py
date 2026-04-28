from __future__ import annotations

from backend.schemas import (
    TrackerCommentCreatePayload,
    TrackerCommentReference,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskCreatePayload,
    TrackerTaskReference,
)
from backend.tracker_metadata import get_nested_mapping, matches_estimated_selection


class MockTracker:
    def __init__(self) -> None:
        self._tasks: dict[str, TrackerTask] = {}
        self._comments: dict[str, list[TrackerCommentCreatePayload]] = {}
        self._task_sequence = 0
        self._comment_sequence = 0

    def fetch_tasks(self, query: TrackerFetchTasksQuery) -> list[TrackerTask]:
        tasks = [
            task
            for task in self._tasks.values()
            if task.status in query.statuses
            and (query.task_type is None or task.task_type == query.task_type)
            and matches_estimated_selection(task=task, selection=query.estimated_selection)
        ]
        return [task.model_copy(deep=True) for task in tasks[: query.limit]]

    def create_task(self, payload: TrackerTaskCreatePayload) -> TrackerTaskReference:
        external_id = self._next_task_id()
        stored_payload = payload.model_copy(deep=True)
        self._tasks[external_id] = TrackerTask(
            external_id=external_id,
            status=stored_payload.status,
            task_type=stored_payload.task_type,
            context=stored_payload.context,
            input_payload=stored_payload.input_payload,
            repo_url=stored_payload.repo_url,
            repo_ref=stored_payload.repo_ref,
            workspace_key=stored_payload.workspace_key,
            metadata=stored_payload.metadata,
        )
        return TrackerTaskReference(external_id=external_id)

    def create_subtask(self, payload: TrackerSubtaskCreatePayload) -> TrackerTaskReference:
        external_id = self._next_task_id()
        stored_payload = payload.model_copy(deep=True)
        self._tasks[external_id] = TrackerTask(
            external_id=external_id,
            parent_external_id=stored_payload.parent_external_id,
            status=stored_payload.status,
            task_type=stored_payload.task_type,
            context=stored_payload.context,
            input_payload=stored_payload.input_payload,
            repo_url=stored_payload.repo_url,
            repo_ref=stored_payload.repo_ref,
            workspace_key=stored_payload.workspace_key,
            metadata=stored_payload.metadata,
        )
        self._mark_parent_taken_in_work(parent_external_id=stored_payload.parent_external_id)
        return TrackerTaskReference(external_id=external_id)

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference:
        self._comment_sequence += 1
        stored_payload = payload.model_copy(deep=True)
        self._comments.setdefault(stored_payload.external_task_id, []).append(stored_payload)
        return TrackerCommentReference(comment_id=f"comment-{self._comment_sequence}")

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        task.status = payload.status
        return TrackerTaskReference(external_id=task.external_id)

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        task.context.references.extend(link.model_copy(deep=True) for link in payload.links)
        return TrackerTaskReference(external_id=task.external_id)

    def _next_task_id(self) -> str:
        self._task_sequence += 1
        return f"task-{self._task_sequence}"

    def _mark_parent_taken_in_work(self, *, parent_external_id: str) -> None:
        parent_task = self._tasks.get(parent_external_id)
        if parent_task is None:
            return
        estimate_metadata = get_nested_mapping(parent_task.metadata, "estimate")
        if "story_points" not in estimate_metadata or "can_take_in_work" not in estimate_metadata:
            return
        metadata = dict(parent_task.metadata)
        selection_metadata = dict(get_nested_mapping(metadata, "selection"))
        selection_metadata["taken_in_work"] = True
        metadata["selection"] = selection_metadata
        parent_task.metadata = metadata
