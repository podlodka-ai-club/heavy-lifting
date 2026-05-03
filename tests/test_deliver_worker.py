from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import (
    TaskContext,
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
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.workers.deliver_worker import DeliverWorker, build_deliver_worker


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_deliver_worker_posts_comment_updates_status_and_attaches_pr_link(session_factory) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        _tracker_task_payload(title="Tracker task", repo_url="https://example.test/repo.git")
    )
    worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-28",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-28",
                branch_name="task28/delivery-flow",
                pr_external_id="pr-28",
                pr_url="https://example.test/repo/pull/28",
                context={"title": "Implement Worker 3"},
                result_payload={
                    "summary": "Worker 3 delivery flow implemented.",
                    "details": "Added delivery worker orchestration and tracker sync.",
                    "branch_name": "task28/delivery-flow",
                    "commit_sha": "mock-commit-0028",
                    "pr_url": "https://example.test/repo/pull/28",
                    "tracker_comment": "Готово: результат доставлен обратно в tracker.",
                    "links": [
                        {
                            "label": "branch",
                            "url": "https://example.test/repo/tree/task28/delivery-flow",
                        }
                    ],
                    "metadata": {"flow_type": "execute"},
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                branch_name=execute_task.branch_name,
                pr_external_id=execute_task.pr_external_id,
                pr_url=execute_task.pr_url,
                context={"title": "Deliver Worker 3 result"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert report.failed_deliver_tasks == 0
    assert len(tracker._comments[tracker_task.external_id]) == 1
    assert tracker._comments[tracker_task.external_id][0].body == (
        "Готово: результат доставлен обратно в tracker."
    )
    assert tracker._tasks[tracker_task.external_id].status == TaskStatus.DONE
    assert [
        reference.url for reference in tracker._tasks[tracker_task.external_id].context.references
    ] == [
        "https://example.test/repo/tree/task28/delivery-flow",
        "https://example.test/repo/pull/28",
    ]

    with session_scope(session_factory=session_factory) as session:
        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.status == TaskStatus.DONE
        assert deliver_task.error is None
        assert deliver_task.result_payload is not None
        assert (
            deliver_task.result_payload["metadata"]["tracker_external_id"]
            == tracker_task.external_id
        )
        assert deliver_task.result_payload["metadata"]["links_attached"] == 2


def test_deliver_worker_marks_task_failed_when_execute_result_is_missing(session_factory) -> None:
    worker = DeliverWorker(tracker=MockTracker(), session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-28",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id="TASK-28",
                context={"title": "Execute task without result"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id="TASK-28",
                context={"title": "Deliver missing result"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 0
    assert report.failed_deliver_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.status == TaskStatus.FAILED
        assert deliver_task.error == "deliver task requires a completed execute result"


def test_deliver_worker_normalizes_estimate_comment_and_persists_estimate_metadata(
    session_factory,
) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Estimate task"),
            status=TaskStatus.NEW,
            metadata={"selection": {"taken_in_work": False}},
        )
    )
    worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Estimate task"},
                result_payload={
                    "summary": "Estimate completed.",
                    "tracker_comment": "2 story points\nReason: small isolated change.",
                    "metadata": {
                        "delivery_mode": "estimate_only",
                        "estimate": {
                            "story_points": 2,
                            "can_take_in_work": True,
                            "rationale": "small isolated change.",
                        },
                    },
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Deliver estimate"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    comment = tracker._comments[tracker_task.external_id][0].body
    assert "Стоимость: 2 SP" in comment
    assert "Можно брать в работу сейчас: да" in comment
    assert "Обоснование: small isolated change." in comment
    assert tracker._tasks[tracker_task.external_id].metadata["estimate"] == {
        "story_points": 2,
        "can_take_in_work": True,
        "rationale": "small isolated change.",
    }
    assert tracker._tasks[tracker_task.external_id].metadata["selection"] == {
        "taken_in_work": False
    }


def test_deliver_worker_marks_three_plus_sp_as_not_takeable_now(session_factory) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="Estimate task"), status=TaskStatus.NEW)
    )
    worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Estimate task"},
                result_payload={
                    "summary": "Estimate completed.",
                    "metadata": {
                        "estimate": {
                            "story_points": 3,
                            "can_take_in_work": False,
                            "rationale": "requires broader refactoring.",
                        }
                    },
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Deliver estimate"},
            )
        )

    worker.poll_once()

    comment = tracker._comments[tracker_task.external_id][0].body
    assert "Стоимость: 3 SP" in comment
    assert "Можно брать в работу сейчас: нет" in comment


def test_build_deliver_worker_uses_runtime_settings(session_factory) -> None:
    runtime = _runtime_with_tracker_poll_interval(poll_interval=17)

    worker = build_deliver_worker(runtime=runtime, session_factory=session_factory)

    assert worker.tracker is runtime.tracker
    assert worker.poll_interval == 17
    assert worker.session_factory is session_factory


class DbWriteDuringTrackerCall(MockTracker):
    def __init__(self, session_factory, target_task_id: int) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.target_task_id = target_task_id
        self.write_attempted = False

    def add_comment(self, payload):
        self.write_attempted = True
        with session_scope(session_factory=self.session_factory) as session:
            target_task = session.get(Task, self.target_task_id)
            assert target_task is not None
            target_task.error = "updated-during-tracker-call"
        return super().add_comment(payload)


def test_deliver_worker_commits_claim_before_tracker_calls(session_factory) -> None:
    tracker = DbWriteDuringTrackerCall(session_factory=session_factory, target_task_id=1)
    tracker_task = tracker.create_task(
        _tracker_task_payload(title="Tracker task", repo_url="https://example.test/repo.git")
    )
    worker = DeliverWorker(tracker=tracker, session_factory=session_factory)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-claim-deliver",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-claim-deliver",
                branch_name="task-claim-deliver/run",
                context={"title": "Implement Worker 3"},
                result_payload={
                    "summary": "done",
                    "details": "details",
                },
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Deliver Worker 3 result"},
            )
        )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert tracker.write_attempted is True
    with session_scope(session_factory=session_factory) as session:
        fetch_task = session.get(Task, 1)
        assert fetch_task is not None
        assert fetch_task.error == "updated-during-tracker-call"


def _tracker_task_payload(*, title: str, repo_url: str):
    return TrackerTaskCreatePayload(
        context=TaskContext(title=title),
        repo_url=repo_url,
        repo_ref="main",
        workspace_key="repo-28",
    )


def _runtime_with_tracker_poll_interval(*, poll_interval: int):
    return RuntimeContainer(
        settings=replace(get_settings(), tracker_poll_interval=poll_interval),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )


@dataclass
class _TrackerSpy:
    update_status_calls: list[TrackerStatusUpdatePayload] = field(default_factory=list)
    update_estimate_calls: list[TrackerEstimateUpdatePayload] = field(default_factory=list)
    add_comment_calls: list[TrackerCommentCreatePayload] = field(default_factory=list)
    attach_links_calls: list[TrackerLinksAttachPayload] = field(default_factory=list)

    def fetch_tasks(self, query: TrackerFetchTasksQuery) -> list[TrackerTask]:
        raise NotImplementedError

    def create_task(self, payload: TrackerTaskCreatePayload) -> TrackerTaskReference:
        raise NotImplementedError

    def create_subtask(self, payload: TrackerSubtaskCreatePayload) -> TrackerTaskReference:
        raise NotImplementedError

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference:
        self.add_comment_calls.append(payload)
        return TrackerCommentReference(comment_id=f"comment-{len(self.add_comment_calls)}")

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference:
        self.update_status_calls.append(payload)
        return TrackerTaskReference(external_id=payload.external_task_id)

    def update_estimate(self, payload: TrackerEstimateUpdatePayload) -> TrackerTaskReference:
        self.update_estimate_calls.append(payload)
        return TrackerTaskReference(external_id=payload.external_task_id)

    def claim_task_selection(
        self, payload: TrackerTaskSelectionClaimPayload
    ) -> TrackerTaskReference:
        raise NotImplementedError

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference:
        self.attach_links_calls.append(payload)
        return TrackerTaskReference(external_id=payload.external_task_id)


def _seed_triage_chain(
    *,
    session_factory,
    delivery_payload: dict | None,
    external_task_id: str = "TRACK-77",
) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=external_task_id,
                context={"title": "Triage candidate"},
            )
        )
        result_payload: dict[str, object] = {
            "summary": "Triage completed.",
            "details": "Triage details (fallback).",
        }
        if delivery_payload is not None:
            result_payload["delivery"] = delivery_payload
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_parent_id=external_task_id,
                context={"title": "Triage execute"},
                result_payload=result_payload,
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                tracker_name="mock",
                external_parent_id=external_task_id,
                context={"title": "Deliver triage"},
            )
        )


def test_deliver_with_delivery_payload_does_not_call_update_status_when_tracker_status_is_none(
    session_factory,
) -> None:
    spy = _TrackerSpy()
    worker = DeliverWorker(tracker=spy, session_factory=session_factory)
    _seed_triage_chain(
        session_factory=session_factory,
        delivery_payload={
            "tracker_status": None,
            "tracker_estimate": 2,
            "tracker_labels": ["sp:2", "triage:ready"],
            "comment_body": "## Agent Handover Brief\nbody",
        },
    )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert report.failed_deliver_tasks == 0
    assert spy.update_status_calls == []
    assert len(spy.update_estimate_calls) == 1
    estimate_call = spy.update_estimate_calls[0]
    assert estimate_call.story_points == 2
    assert estimate_call.labels_to_add == ["sp:2", "triage:ready"]
    assert estimate_call.labels_to_remove == []
    assert len(spy.add_comment_calls) == 1
    assert spy.add_comment_calls[0].body == "## Agent Handover Brief\nbody"


def test_deliver_with_delivery_payload_uses_comment_body_verbatim(session_factory) -> None:
    spy = _TrackerSpy()
    worker = DeliverWorker(tracker=spy, session_factory=session_factory)
    _seed_triage_chain(
        session_factory=session_factory,
        delivery_payload={
            "tracker_status": None,
            "tracker_estimate": 5,
            "tracker_labels": ["sp:5", "triage:rfi"],
            "comment_body": "## RFI\nNeed clarification on AC #3",
            "escalation_kind": "rfi",
        },
    )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert len(spy.add_comment_calls) == 1
    assert spy.add_comment_calls[0].body == "## RFI\nNeed clarification on AC #3"
    # Triage summary fallback should NOT be used when comment_body is set.
    assert "Triage completed." not in spy.add_comment_calls[0].body


def test_deliver_with_delivery_payload_calls_update_status_when_tracker_status_set(
    session_factory,
) -> None:
    spy = _TrackerSpy()
    worker = DeliverWorker(tracker=spy, session_factory=session_factory)
    _seed_triage_chain(
        session_factory=session_factory,
        delivery_payload={
            "tracker_status": TaskStatus.FAILED.value,
            "tracker_estimate": None,
            "tracker_labels": [],
            "comment_body": "Implementation failed",
        },
    )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert len(spy.update_status_calls) == 1
    assert spy.update_status_calls[0].status == TaskStatus.FAILED
    # No estimate-update because tracker_estimate is None and labels list is empty.
    assert spy.update_estimate_calls == []


def test_deliver_legacy_without_delivery_payload_keeps_update_status_done(
    session_factory,
) -> None:
    spy = _TrackerSpy()
    worker = DeliverWorker(tracker=spy, session_factory=session_factory)
    _seed_triage_chain(session_factory=session_factory, delivery_payload=None)

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    assert len(spy.update_status_calls) == 1
    assert spy.update_status_calls[0].status == TaskStatus.DONE
    assert spy.update_estimate_calls == []


def test_deliver_with_delivery_escalation_kind_records_in_result_metadata(
    session_factory,
) -> None:
    spy = _TrackerSpy()
    worker = DeliverWorker(tracker=spy, session_factory=session_factory)
    _seed_triage_chain(
        session_factory=session_factory,
        delivery_payload={
            "tracker_status": None,
            "tracker_estimate": 5,
            "tracker_labels": ["sp:5", "triage:rfi"],
            "comment_body": "## RFI\nDetails",
            "escalation_kind": "rfi",
        },
    )

    report = worker.poll_once()

    assert report.processed_deliver_tasks == 1
    with session_scope(session_factory=session_factory) as session:
        deliver_task = session.get(Task, 3)
        assert deliver_task is not None
        assert deliver_task.result_payload is not None
        metadata = deliver_task.result_payload["metadata"]
        assert metadata["escalation_kind"] == "rfi"
        assert metadata["tracker_estimate"] == 5
        assert metadata["tracker_labels"] == ["sp:5", "triage:rfi"]
        assert metadata["tracker_status"] is None
