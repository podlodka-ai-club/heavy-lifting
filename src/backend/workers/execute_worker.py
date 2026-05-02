from __future__ import annotations

import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory, session_scope
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
    TaskHandoffPayload,
    TaskInputPayload,
    TaskLink,
    TaskResultPayload,
    TokenUsagePayload,
)
from backend.services.context_builder import ContextBuilder, parse_task_result_payload
from backend.services.retro_service import RetroService
from backend.services.triage_step import (
    TriageStep,
    TriageStepError,
    TriageStepResult,
    load_triage_prompt,
)
from backend.settings import Settings, get_settings
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
    branch_name: str | None
    runtime_metadata: dict[str, object]
    skip_scm_artifacts: bool = False


@dataclass(frozen=True, slots=True)
class PreparedTriageExecution:
    """Prepared input для TriageStep.run (см. task05).

    Отличия от PreparedExecution:

    - ``workspace_path`` всегда строка (либо клон репо, либо пустой
      tmp-каталог) — соответствует обязательному
      :attr:`AgentRunRequest.workspace_path`;
    - ``workspace`` может быть ``None``, если ``task_context.workspace_key``
      пуст (без workspace_key SCM не сможет подготовить чекаут — даже если
      ``repo_url`` известен);
    - ``cleanup_paths`` — каталоги, которые caller (task06) обязан удалить
      после ``agent_runner.run`` (актуально только для tmp-fallback).
      ``_prepare_triage_execution`` сам ``shutil.rmtree`` **не** вызывает,
      потому что lifecycle привязан к моменту завершения agent run.
    """

    task_context: EffectiveTaskContext
    workspace_path: str
    runtime_metadata: dict[str, object]
    workspace: ScmWorkspace | None = None
    cleanup_paths: tuple[Path, ...] = ()


@dataclass(slots=True)
class ExecuteWorker:
    scm: ScmProtocol
    agent_runner: AgentRunnerProtocol
    session_factory: sessionmaker[Session]
    poll_interval: int = 30
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    settings: Settings = field(default_factory=get_settings)
    _triage_prompt_text: str | None = field(default=None, init=False, repr=False)

    def _get_triage_prompt_text(self) -> str:
        if self._triage_prompt_text is None:
            self._triage_prompt_text = load_triage_prompt(Path(self.settings.prompts_dir))
        return self._triage_prompt_text

    def poll_once(self) -> ExecuteWorkerReport:
        batch_size = self._read_execute_batch_size()
        report = ExecuteWorkerReport()
        for _ in range(batch_size):
            report = _merge_reports(report, self._process_next_task(TaskType.EXECUTE))
        report = _merge_reports(report, self._process_next_task(TaskType.PR_FEEDBACK))
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

                if task_type == TaskType.EXECUTE:
                    action = self._resolve_execute_action(task=task)
                else:
                    action = "implementation"  # PR_FEEDBACK всегда impl-flow

                if action == "triage":
                    return self._process_triage_execute(
                        repository=repository,
                        task=task,
                        task_chain=task_chain,
                    )

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
                    return ExecuteWorkerReport(failed_pr_feedback_tasks=1)
                if prepared_execution.skip_scm_artifacts:
                    self._complete_execute_task_without_scm(
                        repository=repository,
                        task=task,
                        task_context=prepared_execution.task_context,
                        agent_payload=run_result.payload,
                    )
                    return ExecuteWorkerReport(processed_execute_tasks=1)

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
                return ExecuteWorkerReport(failed_pr_feedback_tasks=1)

    def _resolve_execute_action(self, *, task: Task) -> str:
        """Determine which agent flow handles this execute-task.

        Resolution order:

        1. **Explicit** — ``task.input_payload["action"]`` if it is a non-empty
           string. ``tracker_intake`` (task08) проставляет ``action="triage"``
           новой execute явно, а ``TriageStep`` через task07 будет создавать
           sibling-impl-execute с ``action="implementation"``.
        2. **Default** — ``"implementation"``. Это сохраняет старое
           impl-flow поведение для legacy execute-задач без action: до
           миграции worker всегда шёл по impl-пути, и любая уже
           существующая в БД single-execute-задача должна остаться там же.
           Триаж назначается **только** через явный ``action="triage"``,
           который сегодня выставляет лишь ``tracker_intake`` для новых
           кластеров.

        Возвращает строку (``"triage"``, ``"implementation"``, ...) — caller
        проверяет конкретное значение.
        """

        raw_input = task.input_payload if isinstance(task.input_payload, dict) else None
        explicit_action = raw_input.get("action") if raw_input else None
        if isinstance(explicit_action, str) and explicit_action:
            return explicit_action
        return "implementation"

    def _process_triage_execute(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_chain: list[Task],
    ) -> ExecuteWorkerReport:
        logger = _task_logger(task, attempt=task.attempt, action="triage")

        prepared = self._prepare_triage_execution(
            repository=repository,
            task=task,
            task_chain=task_chain,
        )

        triage_step = TriageStep(
            agent_runner=self.agent_runner,
            triage_prompt_text=self._get_triage_prompt_text(),
        )

        try:
            try:
                triage_result = triage_step.run(
                    task_context=prepared.task_context,
                    workspace_path=prepared.workspace_path,
                    runtime_metadata=prepared.runtime_metadata,
                )
            except TriageStepError as exc:
                self._handle_triage_step_error(task=task, exc=exc)
                logger.warning("triage_output_malformed", error=str(exc))
                return ExecuteWorkerReport(failed_execute_tasks=1)

            self._complete_triage_execute_task(
                repository=repository,
                task=task,
                task_context=prepared.task_context,
                triage_result=triage_result,
            )
            logger.info(
                "triage_execute_task_completed",
                triage_outcome=triage_result.result_payload.outcome,
                triage_sp=triage_result.decision.story_points,
            )
            return ExecuteWorkerReport(processed_execute_tasks=1)
        finally:
            self._cleanup_triage_workspace(prepared.cleanup_paths)

    def _handle_triage_step_error(self, *, task: Task, exc: TriageStepError) -> None:
        raw_stdout = exc.raw_stdout if isinstance(exc.raw_stdout, str) else ""
        truncated = raw_stdout[:2000]
        failure_payload = TaskResultPayload(
            summary="Triage agent output malformed.",
            metadata={"raw_stdout_preview": truncated},
        )
        self._mark_task_failed(
            task=task,
            error="triage_output_malformed",
            result_payload=failure_payload,
            branch_name=None,
        )

    def _complete_triage_execute_task(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_context: EffectiveTaskContext,
        triage_result: TriageStepResult,
    ) -> None:
        result_payload = triage_result.result_payload
        self._mark_task_done(
            task=task,
            result_payload=result_payload,
            branch_name=None,
            pr_external_id=None,
            pr_url=None,
        )
        self._record_token_usage(
            repository=repository,
            task_id=task.id,
            usage=result_payload.token_usage,
        )
        self._record_agent_retro_feedback(
            repository=repository,
            task=task,
            result_payload=result_payload,
        )
        self._ensure_followup_implementation_execute(
            repository=repository,
            triage_task=task,
            result_payload=result_payload,
        )
        self._ensure_deliver_task(
            repository=repository,
            execute_task=task,
            task_context=task_context,
        )

    def _ensure_followup_implementation_execute(
        self,
        *,
        repository: TaskRepository,
        triage_task: Task,
        result_payload: TaskResultPayload,
    ) -> Task | None:
        """Materialise sibling implementation-execute after a successful triage.

        Sibling-модель: создаваемая задача — **не** дочка триажа, а **сиблинг**
        под тем же fetch-родителем (``parent_id=triage_task.parent_id``).
        Это требование плана §5.4 + §6.4 п.2 и поддерживается
        ``ContextBuilder._find_relevant_execute_for_current`` (task16),
        которая в lineage deliver/PR_FEEDBACK выбирает «последний execute»
        в parent-chain — что для sibling-impl как раз impl, а не triage.

        Создание выполняется только когда:

        - ``result_payload.routing`` существует и
          ``create_followup_task is True`` и ``next_task_type == "execute"``
          (это SP 1/2/3 — план §5.2);
        - в кластере root_id ещё нет execute-задачи с ``input_payload.action
          == "implementation"`` (idempotency через
          ``repository.find_implementation_execute_for_root``).

        Возвращает созданную задачу, либо ``None`` — если sibling не
        создавался (эскалация SP 5/8/13 или idempotency-skip).
        """

        routing = result_payload.routing
        if (
            routing is None
            or not routing.create_followup_task
            or routing.next_task_type != "execute"
        ):
            return None

        # Fail-loud BEFORE idempotency lookup: orphan-triage (parent_id is None)
        # нарушает инвариант tracker_intake и не должен тихо проскакивать через
        # idempotency-skip, даже если под тем же root_id уже есть impl-execute
        # (см. AC10 task07.md + Codex review round1 P1).
        if triage_task.parent_id is None:
            raise RuntimeError(
                "triage execute-task must have a fetch parent before sibling "
                "impl-execute can be created"
            )

        root_id = triage_task.root_id or triage_task.id
        existing = repository.find_implementation_execute_for_root(root_id)
        if existing is not None:
            _task_logger(
                triage_task,
                sibling_execute_task_id=existing.id,
            ).info("sibling_implementation_execute_skipped_idempotent")
            return None

        brief_markdown = self._extract_handover_brief(result_payload=result_payload)

        input_payload_model = TaskInputPayload(
            schema_version=1,
            action="implementation",
            handoff=TaskHandoffPayload(
                from_task_id=triage_task.id,
                from_role="triage",
                brief_markdown=brief_markdown,
            ),
        )

        sibling = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=triage_task.parent_id,  # fetch-задача
                status=TaskStatus.NEW,
                tracker_name=triage_task.tracker_name,
                external_parent_id=triage_task.external_parent_id,
                repo_url=triage_task.repo_url,
                repo_ref=triage_task.repo_ref,
                workspace_key=triage_task.workspace_key,
                context=triage_task.context,
                input_payload=input_payload_model.model_dump(mode="python"),
            )
        )
        _task_logger(
            triage_task,
            sibling_execute_task_id=sibling.id,
            handover_brief_present=brief_markdown is not None,
        ).info("sibling_implementation_execute_created")
        return sibling

    @staticmethod
    def _extract_handover_brief(*, result_payload: TaskResultPayload) -> str | None:
        raw = result_payload.metadata.get("handover_brief")
        if isinstance(raw, str) and raw.strip():
            return raw
        return None

    def _cleanup_triage_workspace(self, paths: tuple[Path, ...]) -> None:
        if not paths:
            return
        for path in paths:
            shutil.rmtree(path, ignore_errors=True)

    def _prepare_execution(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_chain: list[Task],
    ) -> PreparedExecution:
        brief_resolver = self._build_brief_resolver(repository=repository)
        task_context = self.context_builder.build_for_task(
            task=task,
            task_chain=task_chain,
            brief_resolver=brief_resolver,
        )
        skip_scm_artifacts = self._should_skip_scm_artifacts(task_context=task_context)
        workspace = self._ensure_workspace(task_context=task_context)
        repository.update_task_workspace_context(
            task.id,
            repo_url=workspace.repo_url,
            repo_ref=workspace.repo_ref,
            workspace_key=workspace.workspace_key,
        )
        branch_name = None
        if not skip_scm_artifacts:
            branch_name = self._sync_branch(
                task=task, task_context=task_context, workspace=workspace
            )
        runtime_metadata: dict[str, object] = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "workspace_key": workspace.workspace_key,
            "workspace_path": workspace.local_path,
            "branch_name": branch_name,
            "repo_url": workspace.repo_url,
            "repo_ref": workspace.repo_ref,
        }
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
            runtime_metadata=runtime_metadata,
            skip_scm_artifacts=skip_scm_artifacts,
        )

    def _prepare_triage_execution(
        self,
        *,
        repository: TaskRepository,
        task: Task,
        task_chain: list[Task],
    ) -> PreparedTriageExecution:
        """Lightweight prepare for the triage agent (no ``_ensure_workspace``).

        Triage by contract is allowed to run without a backing repo: when
        ``workspace_key`` is missing in the lineage, we materialise an empty tmp
        directory under
        ``settings.workspace_root / "__triage__" / f"task-{task.id}"`` so that
        :attr:`AgentRunRequest.workspace_path` is always satisfied. The directory
        is created idempotently (``mkdir(parents=True, exist_ok=True)``) and
        returned via ``cleanup_paths`` so the caller can ``rmtree`` it after the
        agent run.

        When ``workspace_key`` is present but ``repo_url`` / ``repo_ref`` are
        empty (e.g. installations where ``GitHubScm.ensure_workspace`` resolves
        the URL via ``default_repo_url``), we still go through the SCM path —
        the resolved fields are written back both to the DB row and to the
        returned ``task_context``, so ``TriageStep.build_prompt`` sees the
        canonical repo signals.
        """

        brief_resolver = self._build_brief_resolver(repository=repository)
        task_context = self.context_builder.build_for_task(
            task=task,
            task_chain=task_chain,
            brief_resolver=brief_resolver,
        )

        # Наличие ``workspace_key`` — единственный устойчивый сигнал «backend
        # готов выдать workspace»: ``_ensure_workspace`` raise'ит только если
        # ``workspace_key`` пуст, тогда как ``repo_url`` SCM-адаптер волен
        # дорезолвить через ``default_repo_url`` (см. GitHubScm). Поэтому не
        # уводим триаж в tmp-каталог только из-за пустого ``repo_url``.
        has_repo = bool(task_context.workspace_key)

        workspace: ScmWorkspace | None
        cleanup_paths: tuple[Path, ...]
        if has_repo:
            workspace = self._ensure_workspace(task_context=task_context)
            repository.update_task_workspace_context(
                task.id,
                repo_url=workspace.repo_url,
                repo_ref=workspace.repo_ref,
                workspace_key=workspace.workspace_key,
            )
            # SCM мог дорезолвить repo_url / repo_ref (default_repo_url /
            # default_repo_ref) — пробрасываем канонные значения в task_context,
            # чтобы TriageStep.build_prompt видел свежие repo signals.
            task_context = replace(
                task_context,
                repo_url=workspace.repo_url,
                repo_ref=workspace.repo_ref,
                workspace_key=workspace.workspace_key,
            )
            workspace_path = workspace.local_path
            cleanup_paths = ()
        else:
            tmp_dir = Path(self.settings.workspace_root) / "__triage__" / f"task-{task.id}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            workspace = None
            workspace_path = str(tmp_dir)
            cleanup_paths = (tmp_dir,)

        runtime_metadata: dict[str, object] = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "action": "triage",
            "workspace_path": workspace_path,
            "workspace_key": workspace.workspace_key if workspace is not None else None,
            "repo_url": workspace.repo_url if workspace is not None else None,
            "repo_ref": workspace.repo_ref if workspace is not None else None,
            "branch_name": None,
            "repo_available": has_repo,
        }
        _task_logger(
            task,
            workspace_path=workspace_path,
            repo_available=has_repo,
            action="triage",
        ).info("triage_workspace_prepared")
        return PreparedTriageExecution(
            task_context=task_context,
            workspace_path=workspace_path,
            runtime_metadata=runtime_metadata,
            workspace=workspace,
            cleanup_paths=cleanup_paths,
        )

    def _build_brief_resolver(
        self, *, repository: TaskRepository
    ) -> Callable[[int], str | None]:
        def _resolve_handover_brief(from_task_id: int) -> str | None:
            triage_task = repository.get_task(from_task_id)
            if triage_task is None:
                return None
            payload = parse_task_result_payload(triage_task)
            if payload is None:
                return None
            raw = payload.metadata.get("handover_brief")
            if isinstance(raw, str) and raw.strip():
                return raw
            return None

        return _resolve_handover_brief

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

        execution_title = (
            task_context.execution_context.title
            if task_context.execution_context is not None
            else "execution result"
        )
        deliver_task = repository.create_task(
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
        self, *, agent_payload: TaskResultPayload
    ) -> TaskResultPayload:
        metadata = dict(agent_payload.metadata)
        metadata["delivery_mode"] = "estimate_only"
        tracker_comment = self._build_delivery_only_comment(agent_payload=agent_payload)
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
        stdout_preview = agent_payload.metadata.get("stdout_preview")
        if isinstance(stdout_preview, str) and stdout_preview.strip():
            return stdout_preview.strip()
        if agent_payload.tracker_comment:
            return agent_payload.tracker_comment
        if agent_payload.details:
            details = agent_payload.details.strip()
            if details.startswith("stdout:\n"):
                return details.removeprefix("stdout:\n").strip()
            return details
        return agent_payload.summary

    def _should_skip_scm_artifacts(self, *, task_context: EffectiveTaskContext) -> bool:
        if task_context.flow_type != TaskType.EXECUTE:
            return False

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
        return f"{self.settings.scm_branch_prefix}{slug}"

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
