from backend.adapters.mock_tracker import MockTracker
from backend.protocols.tracker import TrackerProtocol
from backend.schemas import (
    TaskContext,
    TrackerCommentCreatePayload,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTaskCreatePayload,
)
from backend.task_constants import TaskStatus, TaskType


def test_mock_tracker_matches_tracker_protocol_at_runtime() -> None:
    tracker = MockTracker()

    assert isinstance(tracker, TrackerProtocol)


def test_mock_tracker_supports_mvp_tracker_operations() -> None:
    tracker = MockTracker()

    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Root task"),
            task_type=TaskType.FETCH,
        )
    )
    created_subtask = tracker.create_subtask(
        TrackerSubtaskCreatePayload(
            parent_external_id=created_task.external_id,
            context=TaskContext(title="Child task"),
            task_type=TaskType.EXECUTE,
            repo_url="https://example.test/repo.git",
        )
    )
    comment = tracker.add_comment(
        TrackerCommentCreatePayload(
            external_task_id=created_subtask.external_id,
            body="Execution completed",
        )
    )
    updated = tracker.update_status(
        TrackerStatusUpdatePayload(
            external_task_id=created_subtask.external_id,
            status=TaskStatus.DONE,
        )
    )
    linked = tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id=created_subtask.external_id,
            links=[{"label": "PR", "url": "https://example.test/pr/17"}],
        )
    )
    tasks = tracker.fetch_tasks(
        TrackerFetchTasksQuery(statuses=[TaskStatus.NEW, TaskStatus.DONE], limit=10)
    )

    assert created_task.external_id == "task-1"
    assert created_subtask.external_id == "task-2"
    assert comment.comment_id == "comment-1"
    assert updated.external_id == created_subtask.external_id
    assert linked.external_id == created_subtask.external_id
    assert [task.external_id for task in tasks] == ["task-1", "task-2"]
    assert tasks[1].parent_external_id == created_task.external_id
    assert tasks[1].status is TaskStatus.DONE
    assert tasks[1].context.references[0].label == "PR"


def test_mock_tracker_isolates_state_from_payload_mutation_after_create() -> None:
    tracker = MockTracker()
    payload = TrackerTaskCreatePayload(
        context=TaskContext(
            title="Original title",
            references=[{"label": "spec", "url": "https://example.test/spec"}],
            metadata={"priority": "high"},
        ),
        metadata={"source": "tracker"},
    )

    created_task = tracker.create_task(payload)
    payload.context.title = "Mutated title"
    payload.context.references[0].label = "changed"
    payload.context.metadata["priority"] = "low"
    payload.metadata["source"] = "mutated"

    stored_task = tracker.fetch_tasks(TrackerFetchTasksQuery())[0]

    assert created_task.external_id == stored_task.external_id
    assert stored_task.context.title == "Original title"
    assert stored_task.context.references[0].label == "spec"
    assert stored_task.context.metadata == {"priority": "high"}
    assert stored_task.metadata == {"source": "tracker"}


def test_mock_tracker_isolates_state_from_fetched_task_mutation() -> None:
    tracker = MockTracker()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Stored title"),
        )
    )

    fetched_task = tracker.fetch_tasks(TrackerFetchTasksQuery())[0]
    fetched_task.context.title = "Externally mutated"
    fetched_task.metadata["new"] = "value"

    fetched_again = tracker.fetch_tasks(TrackerFetchTasksQuery())[0]

    assert created_task.external_id == fetched_again.external_id
    assert fetched_again.context.title == "Stored title"
    assert fetched_again.metadata == {}


def test_mock_tracker_filters_fetch_results_by_status_type_and_limit() -> None:
    tracker = MockTracker()
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Fetch task"),
            task_type=TaskType.FETCH,
        )
    )
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Done execute"),
            task_type=TaskType.EXECUTE,
            status=TaskStatus.DONE,
        )
    )
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="New execute"),
            task_type=TaskType.EXECUTE,
        )
    )

    tasks = tracker.fetch_tasks(
        TrackerFetchTasksQuery(
            statuses=[TaskStatus.NEW, TaskStatus.DONE],
            task_type=TaskType.EXECUTE,
            limit=1,
        )
    )

    assert len(tasks) == 1
    assert tasks[0].task_type is TaskType.EXECUTE
    assert tasks[0].status is TaskStatus.DONE


def test_mock_tracker_attach_links_copies_payload_before_storing() -> None:
    tracker = MockTracker()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="Task with links"))
    )
    payload = TrackerLinksAttachPayload(
        external_task_id=created_task.external_id,
        links=[{"label": "PR", "url": "https://example.test/pr/32"}],
    )

    tracker.attach_links(payload)
    payload.links[0].label = "mutated"

    stored_task = tracker.fetch_tasks(TrackerFetchTasksQuery())[0]

    assert stored_task.context.references[0].label == "PR"
