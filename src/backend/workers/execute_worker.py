from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
from backend.estimate_mode import is_explicit_estimate_only_context
from backend.logging_setup import configure_logging, get_logger
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
from backend.services.retro_service import RetroService
from backend.settings import Settings, get_settings
from backend.task_constants import TaskStatus, TaskType
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class ExecuteWorkerReport:
    processed_execute_tasks: int = 0
    processed_pr_feedback_tasks: int = 0
    processed_tracker_feedback_tasks: int = 0
    failed_execute_tasks: int = 0
    failed_pr_feedback_tasks: int = 0
    failed_tracker_feedback_tasks: int = 0


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    task_context: EffectiveTaskContext
    workspace: ScmWorkspace
    branch_name: str | None
    pre_run_head_sha: str | None
    runtime_metadata: dict[str, object]
    skip_scm_artifacts: bool = False


@dataclass(slots=True)
class ExecuteWorker:
    scm: ScmProtocol
    agent_runner: AgentRunnerProtocol
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    settings: Settings = field(default_factory=get_settings)

    def poll_once(self) -> ExecuteWorkerReport:
        batch_size = self._read_execute_batch_size()
        report = ExecuteWorkerReport()
        for _ in range(batch_size):
            report = _merge_reports(report, self._process_next_task(TaskType.EXECUTE))
        report = _merge_reports(report, self._process_next_task(TaskType.PR_FEEDBACK))
        report = _merge_reports(report, self._process_next_task(TaskType.TRACKER_FEEDBACK))
        return report

    def _read_execute_batch_size(self) -> int:
        try:
            from backend.models import ApplicationSetting  # noqa: PLC0415

            with session_scope(session_factory=self.session_factory) as session:
                row = (
                    session.query(ApplicationSetting)
                    .filter_by(setting_key="execute_worker_batch_size")
                    .first()
                )
                if row is not None:
                    return max(1, min(int(row.value), 20))
        except Exception:
            pass
        return 1

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
            logger = _task_logger(task, attempt=task.attempt)
            logger.info("worker_task_picked_up")

            try:
                task_chain = repository.load_task_chain(task.root_id or task.id)
                prepared_execution = self._prepare_execution(
                    repository=repository, task=task, task_chain=task_chain
                )
                run_result = self._execute_prepared_execution(
                    task=task,
                    prepared_execution=prepared_execution,
                )
                if run_result.execution_failed:
                    self._mark_task_failed(
                        task=task,
                        error=run_result.failure_message or run_result.payload.summary,
                        result_payload=run_result.payload,
                        branch_name=prepared_execution.branch_name,
                    )
                    self._record_agent_retro_feedback(
                        repository=repository,
                        task=task,
                        result_payload=run_result.payload,
                    )
                    if task_type == TaskType.EXECUTE:
                        return ExecuteWorkerReport(failed_execute_tasks=1)
                    if task_type == TaskType.PR_FEEDBACK:
                        return ExecuteWorkerReport(failed_pr_feedback_tasks=1)
                    return ExecuteWorkerReport(failed_tracker_feedback_tasks=1)
                if prepared_execution.skip_scm_artifacts:
                    if task_type == TaskType.EXECUTE:
                        self._complete_execute_task_without_scm(
                            repository=repository,
                            task=task,
                            task_context=prepared_execution.task_context,
                            agent_payload=run_result.payload,
                        )
                        return ExecuteWorkerReport(processed_execute_tasks=1)
                    self._complete_tracker_feedback_task_without_scm(
                        repository=repository,
                        task=task,
                        task_context=prepared_execution.task_context,
                        agent_payload=run_result.payload,
                    )
                    return ExecuteWorkerReport(processed_tracker_feedback_tasks=1)

                branch_name = prepared_execution.branch_name
                if branch_name is None:
                    raise ValueError("normal SCM execution requires branch_name")

                commit_reference = self.scm.commit_changes(
                    ScmCommitChangesPayload(
                        workspace_key=prepared_execution.workspace.workspace_key,
                        branch_name=branch_name,
                        message=self._resolve_commit_message(
                            task_context=prepared_execution.task_context
                        ),
                        pre_run_head_sha=prepared_execution.pre_run_head_sha,
                        metadata={
                            "task_id": task.id,
                            "flow_type": task.task_type.value,
                        },
                    )
                )
                push_reference = self.scm.push_branch(
                    ScmPushBranchPayload(
                        workspace_key=prepared_execution.workspace.workspace_key,
                        branch_name=branch_name,
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
                        branch_name=branch_name,
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
                    branch_name=branch_name,
                    workspace=prepared_execution.workspace,
                    commit_sha=commit_reference.commit_sha,
                    branch_url=push_reference.branch_url,
                    agent_payload=run_result.payload,
                )
                logger.info(
                    "pr_feedback_task_completed",
                    branch_name=branch_name,
                    commit_sha=commit_reference.commit_sha,
                )
                return ExecuteWorkerReport(processed_pr_feedback_tasks=1)
            except Exception as exc:
                logger.exception("task_failed", error=str(exc))
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                if task_type == TaskType.EXECUTE:
                    return ExecuteWorkerReport(failed_execute_tasks=1)
                if task_type == TaskType.PR_FEEDBACK:
                    return ExecuteWorkerReport(failed_pr_feedback_tasks=1)
                return ExecuteWorkerReport(failed_tracker_feedback_tasks=1)

    def _prepare_execution(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_chain: list[Task],
    ) -> PreparedExecution:
        task_context = self.context_builder.build_for_task(task=task, task_chain=task_chain)
        skip_scm_artifacts = should_skip_scm_artifacts(task_context=task_context)
        workspace_key = self._resolve_workspace_key(task=task, task_context=task_context)
        if workspace_key != task_context.workspace_key:
            repository.update_task_workspace_context(task.id, workspace_key=workspace_key)
            task_context = replace(task_context, workspace_key=workspace_key)
        workspace = self._ensure_workspace(task_context=task_context)
        repository.update_task_workspace_context(
            task.id,
            repo_url=workspace.repo_url,
            repo_ref=workspace.repo_ref,
            workspace_key=workspace.workspace_key,
        )
        branch_name = None
        pre_run_head_sha = None
        if not skip_scm_artifacts:
            branch_name = self._sync_branch(
                task=task, task_context=task_context, workspace=workspace
            )
            pre_run_head_sha = self.scm.get_head_commit(workspace.workspace_key, branch_name)
        runtime_metadata: dict[str, object] = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "workspace_key": workspace.workspace_key,
            "workspace_path": workspace.local_path,
            "branch_name": branch_name,
            "repo_url": workspace.repo_url,
            "repo_ref": workspace.repo_ref,
        }
        if pre_run_head_sha is not None:
            runtime_metadata["pre_run_head_sha"] = pre_run_head_sha
        _task_logger(
            task,
            workspace_key=workspace.workspace_key,
            workspace_path=workspace.local_path,
            branch_name=branch_name,
            repo_url=workspace.repo_url,
            repo_ref=workspace.repo_ref,
        ).info("workspace_prepared")
        return PreparedExecution(
            task_context=task_context,
            workspace=workspace,
            branch_name=branch_name,
            pre_run_head_sha=pre_run_head_sha,
            runtime_metadata=runtime_metadata,
            skip_scm_artifacts=skip_scm_artifacts,
        )

    def _execute_prepared_execution(
        self,
        *,
        task: Task,
        prepared_execution: PreparedExecution,
    ) -> AgentRunResult:
        logger = _task_logger(
            task,
            workspace_key=prepared_execution.workspace.workspace_key,
            workspace_path=prepared_execution.workspace.local_path,
            branch_name=prepared_execution.branch_name,
            runner=self.agent_runner.__class__.__name__,
        )
        logger.info("agent_run_started")
        result = self.agent_runner.run(
            AgentRunRequest(
                task_context=prepared_execution.task_context,
                workspace_path=prepared_execution.workspace.local_path,
                metadata=prepared_execution.runtime_metadata,
            )
        )
        logger.info(
            "agent_run_finished",
            result_summary=result.payload.summary,
            token_usage_entries=len(result.payload.token_usage),
            has_details=result.payload.details is not None,
        )
        return result

    def _ensure_workspace(self, *, task_context: EffectiveTaskContext) -> ScmWorkspace:
        workspace_key = task_context.workspace_key
        if not workspace_key:
            raise ValueError("Worker 2 requires workspace_key for SCM workspace sync")

        checkout_branch_name = None
        if task_context.flow_type == TaskType.PR_FEEDBACK:
            checkout_branch_name = task_context.branch_name

        return self.scm.ensure_workspace(
            ScmWorkspaceEnsurePayload(
                repo_url=task_context.repo_url,
                workspace_key=workspace_key,
                repo_ref=task_context.repo_ref,
                branch_name=checkout_branch_name,
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
                    pr_metadata=self._build_pr_metadata(task_context, workspace=workspace),
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
        _task_logger(
            task,
            branch_name=branch_name,
            commit_sha=commit_sha,
            pr_external_id=pr_external_id,
            pr_url=pr_url,
            pr_action=pr_action,
        ).info("execute_task_completed")
        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )
        self._record_agent_retro_feedback(
            repository=repository, task=task, result_payload=result_payload
        )
        self._ensure_deliver_task(
            repository=repository, execute_task=task, task_context=task_context
        )

    def _complete_execute_task_without_scm(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_context: EffectiveTaskContext,
        agent_payload: TaskResultPayload,
    ) -> None:
        result_payload = self._build_result_payload(
            agent_payload=self._build_delivery_only_payload(agent_payload=agent_payload),
            flow_type=TaskType.EXECUTE,
            branch_name=None,
            commit_sha=None,
            pr_url=None,
            branch_url=None,
            workspace=None,
            pr_action="skipped",
        )
        self._mark_task_done(
            task=task,
            result_payload=result_payload,
            branch_name=None,
            pr_external_id=None,
            pr_url=None,
        )
        _task_logger(
            task,
            scm_artifacts_skipped=True,
            pr_action="skipped",
        ).info("execute_task_completed")
        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )
        self._record_agent_retro_feedback(
            repository=repository, task=task, result_payload=result_payload
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
        _task_logger(
            task,
            branch_name=branch_name,
            commit_sha=commit_sha,
            pr_external_id=pr_external_id,
            pr_url=pr_url,
        ).info("pr_feedback_result_applied")

        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )
        self._record_agent_retro_feedback(
            repository=repository, task=task, result_payload=result_payload
        )

    def _complete_tracker_feedback_task_without_scm(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_context: EffectiveTaskContext,
        agent_payload: TaskResultPayload,
    ) -> None:
        current_feedback = task_context.current_feedback
        if current_feedback is None:
            raise ValueError("tracker_feedback task requires current feedback")

        execute_task_entry = task_context.execute_task
        if execute_task_entry is None:
            raise ValueError("tracker_feedback task requires an execute ancestor")
        execute_task = execute_task_entry.task
        execute_result = parse_task_result_payload(execute_task) or TaskResultPayload(
            summary="Tracker thread updated after follow-up comment."
        )
        inherited_estimate = _extract_normalized_estimate(metadata=execute_result.metadata)

        result_payload = self._build_result_payload(
            agent_payload=self._build_delivery_only_payload(
                agent_payload=agent_payload,
                inherited_estimate=inherited_estimate,
            ),
            flow_type=TaskType.TRACKER_FEEDBACK,
            branch_name=None,
            commit_sha=None,
            pr_url=None,
            branch_url=None,
            workspace=None,
            pr_action="skipped",
        )
        self._mark_task_done(
            task=task,
            result_payload=result_payload,
            branch_name=None,
            pr_external_id=None,
            pr_url=None,
        )
        execute_metadata = dict(execute_result.metadata)
        execute_metadata.update(
            {
                "last_updated_flow": TaskType.TRACKER_FEEDBACK.value,
                "last_feedback_task_id": task.id,
                "last_feedback_comment_id": current_feedback.comment_id,
            }
        )
        execute_task.result_payload = _dump_result_payload(
            execute_result.model_copy(update={"metadata": execute_metadata})
        )
        _task_logger(
            task,
            scm_artifacts_skipped=True,
            tracker_comment_id=current_feedback.comment_id,
        ).info("tracker_feedback_result_applied")
        self._record_token_usage(
            repository=repository, task_id=task.id, usage=result_payload.token_usage
        )
        self._record_agent_retro_feedback(
            repository=repository, task=task, result_payload=result_payload
        )
        self._ensure_deliver_task(
            repository=repository,
            execute_task=task,
            task_context=task_context,
        )

    def _mark_task_done(
        self,
        *,
        task: Task,
        result_payload: TaskResultPayload,
        branch_name: str | None,
        pr_external_id: str | None,
        pr_url: str | None,
    ) -> None:
        task.status = TaskStatus.DONE
        task.error = None
        task.result_payload = _dump_result_payload(result_payload)
        task.branch_name = branch_name
        task.pr_external_id = pr_external_id
        task.pr_url = pr_url

    def _mark_task_failed(
        self,
        *,
        task: Task,
        error: str,
        result_payload: TaskResultPayload | None = None,
        branch_name: str | None = None,
    ) -> None:
        task.status = TaskStatus.FAILED
        task.error = error
        task.result_payload = (
            _dump_result_payload(result_payload) if result_payload is not None else None
        )
        task.branch_name = branch_name
        task.pr_external_id = None
        task.pr_url = None

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

        delivery_parent = (
            task_context.feedback_task.task
            if task_context.current_task.task.task_type == TaskType.TRACKER_FEEDBACK
            and task_context.feedback_task is not None
            else execute_task
        )
        execution_title = (
            task_context.execution_context.title
            if task_context.execution_context is not None
            else "execution result"
        )
        deliver_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=delivery_parent.id,
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
        _task_logger(
            execute_task,
            deliver_task_id=deliver_task.id,
            branch_name=deliver_task.branch_name,
            pr_external_id=deliver_task.pr_external_id,
            pr_url=deliver_task.pr_url,
        ).info("deliver_task_created")

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

    def _record_agent_retro_feedback(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        result_payload: TaskResultPayload,
    ) -> None:
        RetroService(repository.session).record_agent_feedback(
            task=task,
            result_metadata=result_payload.metadata,
        )

    def _build_result_payload(
        self,
        *,
        agent_payload: TaskResultPayload,
        flow_type: TaskType,
        branch_name: str | None,
        commit_sha: str | None,
        pr_url: str | None,
        branch_url: str | None,
        workspace: ScmWorkspace | None,
        pr_action: str,
    ) -> TaskResultPayload:
        metadata = dict(agent_payload.metadata)
        metadata.update({"flow_type": flow_type.value, "pr_action": pr_action})
        if workspace is not None:
            metadata.update(
                {
                    "workspace_key": workspace.workspace_key,
                    "repo_url": workspace.repo_url,
                    "repo_ref": workspace.repo_ref,
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

    def _build_delivery_only_payload(
        self,
        *,
        agent_payload: TaskResultPayload,
        inherited_estimate: dict[str, object] | None = None,
    ) -> TaskResultPayload:
        metadata = dict(agent_payload.metadata)
        metadata["delivery_mode"] = "estimate_only"
        tracker_comment = self._build_delivery_only_comment(agent_payload=agent_payload)
        if inherited_estimate is not None:
            metadata["estimate"] = inherited_estimate
        else:
            metadata["estimate"] = _derive_estimate_metadata(
                metadata=metadata,
                tracker_comment=tracker_comment,
                summary=agent_payload.summary,
                details=agent_payload.details,
            )
        return agent_payload.model_copy(
            update={
                "branch_name": None,
                "commit_sha": None,
                "pr_url": None,
                "links": [],
                "tracker_comment": tracker_comment,
                "metadata": metadata,
            }
        )

    def _build_delivery_only_comment(self, *, agent_payload: TaskResultPayload) -> str:
        comment = ""
        for candidate in self._delivery_only_comment_sources(agent_payload=agent_payload):
            if not comment:
                comment = candidate
                continue
            comment = _merge_delivery_comment_text(comment, candidate)
        return comment or agent_payload.summary

    def _delivery_only_comment_sources(self, *, agent_payload: TaskResultPayload) -> list[str]:
        sources: list[str | None] = []
        stdout_preview = agent_payload.metadata.get("stdout_preview")
        if isinstance(stdout_preview, str):
            sources.append(stdout_preview)
        sources.extend(
            [
                agent_payload.tracker_comment,
                _normalize_delivery_comment_text(agent_payload.details),
            ]
        )

        unique_sources: list[str] = []
        seen: set[str] = set()
        for source in sources:
            normalized = _normalize_delivery_comment_text(source)
            if normalized is None:
                continue
            canonical = _canonicalize_delivery_comment_text(normalized)
            if canonical in seen:
                continue
            unique_sources.append(normalized)
            seen.add(canonical)
        return unique_sources

    def _should_skip_scm_artifacts(self, *, task_context: EffectiveTaskContext) -> bool:
        return should_skip_scm_artifacts(task_context=task_context)

    def _resolve_branch_name(self, *, task: Task, task_context: EffectiveTaskContext) -> str:
        if task_context.branch_name:
            return task_context.branch_name
        if task.task_type == TaskType.PR_FEEDBACK:
            raise ValueError("pr_feedback task requires an existing branch_name")

        slug = _slugify(self._resolve_tracker_identifier(task=task, task_context=task_context))
        return f"{self.settings.scm_branch_prefix}{slug}"

    def _resolve_workspace_key(self, *, task: Task, task_context: EffectiveTaskContext) -> str:
        if task_context.workspace_key:
            return task_context.workspace_key
        if task.task_type == TaskType.TRACKER_FEEDBACK:
            return _slugify(self._resolve_tracker_identifier(task=task, task_context=task_context))
        if task.task_type != TaskType.EXECUTE:
            raise ValueError("Worker 2 requires workspace_key for SCM workspace sync")
        return _slugify(self._resolve_tracker_identifier(task=task, task_context=task_context))

    def _resolve_tracker_identifier(
        self,
        *,
        task: Task,
        task_context: EffectiveTaskContext,
    ) -> str:
        return (
            task.external_parent_id
            or task_context.root_task.task.external_task_id
            or f"task-{task.id}"
        )

    def _resolve_base_branch(self, task_context: EffectiveTaskContext) -> str:
        return (
            task_context.base_branch
            or task_context.repo_ref
            or self.settings.scm_default_base_branch
            or "main"
        )

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

    def _build_pr_metadata(
        self,
        task_context: EffectiveTaskContext,
        *,
        workspace: ScmWorkspace,
    ) -> ScmPullRequestMetadata:
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
            workspace_key=workspace.workspace_key,
            repo_url=workspace.repo_url,
            metadata={
                "root_task_id": task_context.root_task.task.id,
                "current_task_id": task_context.current_task.task.id,
            },
        )


def should_skip_scm_artifacts(*, task_context: EffectiveTaskContext) -> bool:
    if task_context.flow_type == TaskType.TRACKER_FEEDBACK:
        return True
    if task_context.flow_type != TaskType.EXECUTE:
        return False
    if is_explicit_estimate_only_context(task_context):
        return True
    text_parts = [
        task_context.instructions,
        task_context.tracker_context.title if task_context.tracker_context else None,
        task_context.tracker_context.description if task_context.tracker_context else None,
        task_context.execution_context.title if task_context.execution_context else None,
        task_context.execution_context.description if task_context.execution_context else None,
    ]
    normalized_text = "\n".join(part.lower() for part in text_parts if part)
    estimate_markers = (
        "estimate only",
        "only estimate",
        "story point",
        "story-point",
        "оцен",
        "только оцен",
    )
    no_code_markers = (
        "do not modify code",
        "don't modify code",
        "do not change code",
        "without code changes",
        "no code changes",
        "не изменяй код",
        "не изменять код",
        "не менять код",
        "без изменений кода",
    )
    return any(marker in normalized_text for marker in estimate_markers) and any(
        marker in normalized_text for marker in no_code_markers
    )


def build_execute_worker(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
) -> ExecuteWorker:
    active_runtime = runtime or create_runtime_container()
    active_settings = settings or active_runtime.settings
    return ExecuteWorker(
        scm=active_runtime.scm,
        agent_runner=active_runtime.agent_runner,
        session_factory=session_factory or get_session_factory(),
        poll_interval=active_settings.tracker_poll_interval,
        settings=active_settings,
    )


def run(
    *,
    once: bool = False,
    max_iterations: int | None = None,
) -> ExecuteWorker:
    settings = get_settings()
    logger = configure_logging(app_name=settings.app_name, component="worker2")
    logger.info("worker_started", once=once, max_iterations=max_iterations)
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
        processed_tracker_feedback_tasks=(
            left.processed_tracker_feedback_tasks + right.processed_tracker_feedback_tasks
        ),
        failed_execute_tasks=left.failed_execute_tasks + right.failed_execute_tasks,
        failed_pr_feedback_tasks=left.failed_pr_feedback_tasks + right.failed_pr_feedback_tasks,
        failed_tracker_feedback_tasks=(
            left.failed_tracker_feedback_tasks + right.failed_tracker_feedback_tasks
        ),
    )


def _append_link_once(links: list[TaskLink], *, label: str, url: str | None) -> None:
    if not url:
        return
    if any(existing_link.url == url for existing_link in links):
        return
    links.append(TaskLink(label=label, url=url))


def _normalize_delivery_comment_text(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if normalized.startswith("stdout:\n"):
        normalized = normalized.removeprefix("stdout:\n").strip()
    return normalized or None


def _canonicalize_delivery_comment_text(text: str) -> str:
    return " ".join(text.split())


def _merge_delivery_comment_text(current: str, candidate: str) -> str:
    current_canonical = _canonicalize_delivery_comment_text(current)
    candidate_canonical = _canonicalize_delivery_comment_text(candidate)
    if current_canonical == candidate_canonical:
        return current
    if current_canonical in candidate_canonical:
        return candidate
    if candidate_canonical in current_canonical:
        return current

    merged_lines = list(current.splitlines())
    existing_lines = {
        _canonicalize_delivery_comment_text(line) for line in merged_lines if line.strip()
    }
    for line in candidate.splitlines():
        normalized_line = line.strip()
        if not normalized_line:
            continue
        canonical_line = _canonicalize_delivery_comment_text(normalized_line)
        if canonical_line in existing_lines:
            continue
        merged_lines.append(normalized_line)
        existing_lines.add(canonical_line)
    return "\n".join(line for line in merged_lines if line.strip())


def _derive_estimate_metadata(
    *,
    metadata: dict[str, object],
    tracker_comment: str,
    summary: str,
    details: str | None,
) -> dict[str, object]:
    structured = metadata.get("estimate")
    if isinstance(structured, dict):
        story_points = structured.get("story_points")
        rationale = structured.get("rationale")
        if isinstance(story_points, int) and isinstance(rationale, str) and rationale.strip():
            return {
                "story_points": story_points,
                "can_take_in_work": story_points <= 2,
                "rationale": rationale.strip(),
            }

    structured_from_text = _extract_structured_estimate_from_text(
        [tracker_comment, summary, details]
    )
    if structured_from_text is not None:
        story_points, rationale = structured_from_text
        return {
            "story_points": story_points,
            "can_take_in_work": story_points <= 2,
            "rationale": rationale,
        }

    parsed_story_points = _extract_story_points_from_text([tracker_comment, summary, details])
    rationale = _extract_rationale_from_text([tracker_comment, details, summary])
    if parsed_story_points is None or rationale is None:
        raise ValueError(
            "estimate_only normalization requires parseable story_points and non-empty rationale"
        )
    return {
        "story_points": parsed_story_points,
        "can_take_in_work": parsed_story_points <= 2,
        "rationale": rationale,
    }


def _extract_story_points_from_text(candidates: list[str | None]) -> int | None:
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"\b(\d+)\s*(?:sp|story\s*points?)\b", candidate, re.IGNORECASE)
        if match is None:
            continue
        return int(match.group(1))
    return None


def _extract_structured_estimate_from_text(
    candidates: list[str | None],
) -> tuple[int, str] | None:
    for candidate in candidates:
        if not candidate:
            continue
        for line in candidate.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("estimate_json:"):
                continue
            raw_json = stripped.split(":", 1)[1].strip()
            if not raw_json:
                continue
            try:
                parsed = json.loads(raw_json)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            story_points = parsed.get("story_points")
            rationale = parsed.get("rationale")
            if isinstance(story_points, int) and isinstance(rationale, str) and rationale.strip():
                return (story_points, rationale.strip())
    return None


def _extract_rationale_from_text(candidates: list[str | None]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if lowered.startswith("reason:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    return None


def _extract_normalized_estimate(*, metadata: dict[str, object]) -> dict[str, object] | None:
    estimate = metadata.get("estimate")
    if not isinstance(estimate, dict):
        return None
    story_points = estimate.get("story_points")
    rationale = estimate.get("rationale")
    if not isinstance(story_points, int) or not isinstance(rationale, str) or not rationale.strip():
        return None
    return {
        "story_points": story_points,
        "can_take_in_work": story_points <= 2,
        "rationale": rationale.strip(),
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "task"


def _dump_result_payload(payload: TaskResultPayload) -> dict[str, object]:
    return payload.model_dump(mode="json")


def _task_logger(task: Task, **fields: Any):
    log_fields = {
        "task_id": task.id,
        "root_task_id": task.root_id or task.id,
        "parent_id": task.parent_id,
        "task_type": task.task_type.value,
        "task_status": task.status.value,
        "tracker_name": task.tracker_name,
        "tracker_external_id": task.external_task_id,
        "tracker_parent_external_id": task.external_parent_id,
        "workspace_key": task.workspace_key,
        "branch_name": task.branch_name,
        "pr_external_id": task.pr_external_id,
        "pr_url": task.pr_url,
    }
    log_fields.update(fields)
    return get_logger(__name__, component="worker2").bind(**log_fields)


__all__ = [
    "ExecuteWorker",
    "ExecuteWorkerReport",
    "build_execute_worker",
    "run",
]
