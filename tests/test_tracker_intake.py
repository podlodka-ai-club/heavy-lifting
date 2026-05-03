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
    TrackerCommentCreatePayload,
    TrackerSubtaskCreatePayload,
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


class FailingTracker(MockTracker):
    def fetch_tasks(self, query):
        raise RuntimeError("tracker fetch failed")


class FailingScm(MockScm):
    def read_pr_feedback(self, query):
        raise RuntimeError("scm feedback fetch failed")


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
            "tracker_feedback": None,
            "metadata": {"estimate_only": True},
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
            "tracker_feedback": None,
            "metadata": {"estimate_only": True},
        }


def test_tracker_intake_does_not_force_estimate_only_for_tracker_subtasks(session_factory) -> None:
    tracker = MockTracker()
    scm = MockScm()
    parent = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(title="Estimated parent"),
            input_payload=TaskInputPayload(instructions="Parent task"),
        )
    )
    child = tracker.create_subtask(
        TrackerSubtaskCreatePayload(
            context=TaskContext(title="Selected child task"),
            input_payload=TaskInputPayload(
                instructions="Implement selected child task.",
                base_branch="main",
                branch_name="task120/selected-from-estimate",
            ),
            parent_external_id=parent.external_id,
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

    assert report.created_execute_tasks == 2

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        child_fetch = repository.find_fetch_task_by_tracker_task(
            tracker_name="mock",
            external_task_id=child.external_id,
        )
        assert child_fetch is not None
        child_execute = repository.find_child_task(
            parent_id=child_fetch.id, task_type=TaskType.EXECUTE
        )
        assert child_execute is not None
        assert child_execute.input_payload is not None
        assert child_execute.input_payload["metadata"] == {}


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
            "url": None,
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


def test_tracker_intake_query_includes_repo_context_for_execute_task(session_factory) -> None:
    tracker = MockTracker()
    pull_request_metadata = ScmPullRequestMetadata(
        execute_task_external_id="tracker-task-99",
        tracker_name="mock",
        workspace_key="repo-99",
        repo_url="https://example.test/repo.git",
    )
    scm = NonAscendingPaginatedScm(
        pages=[
            ScmReadPrFeedbackResult(
                items=[
                    ScmPullRequestFeedback(
                        pr_external_id="pr-99",
                        comment_id="comment-1",
                        body="hi",
                        pr_url="https://example.test/repo/pull/99",
                        pr_metadata=pull_request_metadata,
                    )
                ],
                latest_cursor="comment-1",
            ),
        ]
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="tracker-task-99",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-99",
                context={"title": "root"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="tracker-task-99",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-99",
                branch_name="task99/branch",
                pr_external_id="pr-99",
                pr_url="https://example.test/repo/pull/99",
                context={"title": "root", "metadata": {}},
            )
        )

    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        poll_interval=1,
        pr_poll_interval=1,
    )
    worker.poll_pr_feedback_once()

    assert len(scm.queries) >= 1
    first_query = scm.queries[0]
    assert first_query.repo_url == "https://example.test/repo.git"
    assert first_query.workspace_key == "repo-99"
    assert first_query.branch_name == "task99/branch"


def test_maybe_enrich_pr_metadata_rebuilds_sentinel_from_execute_task(
    session_factory,
) -> None:
    sentinel_metadata = ScmPullRequestMetadata(
        execute_task_external_id="",
        workspace_key=None,
        repo_url=None,
        metadata={"_hl_unresolved": True},
    )
    feedback_item = ScmPullRequestFeedback(
        pr_external_id="pr-77",
        comment_id="issue-1",
        body="please fix",
        pr_url="https://example.test/repo/pull/77",
        pr_metadata=sentinel_metadata,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="linear",
                external_task_id="LIN-77",
                repo_url="https://github.com/acme/widgets",
                repo_ref="main",
                workspace_key="repo-77",
                context={"title": "root"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="linear",
                external_task_id="LIN-77",
                external_parent_id="LIN-77",
                repo_url="https://github.com/acme/widgets",
                repo_ref="main",
                workspace_key="repo-77",
                branch_name="task77/run",
                pr_external_id="pr-77",
                pr_url="https://example.test/repo/pull/77",
                context={"title": "root", "metadata": {}},
            )
        )

        worker = TrackerIntakeWorker(
            tracker=MockTracker(),
            scm=MockScm(),
            tracker_name="linear",
            session_factory=session_factory,
            poll_interval=1,
            pr_poll_interval=1,
        )
        enriched = worker._maybe_enrich_pr_metadata(
            feedback_item=feedback_item, execute_task=execute_task
        )

    assert enriched.pr_metadata.execute_task_external_id == "LIN-77"
    assert enriched.pr_metadata.repo_url == "https://github.com/acme/widgets"
    assert enriched.pr_metadata.workspace_key == "repo-77"
    assert enriched.pr_metadata.tracker_name == "linear"
    assert enriched.pr_metadata.metadata == {}
    # Original feedback_item must remain untouched.
    assert feedback_item.pr_metadata.metadata == {"_hl_unresolved": True}


def test_maybe_enrich_pr_metadata_passes_through_resolved_metadata(
    session_factory,
) -> None:
    valid_metadata = ScmPullRequestMetadata(
        execute_task_external_id="EXTERNAL-ABC",
        tracker_name="github",
        workspace_key="repo-abc",
        repo_url="https://github.com/acme/widgets",
    )
    feedback_item = ScmPullRequestFeedback(
        pr_external_id="pr-78",
        comment_id="issue-2",
        body="ok",
        pr_url="https://example.test/repo/pull/78",
        pr_metadata=valid_metadata,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                tracker_name="linear",
                external_task_id="LIN-78",
                repo_url="https://github.com/acme/widgets",
                repo_ref="main",
                workspace_key="repo-78",
            )
        )
        worker = TrackerIntakeWorker(
            tracker=MockTracker(),
            scm=MockScm(),
            tracker_name="linear",
            session_factory=session_factory,
            poll_interval=1,
            pr_poll_interval=1,
        )
        result = worker._maybe_enrich_pr_metadata(
            feedback_item=feedback_item, execute_task=execute_task
        )

    assert result is feedback_item
    assert result.pr_metadata.execute_task_external_id == "EXTERNAL-ABC"
    assert result.pr_metadata.tracker_name == "github"


def test_tracker_intake_creates_tracker_feedback_child_for_estimate_only_comments(
    session_factory,
) -> None:
    tracker = MockTracker()
    scm = MockScm()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Estimate task",
                description="Estimate only. Do not modify code.",
            )
        )
    )
    tracker.add_comment(
        TrackerCommentCreatePayload(
            external_task_id=tracker_task.external_id,
            body="Please explain why this is 2 points.",
            metadata={"source": "operator"},
        )
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
                context={"title": "Estimate task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={
                    "title": "Estimate task",
                    "description": "Need only an estimate without code changes.",
                },
                input_payload={
                    "instructions": "Estimate only. Do not modify code.",
                    "branch_name": "task62/estimate-only",
                },
            )
        )

    worker = TrackerIntakeWorker(
        tracker=tracker,
        scm=scm,
        tracker_name="mock",
        session_factory=session_factory,
        feedback_limit=10,
    )
    first_report = worker.poll_tracker_feedback_once()
    second_report = worker.poll_tracker_feedback_once()

    assert first_report.fetched_feedback_items == 1
    assert first_report.created_tracker_feedback_tasks == 1
    assert second_report.fetched_feedback_items == 0
    assert second_report.created_tracker_feedback_tasks == 0

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        feedback_task = repository.find_child_task_by_external_id(
            parent_id=execute_task.id,
            task_type=TaskType.TRACKER_FEEDBACK,
            external_task_id="comment-1",
        )
        assert feedback_task is not None
        assert feedback_task.external_parent_id == tracker_task.external_id
        assert feedback_task.input_payload["tracker_feedback"] == {
            "external_task_id": tracker_task.external_id,
            "comment_id": "comment-1",
            "body": "Please explain why this is 2 points.",
            "author": "heavy-lifting",
            "url": f"mock://tracker/{tracker_task.external_id}/comments/comment-1",
            "metadata": {"source": "operator"},
        }
        execute_task = session.get(Task, execute_task.id)
        assert execute_task is not None
        assert execute_task.context == {
            "title": "Estimate task",
            "description": "Need only an estimate without code changes.",
            "metadata": {"tracker_comment_cursor": "comment-1"},
        }


def test_tracker_intake_skips_system_authored_tracker_comments(session_factory) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(
            context=TaskContext(
                title="Estimate task", description="Estimate only. Do not modify code."
            )
        )
    )
    tracker.add_comment(
        TrackerCommentCreatePayload(
            external_task_id=tracker_task.external_id,
            body="Automated reply",
            metadata={"source": "heavy_lifting"},
        )
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={
                    "title": "Estimate task",
                    "description": "Estimate only. Do not modify code.",
                },
                input_payload={"instructions": "Estimate only. Do not modify code."},
            )
        )

    report = TrackerIntakeWorker(
        tracker=tracker,
        scm=MockScm(),
        tracker_name="mock",
        session_factory=session_factory,
    ).poll_tracker_feedback_once()

    assert report.fetched_feedback_items == 1
    assert report.created_tracker_feedback_tasks == 0
    assert report.skipped_feedback_items == 1


def test_tracker_intake_skips_non_estimate_only_execute_threads(session_factory) -> None:
    tracker = MockTracker()
    tracker_task = tracker.create_task(
        TrackerTaskCreatePayload(context=TaskContext(title="Implementation task"))
    )
    tracker.add_comment(
        TrackerCommentCreatePayload(
            external_task_id=tracker_task.external_id,
            body="Please add more details.",
        )
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id=tracker_task.external_id,
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id=tracker_task.external_id,
                context={"title": "Implementation task"},
                input_payload={"instructions": "Implement the task and open a PR."},
            )
        )

    report = TrackerIntakeWorker(
        tracker=tracker,
        scm=MockScm(),
        tracker_name="mock",
        session_factory=session_factory,
    ).poll_tracker_feedback_once()

    assert report.fetched_feedback_items == 0
    assert report.created_tracker_feedback_tasks == 0


def test_build_tracker_intake_worker_uses_runtime_settings(session_factory) -> None:
    runtime = RuntimeContainer(
        settings=replace(
            get_settings(),
            tracker_poll_interval=12,
            pr_poll_interval=7,
            tracker_fetch_limit=44,
            pr_feedback_fetch_limit=11,
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
    assert worker.fetch_limit == 44
    assert worker.feedback_limit == 11
    assert worker.session_factory is session_factory


def test_tracker_poll_logs_structured_failure_event(session_factory, caplog) -> None:
    caplog.set_level("INFO")
    worker = TrackerIntakeWorker(
        tracker=FailingTracker(),
        scm=MockScm(),
        tracker_name="mock",
        session_factory=session_factory,
        fetch_limit=25,
    )

    with pytest.raises(RuntimeError, match="tracker fetch failed"):
        worker.poll_tracker_once()

    failure_events = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "tracker_poll_failed"
    ]
    assert len(failure_events) == 1
    assert failure_events[0]["component"] == "worker1"
    assert failure_events[0]["tracker_name"] == "mock"
    assert failure_events[0]["fetch_limit"] == 25
    assert failure_events[0]["fetch_statuses"] == ["new"]
    assert failure_events[0]["error"] == "tracker fetch failed"


def test_pr_feedback_poll_logs_structured_failure_event(session_factory, caplog) -> None:
    caplog.set_level("INFO")
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="tracker-task-92",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-92",
                context={"title": "Task 92 root"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="tracker-task-92",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-92",
                branch_name="task92/pr-feedback",
                pr_external_id="pr-92",
                pr_url="https://example.test/repo/pull/92",
                context={"title": "Task 92 root", "metadata": {}},
            )
        )

    worker = TrackerIntakeWorker(
        tracker=MockTracker(),
        scm=FailingScm(),
        tracker_name="mock",
        session_factory=session_factory,
        feedback_limit=7,
    )

    with pytest.raises(RuntimeError, match="scm feedback fetch failed"):
        worker.poll_pr_feedback_once()

    failure_events = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "pr_feedback_poll_failed"
    ]
    assert len(failure_events) == 1
    assert failure_events[0]["component"] == "worker1"
    assert failure_events[0]["tracker_name"] == "mock"
    assert failure_events[0]["feedback_limit"] == 7
    assert failure_events[0]["error"] == "scm feedback fetch failed"

    intake_events = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("component") == "worker1"
    ]
    assert "pr_feedback_intake_started" in [entry["event"] for entry in intake_events]
