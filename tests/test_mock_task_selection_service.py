from __future__ import annotations

from backend.adapters.mock_tracker import MockTracker
from backend.schemas import TaskContext, TaskInputPayload, TrackerTaskCreatePayload
from backend.services.mock_task_selection import MockTaskSelectionService
from backend.task_constants import TaskStatus


def test_tracker_query_returns_only_eligible_estimated_tasks() -> None:
    tracker = MockTracker()
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Eligible small task"),
            input_payload=TaskInputPayload(instructions="Implement the small task."),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Too large"),
            input_payload=TaskInputPayload(instructions="Implement the large task."),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 8, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Do not take"),
            input_payload=TaskInputPayload(instructions="Skip this task."),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 1, "can_take_in_work": False},
                "selection": {"taken_in_work": False},
            },
        )
    )
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Already taken"),
            input_payload=TaskInputPayload(instructions="Skip duplicate selection."),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 1, "can_take_in_work": True},
                "selection": {"taken_in_work": True},
            },
        )
    )

    service = MockTaskSelectionService(tracker=tracker)

    result = service.select_small_estimated_task(max_story_points=3)

    assert result is not None
    assert result.parent_task.context.title == "Eligible small task"


def test_selecting_task_creates_single_executable_tracker_subtask() -> None:
    tracker = MockTracker()
    parent = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Implement selected task"),
            input_payload=TaskInputPayload(
                instructions="Implement the selected task.",
                base_branch="main",
                branch_name="task100/selected-task",
                commit_message_hint="task100 selected task",
            ),
            status=TaskStatus.DONE,
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-100",
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    service = MockTaskSelectionService(tracker=tracker)

    result = service.select_small_estimated_task(max_story_points=3)

    assert result is not None
    created_subtask = tracker._tasks[result.created_task.external_id]
    assert created_subtask.parent_external_id == parent.external_id
    assert created_subtask.status is TaskStatus.NEW
    assert created_subtask.context.title == "Implement selected task"
    assert created_subtask.input_payload is not None
    assert created_subtask.input_payload.instructions == "Implement the selected task."
    assert created_subtask.repo_url == "https://example.test/repo.git"
    assert created_subtask.repo_ref == "main"
    assert created_subtask.workspace_key == "repo-100"
    assert created_subtask.metadata["selection"] == {
        "taken_in_work": False,
        "selected_from_parent_external_id": parent.external_id,
        "selected_from_parent_status": "done",
    }
    assert tracker._tasks[parent.external_id].metadata["selection"]["taken_in_work"] is True


def test_repeated_selection_does_not_duplicate_same_parent_task() -> None:
    tracker = MockTracker()
    parent = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Take once"),
            input_payload=TaskInputPayload(instructions="Implement exactly once."),
            status=TaskStatus.DONE,
            metadata={
                "estimate": {"story_points": 1, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
            },
        )
    )
    service = MockTaskSelectionService(tracker=tracker)

    first_result = service.select_small_estimated_task(max_story_points=3)
    second_result = service.select_small_estimated_task(max_story_points=3)

    assert first_result is not None
    assert second_result is None
    assert tracker._tasks[parent.external_id].metadata["selection"]["taken_in_work"] is True
    child_tasks = [
        task for task in tracker._tasks.values() if task.parent_external_id == parent.external_id
    ]
    assert [task.external_id for task in child_tasks] == [first_result.created_task.external_id]
