from __future__ import annotations

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.protocols.agent_runner import AgentRunRequest
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.services.context_builder import ContextBuilder
from backend.task_constants import TaskType


def test_local_agent_runner_returns_normalized_execute_result(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-24",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task24/runner",
                context={"title": "Implement runner abstraction"},
                input_payload={
                    "instructions": "Implement a placeholder agent runner and tests.",
                    "base_branch": "main",
                    "branch_name": "task24/runner",
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    result = LocalAgentRunner().run(
        AgentRunRequest(task_context=task_context, workspace_path="/workspace/repos/repo-24")
    )

    assert (
        result.payload.summary == "Prepared local agent execution for Implement runner abstraction."
    )
    assert result.payload.branch_name == "task24/runner"
    assert result.payload.pr_url is None
    assert len(result.token_usage) == 1
    assert result.token_usage[0].estimated is True
    assert result.summary_metadata == {
        "runner": "local-placeholder-runner",
        "mode": "placeholder",
        "flow_type": "execute",
        "workspace_path": "/workspace/repos/repo-24",
        "has_feedback": False,
        "feedback_history_count": 0,
        "estimated_cost_usd": str(result.token_usage[0].cost_usd),
    }


def test_local_agent_runner_includes_feedback_metadata_for_pr_feedback(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.FETCH, context={"title": "Tracker task"})
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task24/runner-feedback",
                context={"title": "Implement runner abstraction"},
                input_payload={"instructions": "Initial implementation."},
                result_payload={"summary": "Opened PR", "pr_url": "https://example.test/pr/24"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "instructions": "Address first review comment.",
                    "pr_feedback": {
                        "pr_external_id": "pr-24",
                        "comment_id": "c-1",
                        "body": "Please add token metadata.",
                    },
                },
                result_payload={"summary": "Updated metadata"},
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "instructions": "Address latest review comment.",
                    "pr_feedback": {
                        "pr_external_id": "pr-24",
                        "comment_id": "c-2",
                        "body": "Please keep the API small.",
                        "pr_url": "https://example.test/pr/24",
                    },
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=feedback_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    result = LocalAgentRunner().run(
        AgentRunRequest(task_context=task_context, workspace_path="/workspace/repos/repo-24")
    )

    assert result.payload.summary == "Prepared follow-up response for review comment c-2."
    assert result.payload.pr_url == "https://example.test/pr/24"
    assert result.summary_metadata["has_feedback"] is True
    assert result.summary_metadata["feedback_history_count"] == 1
    assert result.token_usage[0].cached_tokens > 0
