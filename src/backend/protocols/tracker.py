from typing import Protocol, runtime_checkable

from backend.schemas import (
    TrackerCommentCreatePayload,
    TrackerCommentReference,
    TrackerEstimateUpdatePayload,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskCreatePayload,
    TrackerTaskReference,
    TrackerTaskSelectionClaimPayload,
)


@runtime_checkable
class TrackerProtocol(Protocol):
    def fetch_tasks(self, query: TrackerFetchTasksQuery) -> list[TrackerTask]: ...

    def create_task(self, payload: TrackerTaskCreatePayload) -> TrackerTaskReference: ...

    def create_subtask(self, payload: TrackerSubtaskCreatePayload) -> TrackerTaskReference: ...

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference: ...

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference: ...

    def update_estimate(
        self, payload: TrackerEstimateUpdatePayload
    ) -> TrackerTaskReference: ...

    def claim_task_selection(
        self, payload: TrackerTaskSelectionClaimPayload
    ) -> TrackerTaskReference: ...

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference: ...
