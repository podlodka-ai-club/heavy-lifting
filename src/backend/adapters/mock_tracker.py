from __future__ import annotations

from backend.schemas import (
    TrackerCommentCreatePayload,
    TrackerCommentPayload,
    TrackerCommentReference,
    TrackerEstimateUpdatePayload,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerReadCommentsQuery,
    TrackerReadCommentsResult,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskCreatePayload,
    TrackerTaskEstimateUpdatePayload,
    TrackerTaskReference,
    TrackerTaskSelectionClaimPayload,
)
from backend.tracker_metadata import get_nested_mapping, matches_estimated_selection


class MockTracker:
    def __init__(self) -> None:
        self._tasks: dict[str, TrackerTask] = {}
        self._comments: dict[str, list[TrackerCommentPayload]] = {}
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
        return TrackerTaskReference(external_id=external_id)

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference:
        comment_id = self._next_comment_id()
        stored_payload = payload.model_copy(deep=True)
        self._comments.setdefault(stored_payload.external_task_id, []).append(
            TrackerCommentPayload(
                external_task_id=stored_payload.external_task_id,
                comment_id=comment_id,
                body=stored_payload.body,
                author="heavy-lifting",
                url=f"mock://tracker/{stored_payload.external_task_id}/comments/{comment_id}",
                metadata=stored_payload.metadata,
            )
        )
        return TrackerCommentReference(comment_id=comment_id)

    def read_comments(self, query: TrackerReadCommentsQuery) -> TrackerReadCommentsResult:
        comments = self._comments.get(query.external_task_id, [])
        start_index = 0
        if query.since_cursor is not None:
            for index, comment in enumerate(comments):
                if comment.comment_id == query.since_cursor:
                    start_index = index + 1
                    break
        if query.page_cursor is not None:
            start_index = max(start_index, int(query.page_cursor))
        page_items = comments[start_index : start_index + query.limit]
        next_index = start_index + len(page_items)
        next_page_cursor = str(next_index) if next_index < len(comments) else None
        latest_cursor = comments[-1].comment_id if comments else query.since_cursor
        return TrackerReadCommentsResult(
            items=[comment.model_copy(deep=True) for comment in page_items],
            next_page_cursor=next_page_cursor,
            latest_cursor=latest_cursor,
        )

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        task.status = payload.status
        return TrackerTaskReference(external_id=task.external_id)

    def update_estimate(
        self, payload: TrackerEstimateUpdatePayload
    ) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        metadata = dict(task.metadata)

        if payload.story_points is not None:
            estimate_metadata = dict(get_nested_mapping(metadata, "estimate"))
            estimate_metadata["story_points"] = payload.story_points
            metadata["estimate"] = estimate_metadata

        existing_labels_raw = metadata.get("labels")
        if isinstance(existing_labels_raw, list):
            current_labels = [label for label in existing_labels_raw if isinstance(label, str)]
        else:
            current_labels = []

        remove_set = set(payload.labels_to_remove)
        next_labels = [label for label in current_labels if label not in remove_set]
        for label in payload.labels_to_add:
            if label not in next_labels:
                next_labels.append(label)
        metadata["labels"] = next_labels

        task.metadata = metadata
        return TrackerTaskReference(external_id=task.external_id)

    def claim_task_selection(
        self, payload: TrackerTaskSelectionClaimPayload
    ) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        metadata = dict(task.metadata)
        selection_metadata = dict(get_nested_mapping(metadata, "selection"))
        selection_metadata["taken_in_work"] = True
        metadata["selection"] = selection_metadata
        task.metadata = metadata
        return TrackerTaskReference(external_id=task.external_id)

    def update_task_estimate(
        self, payload: TrackerTaskEstimateUpdatePayload
    ) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        metadata = dict(task.metadata)
        metadata["estimate"] = {
            "story_points": payload.story_points,
            "can_take_in_work": payload.can_take_in_work,
            "rationale": payload.rationale,
        }
        task.metadata = metadata
        return TrackerTaskReference(external_id=task.external_id)

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference:
        task = self._tasks[payload.external_task_id]
        own_write_links = [
            link.model_copy(deep=True, update={"origin": "own_write"})
            for link in payload.links
        ]
        task.context.references.extend(own_write_links)
        return TrackerTaskReference(external_id=task.external_id)

    def _next_task_id(self) -> str:
        self._task_sequence += 1
        return f"task-{self._task_sequence}"

    def _next_comment_id(self) -> str:
        self._comment_sequence += 1
        return f"comment-{self._comment_sequence}"
