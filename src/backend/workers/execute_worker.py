from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.logging_setup import configure_logging
from backend.models import Task
from backend.protocols.agent_runner import AgentRunnerProtocol, AgentRunRequest, AgentRunResult
from backend.protocols.scm import ScmProtocol
from backend.repositories.task_repository import (
    TaskCreateParams,
    TaskRepository,
    TokenUsageCreateParams,
)
from backend.schemas import (
    ScmBranchCreatePayload,
    ScmCommitChangesPayload,
    ScmPullRequestCreatePayload,
    ScmPullRequestMetadata,
    ScmPushBranchPayload,
    ScmWorkspace,
    ScmWorkspaceEnsurePayload,
    TaskLink,
    TaskResultPayload,
    TokenUsagePayload,
)
from backend.services.context_builder import ContextBuilder, parse_task_result_payload
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class ExecuteWorkerReport:
    processed_execute_tasks: int = 0
    processed_pr_feedback_tasks: int = 0
    failed_execute_tasks: int = 0
    failed_pr_feedback_tasks: int = 0


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    task_context: EffectiveTaskContext
    workspace: ScmWorkspace
    branch_name: str
    runtime_metadata: dict[str, object]


@dataclass(slots=True)
class ExecuteWorker:
    scm: ScmProtocol
    agent_runner: AgentRunnerProtocol
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)

    def poll_once(self) -> ExecuteWorkerReport:
        report = ExecuteWorkerReport()
        report = _merge_reports(report, self._process_next_task(TaskType.EXECUTE))
        report = _merge_reports(report, self._process_next_task(TaskType.PR_FEEDBACK))
        return report

    def run_forever(
        self,
        *,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            self.poll_once()
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            sleep_fn(self.poll_interval)

    def _process_next_task(self, task_type: TaskType) -> ExecuteWorkerReport:
        with session_scope(session_factory=self.session_factory) as session:
            repository = TaskRepository(session)
            task = repository.poll_task(task_type=task_type)
            if task is None:
                return ExecuteWorkerReport()

            task.attempt += 1

            try:
                task_chain = repository.load_task_chain(task.root_id or task.id)
                prepared_execution = self._prepare_execution(task=task, task_chain=task_chain)
                run_result = self._execute_prepared_execution(prepared_execution)
                commit_reference = self.scm.commit_changes(
                    ScmCommitChangesPayload(
                        workspace_key=prepared_execution.workspace.workspace_key,
                        branch_name=prepared_execution.branch_name,
                        message=self._resolve_commit_message(
                            task_context=prepared_execution.task_context
                        ),
                        metadata={
                            "task_id": task.id,
                            "flow_type": task.task_type.value,
                        },
                    )
                )
                push_reference = self.scm.push_branch(
                    ScmPushBranchPayload(
                        workspace_key=prepared_execution.workspace.workspace_key,
                        branch_name=prepared_execution.branch_name,
                        metadata={
                            "task_id": task.id,
                            "flow_type": task.task_type.value,
                        },
                    )
                )

                if task_type == TaskType.EXECUTE:
                    self._complete_execute_task(
                        repository=repository,
                        task=task,
                        task_context=prepared_execution.task_context,
                        branch_name=prepared_execution.branch_name,
                        workspace=prepared_execution.workspace,
                        commit_sha=commit_reference.commit_sha,
                        branch_url=push_reference.branch_url,
                        agent_payload=run_result.payload,
                    )
                    return ExecuteWorkerReport(processed_execute_tasks=1)

                self._complete_pr_feedback_task(
                    repository=repository,
                    task=task,
                    task_context=prepared_execution.task_context,
                    branch_name=prepared_execution.branch_name,
                    workspace=prepared_execution.workspace,
                    commit_sha=commit_reference.commit_sha,
                    branch_url=push_reference.branch_url,
                    agent_payload=run_result.payload,
                )
                return ExecuteWorkerReport(processed_pr_feedback_tasks=1)
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                if task_type == TaskType.EXECUTE:
                    return ExecuteWorkerReport(failed_execute_tasks=1)
                return ExecuteWorkerReport(failed_pr_feedback_tasks=1)

    def _prepare_execution(self, *, task: Task, task_chain: list[Task]) -> PreparedExecution:
        task_context = self.context_builder.build_for_task(task=task, task_chain=task_chain)
        workspace = self._ensure_workspace(task_context=task_context)
        branch_name = self._sync_branch(task=task, task_context=task_context, workspace=workspace)
        runtime_metadata: dict[str, object] = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "workspace_key": workspace.workspace_key,
            "workspace_path": workspace.local_path,
            "branch_name": branch_name,
            "repo_url": workspace.repo_url,
            "repo_ref": workspace.repo_ref,
        }
        return PreparedExecution(
            task_context=task_context,
            workspace=workspace,
            branch_name=branch_name,
            runtime_metadata=runtime_metadata,
        )

    def _execute_prepared_execution(self, prepared_execution: PreparedExecution) -> AgentRunResult:
        return self.agent_runner.run(
            AgentRunRequest(
                task_context=prepared_execution.task_context,
                workspace_path=prepared_execution.workspace.local_path,
                metadata=prepared_execution.runtime_metadata,
            )
        )

    def _ensure_workspace(self, *, task_context: EffectiveTaskContext) -> ScmWorkspace:
        repo_url = task_context.repo_url
        workspace_key = task_context.workspace_key
        if not repo_url:
            raise ValueError("Worker 2 requires repo_url for SCM workspace sync")
        if not workspace_key:
            raise ValueError("Worker 2 requires workspace_key for SCM workspace sync")

        return self.scm.ensure_workspace(
            ScmWorkspaceEnsurePayload(
                repo_url=repo_url,
                workspace_key=workspace_key,
                repo_ref=task_context.repo_ref,
                metadata={
                    "flow_type": task_context.flow_type.value,
                    "root_task_id": task_context.root_task.task.id,
                    "current_task_id": task_context.current_task.task.id,
                },
            )
        )

    def _sync_branch(
        self,
        *,
        task: Task,
        task_context: EffectiveTaskContext,
        workspace: ScmWorkspace,
    ) -> str:
        branch_name = self._resolve_branch_name(task=task, task_context=task_context)
        if task.task_type == TaskType.PR_FEEDBACK:
            return branch_name

        self.scm.create_branch(
            ScmBranchCreatePayload(
                workspace_key=workspace.workspace_key,
                branch_name=branch_name,
                from_ref=self._resolve_base_branch(task_context),
                metadata={
                    "flow_type": task.task_type.value,
                    "task_id": task.id,
                    "reused_pr": task.task_type == TaskType.PR_FEEDBACK,
                },
            )
        )
        return branch_name

    def _complete_execute_task(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_context: EffectiveTaskContext,
        branch_name: str,
        workspace: ScmWorkspace,
        commit_sha: str,
        branch_url: str | None,
        agent_payload: TaskResultPayload,
    ) -> None:
        pr_external_id = task.pr_external_id
        pr_url = task.pr_url
        pr_action = "reused"

        if not pr_external_id or not pr_url:
            pull_request = self.scm.create_pull_request(
                ScmPullRequestCreatePayload(
                    workspace_key=workspace.workspace_key,
                    branch_name=branch_name,
                    base_branch=self._resolve_base_branch(task_context),
                    title=self._build_pr_title(task_context),
                    body=self._build_pr_body(
                        task_context=task_context, agent_payload=agent_payload
                    ),
                    pr_metadata=self._build_pr_metadata(task_context),
                    metadata={
                        "task_id": task.id,
                        "flow_type": task.task_type.value,
                    },
                )
            )
            pr_external_id = pull_request.external_id
            pr_url = pull_request.url
            pr_action = "created"

        result_payload = self._build_result_payload(
            agent_payload=agent_payload,
            flow_type=TaskType.EXECUTE,
            branch_name=branch_name,
            commit_sha=commit_sha,
            pr_url=pr_url,
            branch_url=branch_url,
            workspace=workspace,
            pr_action=pr_action,
        )
        self._mark_task_done(
            task=task,
            result_payload=result_payload,
            branch_name=branch_name,
            pr_external_id=pr_external_id,
            pr_url=pr_url,
        )
        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )
        self._ensure_deliver_task(
            repository=repository, execute_task=task, task_context=task_context
        )

    def _complete_pr_feedback_task(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_context: EffectiveTaskContext,
        branch_name: str,
        workspace: ScmWorkspace,
        commit_sha: str,
        branch_url: str | None,
        agent_payload: TaskResultPayload,
    ) -> None:
        pr_external_id = task_context.pr_external_id
        pr_url = task_context.pr_url
        if not pr_external_id or not pr_url:
            raise ValueError("pr_feedback task requires an existing pull request")

        result_payload = self._build_result_payload(
            agent_payload=agent_payload,
            flow_type=TaskType.PR_FEEDBACK,
            branch_name=branch_name,
            commit_sha=commit_sha,
            pr_url=pr_url,
            branch_url=branch_url,
            workspace=workspace,
            pr_action="reused",
        )
        self._mark_task_done(
            task=task,
            result_payload=result_payload,
            branch_name=branch_name,
            pr_external_id=pr_external_id,
            pr_url=pr_url,
        )

        execute_task_entry = task_context.execute_task
        if execute_task_entry is None:
            raise ValueError("pr_feedback task requires an execute ancestor")

        execute_task = execute_task_entry.task
        execute_result = parse_task_result_payload(execute_task) or TaskResultPayload(
            summary="Execution PR updated after review feedback."
        )
        execute_metadata = dict(execute_result.metadata)
        execute_metadata.update(
            {
                "last_updated_flow": TaskType.PR_FEEDBACK.value,
                "last_feedback_task_id": task.id,
                "last_feedback_comment_id": task_context.current_feedback.comment_id
                if task_context.current_feedback is not None
                else None,
            }
        )
        updated_execute_result = execute_result.model_copy(
            update={
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "pr_url": pr_url,
                "metadata": execute_metadata,
            }
        )
        execute_task.branch_name = branch_name
        execute_task.pr_external_id = pr_external_id
        execute_task.pr_url = pr_url
        execute_task.result_payload = _dump_result_payload(updated_execute_result)
        task.status = TaskStatus.DONE
        task.error = None
        task.result_payload = _dump_result_payload(result_payload)
        task.branch_name = branch_name
        task.pr_external_id = pr_external_id
        task.pr_url = pr_url

        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )

    def _mark_task_done(
        self,
        *,
        task: Task,
        result_payload: TaskResultPayload,
        branch_name: str,
        pr_external_id: str | None,
        pr_url: str | None,
    ) -> None:
        task.status = TaskStatus.DONE
        task.error = None
        task.result_payload = _dump_result_payload(result_payload)
        task.branch_name = branch_name
        task.pr_external_id = pr_external_id
        task.pr_url = pr_url

    def _ensure_deliver_task(
        self,
        *,
        repository: TaskRepository,
        execute_task: Task,
        task_context: EffectiveTaskContext,
    ) -> None:
        if (
            repository.find_child_task(parent_id=execute_task.id, task_type=TaskType.DELIVER)
            is not None
        ):
            return

        execution_title = (
            task_context.execution_context.title
            if task_context.execution_context is not None
            else "execution result"
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                status=TaskStatus.NEW,
                tracker_name=execute_task.tracker_name,
                external_parent_id=execute_task.external_parent_id,
                repo_url=execute_task.repo_url,
                repo_ref=execute_task.repo_ref,
                workspace_key=execute_task.workspace_key,
                branch_name=execute_task.branch_name,
                pr_external_id=execute_task.pr_external_id,
                pr_url=execute_task.pr_url,
                context={"title": f"Deliver result for {execution_title}"},
            )
        )

    def _record_token_usage(
        self,
        *,
        repository: TaskRepository,
        task_id: int,
        usage: list[TokenUsagePayload],
    ) -> None:
        for item in usage:
            repository.record_token_usage(
                task_id=task_id,
                usage=TokenUsageCreateParams(
                    model=item.model,
                    provider=item.provider,
                    input_tokens=item.input_tokens,
                    output_tokens=item.output_tokens,
                    cached_tokens=item.cached_tokens,
                    estimated=item.estimated,
                    cost_usd=item.cost_usd,
                ),
            )

    def _build_result_payload(
        self,
        *,
        agent_payload: TaskResultPayload,
        flow_type: TaskType,
        branch_name: str,
        commit_sha: str,
        pr_url: str | None,
        branch_url: str | None,
        workspace: ScmWorkspace,
        pr_action: str,
    ) -> TaskResultPayload:
        metadata = dict(agent_payload.metadata)
        metadata.update(
            {
                "workspace_key": workspace.workspace_key,
                "repo_url": workspace.repo_url,
                "repo_ref": workspace.repo_ref,
                "flow_type": flow_type.value,
                "pr_action": pr_action,
            }
        )
        links = list(agent_payload.links)
        _append_link_once(links, label="branch", url=branch_url)
        _append_link_once(links, label="pull_request", url=pr_url)
        return agent_payload.model_copy(
            update={
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "pr_url": pr_url,
                "links": links,
                "metadata": metadata,
            }
        )

    def _resolve_branch_name(self, *, task: Task, task_context: EffectiveTaskContext) -> str:
        if task_context.branch_name:
            return task_context.branch_name
        if task.task_type == TaskType.PR_FEEDBACK:
            raise ValueError("pr_feedback task requires an existing branch_name")

        tracker_identifier = (
            task.external_parent_id
            or task_context.root_task.task.external_task_id
            or f"task-{task.id}"
        )
        slug = _slugify(tracker_identifier)
        return f"execute/{slug}"

    def _resolve_base_branch(self, task_context: EffectiveTaskContext) -> str:
        return task_context.base_branch or task_context.repo_ref or "main"

    def _resolve_commit_message(self, *, task_context: EffectiveTaskContext) -> str:
        if task_context.commit_message_hint:
            return task_context.commit_message_hint
        if (
            task_context.flow_type == TaskType.PR_FEEDBACK
            and task_context.current_feedback is not None
        ):
            return f"Address PR feedback {task_context.current_feedback.comment_id}"
        execution_title = (
            task_context.execution_context.title
            if task_context.execution_context is not None
            else "execution task"
        )
        return f"Apply agent result for {execution_title}"

    def _build_pr_title(self, task_context: EffectiveTaskContext) -> str:
        if task_context.execution_context is not None:
            return task_context.execution_context.title
        if task_context.tracker_context is not None:
            return task_context.tracker_context.title
        return f"Execution task {task_context.current_task.task.id}"

    def _build_pr_body(
        self,
        *,
        task_context: EffectiveTaskContext,
        agent_payload: TaskResultPayload,
    ) -> str:
        parts = [agent_payload.summary]
        if task_context.instructions:
            parts.append(f"Instructions: {task_context.instructions}")
        if agent_payload.details:
            parts.append(agent_payload.details)
        return "\n\n".join(parts)

    def _build_pr_metadata(self, task_context: EffectiveTaskContext) -> ScmPullRequestMetadata:
        execute_task = (
            task_context.execute_task.task if task_context.execute_task is not None else None
        )
        execute_task_external_id = None
        if execute_task is not None:
            execute_task_external_id = (
                execute_task.external_parent_id or execute_task.external_task_id
            )
        if execute_task_external_id is None:
            execute_task_external_id = str(task_context.current_task.task.id)

        return ScmPullRequestMetadata(
            execute_task_external_id=execute_task_external_id,
            tracker_name=task_context.current_task.task.tracker_name,
            workspace_key=task_context.workspace_key,
            repo_url=task_context.repo_url,
            metadata={
                "root_task_id": task_context.root_task.task.id,
                "current_task_id": task_context.current_task.task.id,
            },
        )


def build_execute_worker(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> ExecuteWorker:
    active_runtime = runtime or create_runtime_container()
    return ExecuteWorker(
        scm=active_runtime.scm,
        agent_runner=active_runtime.agent_runner,
        session_factory=session_factory or get_session_factory(),
        poll_interval=active_runtime.settings.tracker_poll_interval,
    )


def run(
    *,
    once: bool = False,
    max_iterations: int | None = None,
) -> ExecuteWorker:
    settings = get_settings()
    logger = configure_logging(app_name=settings.app_name, component="worker2")
    logger.info("Starting execute worker once=%s max_iterations=%s", once, max_iterations)
    worker = build_execute_worker()
    if once:
        worker.poll_once()
    else:
        worker.run_forever(max_iterations=max_iterations, sleep_fn=time.sleep)
    return worker


def _merge_reports(left: ExecuteWorkerReport, right: ExecuteWorkerReport) -> ExecuteWorkerReport:
    return ExecuteWorkerReport(
        processed_execute_tasks=left.processed_execute_tasks + right.processed_execute_tasks,
        processed_pr_feedback_tasks=(
            left.processed_pr_feedback_tasks + right.processed_pr_feedback_tasks
        ),
        failed_execute_tasks=left.failed_execute_tasks + right.failed_execute_tasks,
        failed_pr_feedback_tasks=left.failed_pr_feedback_tasks + right.failed_pr_feedback_tasks,
    )


def _append_link_once(links: list[TaskLink], *, label: str, url: str | None) -> None:
    if not url:
        return
    if any(existing_link.url == url for existing_link in links):
        return
    links.append(TaskLink(label=label, url=url))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "task"


def _dump_result_payload(payload: TaskResultPayload) -> dict[str, object]:
    return payload.model_dump(mode="json")


__all__ = [
    "ExecuteWorker",
    "ExecuteWorkerReport",
    "build_execute_worker",
    "run",
]
