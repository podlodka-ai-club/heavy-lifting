from __future__ import annotations

from dataclasses import dataclass

from backend.protocols.tracker import TrackerProtocol
from backend.schemas import (
    TrackerEstimatedSelectionQuery,
    TrackerFetchTasksQuery,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskReference,
    TrackerTaskSelectionClaimPayload,
)
from backend.task_constants import TaskStatus


@dataclass(frozen=True, slots=True)
class MockTaskSelectionResult:
    parent_task: TrackerTask
    created_task: TrackerTaskReference


@dataclass(slots=True)
class MockTaskSelectionService:
    tracker: TrackerProtocol
    fetch_limit: int = 100

    def select_small_estimated_task(
        self,
        *,
        max_story_points: int,
        candidate_statuses: tuple[TaskStatus, ...] = (TaskStatus.DONE,),
    ) -> MockTaskSelectionResult | None:
        candidate_tasks = self.tracker.fetch_tasks(
            TrackerFetchTasksQuery(
                statuses=list(candidate_statuses),
                estimated_selection=TrackerEstimatedSelectionQuery(
                    max_story_points=max_story_points,
                    can_take_in_work=True,
                    taken_in_work=False,
                    only_parent_tasks=True,
                ),
                limit=self.fetch_limit,
            )
        )
        selected_task = self._pick_candidate(candidate_tasks)
        if selected_task is None:
            return None

        created_task = self.tracker.create_subtask(
            TrackerSubtaskCreatePayload(
                parent_external_id=selected_task.external_id,
                context=selected_task.context.model_copy(deep=True),
                task_type=selected_task.task_type,
                status=TaskStatus.NEW,
                input_payload=(
                    selected_task.input_payload.model_copy(deep=True)
                    if selected_task.input_payload is not None
                    else None
                ),
                repo_url=selected_task.repo_url,
                repo_ref=selected_task.repo_ref,
                workspace_key=selected_task.workspace_key,
                metadata=_build_selected_subtask_metadata(selected_task),
            )
        )
        self.tracker.claim_task_selection(
            TrackerTaskSelectionClaimPayload(external_task_id=selected_task.external_id)
        )
        return MockTaskSelectionResult(parent_task=selected_task, created_task=created_task)

    def _pick_candidate(self, tasks: list[TrackerTask]) -> TrackerTask | None:
        if not tasks:
            return None
        return min(enumerate(tasks), key=_candidate_sort_key)[1]


def _candidate_sort_key(item: tuple[int, TrackerTask]) -> tuple[int, int]:
    index, task = item
    estimate = task.metadata.get("estimate")
    story_points = estimate.get("story_points") if isinstance(estimate, dict) else None
    if not isinstance(story_points, int):
        raise ValueError(
            "eligible estimated task must include integer metadata.estimate.story_points"
        )
    return story_points, index


def _build_selected_subtask_metadata(task: TrackerTask) -> dict[str, object]:
    metadata = dict(task.metadata)
    selection_value = metadata.get("selection")
    selection_metadata = dict(selection_value) if isinstance(selection_value, dict) else {}
    selection_metadata.update(
        {
            "selected_from_parent_external_id": task.external_id,
            "selected_from_parent_status": task.status.value,
        }
    )
    metadata["selection"] = selection_metadata
    return metadata


__all__ = ["MockTaskSelectionResult", "MockTaskSelectionService"]
