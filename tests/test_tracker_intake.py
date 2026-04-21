from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import (
    ScmBranchCreatePayload,
    ScmPullRequestCreatePayload,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmReadPrFeedbackQuery,
    ScmReadPrFeedbackResult,
    ScmWorkspaceEnsurePayload,
    TaskContext,
    TaskInputPayload,
    TrackerTaskCreatePayload,
)
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.workers.tracker_intake import TrackerIntakeWorker, build_tracker_intake_worker


class NonAscendingPaginatedScm(MockScm):
    def __init__(self, pages: list[ScmReadPrFeedbackResult]) -> None:
        super().__init__()
        self._pages = pages
        self.queries: list[ScmReadPrFeedbackQuery] = []

    def read_pr_feedback(self, query: ScmReadPrFeedbackQuery) -> ScmReadPrFeedbackResult:
        self.queries.append(query.model_copy(deep=True))
        if query.since_cursor == self._pages[-1].latest_cursor:
            return ScmReadPrFeedbackResult(latest_cursor=query.since_cursor)
        page_index = int(query.page_cursor) if query.page_cursor is not None else 0
        if page_index >= len(self._pages):
            return ScmReadPrFeedbackResult(latest_cursor=query.since_cursor)
        return self._pages[page_index].model_copy(deep=True)


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_tracker_intake_creates_fetch_and_execute_tasks(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Implement tracker intake",
                description="Create local fetch and execute tasks.",
                acceptance_criteria=["Local execute task is queued"],
            ),
            input_payload=TaskInputPayload(
                instructions="Implement Worker 1 flow.",
                base_branch="main",
                branch_name="task25/tracker-intake",
            ),
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-25",
        )
    )
    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    report = worker.poll_once()

    assert report.fetched_count == 1
    assert report.created_fetch_tasks == 1
    assert report.created_execute_tasks == 1
    assert report.skipped_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=created_task.external_id,
        )

        assert fetch_task is not None
        assert fetch_task.status is TaskStatus.DONE
        assert fetch_task.task_type is TaskType.FETCH
        assert fetch_task.external_task_id == created_task.external_id
        assert fetch_task.context == {
            "title": "Implement tracker intake",
            "description": "Create local fetch and execute tasks.",
            "acceptance_criteria": ["Local execute task is queued"],
            "references": [],
            "metadata": {},
        }

        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )

        assert execute_task is not None
        assert execute_task.status is TaskStatus.NEW
        assert execute_task.parent_id == fetch_task.id
        assert execute_task.root_id == fetch_task.root_id
        assert execute_task.external_parent_id == created_task.external_id
        assert execute_task.repo_url == "https://example.test/repo.git"
        assert execute_task.repo_ref == "main"
        assert execute_task.workspace_key == "repo-25"
        assert execute_task.context == fetch_task.context
        assert execute_task.input_payload == {
            "instructions": "Implement Worker 1 flow.",
            "base_branch": "main",
            "branch_name": "task25/tracker-intake",
            "commit_message_hint": None,
            "pr_feedback": None,
            "metadata": {},
        }


def test_tracker_intake_is_idempotent_for_repeated_polls(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Repeatable intake task"),
            input_payload=TaskInputPayload(instructions="Run once"),
        )
    )
    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    first_report = worker.poll_once()
    second_report = worker.poll_once()

    assert first_report.created_fetch_tasks == 1
    assert first_report.created_execute_tasks == 1
    assert second_report.fetched_count == 1
    assert second_report.created_fetch_tasks == 0
    assert second_report.created_execute_tasks == 0
    assert second_report.skipped_tasks == 1

    with session_scope(session_factory=session_factory) as session:
        tasks = session.query(Task).count()

    assert tasks == 2


def test_tracker_intake_restores_missing_execute_child(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    created_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Repair missing execute child"),
            input_payload=TaskInputPayload(instructions="Restore child"),
            repo_url="https://example.test/repo.git",
        )
    )
    with session_scope(session_factory=session_factory) as session:
        TaskRepository(session).create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_task_id=created_task.external_id,
                context={"title": "Repair missing execute child"},
            )
        )

    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
    )

    report = worker.poll_once()

    assert report.created_fetch_tasks == 0
    assert report.created_execute_tasks == 1
    assert report.skipped_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=created_task.external_id,
        )

        assert fetch_task is not None
        execute_task = repository.find_child_task(
            parent_id=fetch_task.id, task_type=TaskType.EXECUTE
        )
        assert execute_task is not None
        assert execute_task.external_parent_id == created_task.external_id
        assert execute_task.input_payload == {
            "instructions": "Restore child",
            "base_branch": None,
            "branch_name": None,
            "commit_message_hint": None,
            "pr_feedback": None,
            "metadata": {},
        }


def test_tracker_intake_creates_pr_feedback_children_for_scm_comments(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-26",
        )
    )
    scm.create_branch(
        ScmBranchCreatePayload(
            workspace_key="repo-26",
            branch_name="task26/pr-feedback",
        )
    )
    pull_request = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="repo-26",
            branch_name="task26/pr-feedback",
            base_branch="main",
            title="Task 26",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="tracker-task-26",
                tracker_name="mock",
                workspace_key="repo-26",
                repo_url="https://example.test/repo.git",
            ),
        )
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="tracker-task-26",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-26",
                context={"title": "Task 26 root"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="tracker-task-26",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-26",
                branch_name="task26/pr-feedback",
                pr_external_id=pull_request.external_id,
                pr_url=pull_request.url,
                context=fetch_task.context,
                input_payload={"instructions": "Implement task26"},
            )
        )

    first_feedback = scm.add_pr_feedback(
        pull_request.external_id,
        "Please add a dedupe regression test.",
        author="reviewer-1",
        path="tests/test_tracker_intake.py",
        line=1,
    )
    second_feedback = scm.add_pr_feedback(
        pull_request.external_id,
        "Please preserve the root task chain.",
        author="reviewer-2",
    )
    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )

    report = worker.poll_pr_feedback_once()

    assert report.fetched_feedback_items == 2
    assert report.created_pr_feedback_tasks == 2
    assert report.skipped_feedback_items == 0
    assert report.unmapped_feedback_items == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        first_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.PR_FEEDBACK,
            external_task_id=first_feedback.comment_id,
        )
        second_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.PR_FEEDBACK,
            external_task_id=second_feedback.comment_id,
        )

        assert first_task is not None
        assert second_task is not None
        assert first_task.parent_id == execute_task.id
        assert first_task.root_id == execute_task.root_id
        assert first_task.external_parent_id == pull_request.external_id
        assert first_task.pr_external_id == pull_request.external_id
        assert first_task.pr_url == pull_request.url
        assert first_task.branch_name == "task26/pr-feedback"
        assert first_task.input_payload["pr_feedback"] == {
            "pr_external_id": pull_request.external_id,
            "comment_id": first_feedback.comment_id,
            "body": "Please add a dedupe regression test.",
            "author": "reviewer-1",
            "path": "tests/test_tracker_intake.py",
            "line": 1,
            "side": None,
            "commit_sha": None,
            "pr_url": pull_request.url,
            "metadata": {},
        }
        assert second_task.parent_id == execute_task.id
        assert second_task.root_id == execute_task.root_id


def test_tracker_intake_deduplicates_pr_feedback_by_comment_id(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-26",
        )
    )
    scm.create_branch(
        ScmBranchCreatePayload(
            workspace_key="repo-26",
            branch_name="task26/pr-feedback",
        )
    )
    pull_request = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="repo-26",
            branch_name="task26/pr-feedback",
            base_branch="main",
            title="Task 26",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="tracker-task-26",
                workspace_key="repo-26",
                repo_url="https://example.test/repo.git",
            ),
        )
    )
    feedback_item = scm.add_pr_feedback(pull_request.external_id, "Existing review note.")

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="tracker-task-26",
                context={"title": "Task 26 root"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                pr_external_id=pull_request.external_id,
                branch_name="task26/pr-feedback",
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                external_task_id=feedback_item.comment_id,
                external_parent_id=pull_request.external_id,
                pr_external_id=pull_request.external_id,
                input_payload={
                    "pr_feedback": {
                        "pr_external_id": pull_request.external_id,
                        "comment_id": feedback_item.comment_id,
                        "body": "Existing review note.",
                    }
                },
            )
        )

        outcome = TrackerIntakeWorker(
            tracker=tracker,
            scm=scm,
            tracker_name="mock",
            session_factory=session_factory,
            poll_interval=1,
            pr_poll_interval=1,
        )._ingest_pr_feedback(
            repository=repository,
            feedback_item=feedback_item,
        )

        assert outcome.created_pr_feedback_task is False
        assert outcome.skipped_feedback_item is True
        assert outcome.unmapped_feedback_item is False


def test_tracker_intake_paginates_pr_feedback_without_relying_on_item_order(
    session_factory,
) -> None:
    tracker = MockTracker()
    pull_request_metadata = ScmPullRequestMetadata(
        execute_task_external_id="tracker-task-26",
        tracker_name="mock",
        workspace_key="repo-26",
        repo_url="https://example.test/repo.git",
    )
    feedback_items = [
        ScmPullRequestFeedback(
            pr_external_id="pr-26",
            comment_id=f"comment-{index}",
            body=f"Review note {index}",
            pr_url="https://example.test/repo/pull/26",
            pr_metadata=pull_request_metadata,
        )
        for index in range(1, 6)
    ]
    scm = NonAscendingPaginatedScm(
        pages=[
            ScmReadPrFeedbackResult(
                items=[feedback_items[4], feedback_items[3]],
                next_page_cursor="1",
                latest_cursor="comment-5",
            ),
            ScmReadPrFeedbackResult(
                items=[feedback_items[2], feedback_items[1]],
                next_page_cursor="2",
                latest_cursor="comment-5",
            ),
            ScmReadPrFeedbackResult(
                items=[feedback_items[0]],
                latest_cursor="comment-5",
            ),
        ]
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="tracker-task-26",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-26",
                context={"title": "Task 26 root", "metadata": {}},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="tracker-task-26",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-26",
                branch_name="task26/pr-feedback",
                pr_external_id="pr-26",
                pr_url="https://example.test/repo/pull/26",
                context={"title": "Task 26 root", "metadata": {}},
            )
        )

    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
        feedback_limit=2,
    )

    first_report = worker.poll_pr_feedback_once()
    second_report = worker.poll_pr_feedback_once()

    assert first_report.fetched_feedback_items == 5
    assert first_report.created_pr_feedback_tasks == 5
    assert first_report.skipped_feedback_items == 0
    assert second_report.fetched_feedback_items == 0
    assert second_report.created_pr_feedback_tasks == 0
    assert len(scm.queries) == 4
    assert scm.queries[0].since_cursor is None
    assert scm.queries[0].page_cursor is None
    assert scm.queries[1].since_cursor is None
    assert scm.queries[1].page_cursor == "1"
    assert scm.queries[2].since_cursor is None
    assert scm.queries[2].page_cursor == "2"
    assert scm.queries[3].since_cursor == "comment-5"

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        execute_task = session.get(Task, execute_task.id)
        assert execute_task is not None
        assert execute_task.context == {
            "title": "Task 26 root",
            "metadata": {"scm_pr_feedback_cursor": "comment-5"},
        }
        stored_feedback_ids = {
            task.external_task_id
            for task in session.query(Task)
            .filter(Task.parent_id == execute_task.id, Task.task_type == TaskType.PR_FEEDBACK)
            .all()
        }
        assert stored_feedback_ids == {
            "comment-1",
            "comment-2",
            "comment-3",
            "comment-4",
            "comment-5",
        }


def test_build_tracker_intake_worker_uses_runtime_settings(session_factory) -> None:
    runtime = RuntimeContainer(
        settings=replace(
            get_settings(),
            tracker_poll_interval=12,
            pr_poll_interval=7,
            tracker_adapter="mock",
        ),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=object(),
    )

    worker = build_tracker_intake_worker(runtime=runtime, session_factory=session_factory)

    assert worker.tracker is runtime.tracker
    assert worker.scm is runtime.scm
    assert worker.tracker_name == "mock"
    assert worker.poll_interval == 12
    assert worker.pr_poll_interval == 7
    assert worker.session_factory is session_factory
