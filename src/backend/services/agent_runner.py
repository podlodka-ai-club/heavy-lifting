from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.schemas import TaskContext, TaskResultPayload, TokenUsagePayload
from backend.services.token_costs import TokenCostService
from backend.task_constants import TaskType
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class CliAgentRunnerConfig:
    command: str
    subcommand: str
    timeout_seconds: int
    provider_hint: str | None = None
    model_hint: str | None = None
    profile: str | None = None
    api_key_env_var: str | None = None
    base_url_env_var: str | None = None


@dataclass(slots=True)
class LocalAgentRunner:
    token_cost_service: TokenCostService = field(default_factory=TokenCostService)
    provider: str = "openai"
    model: str = "gpt-5.4"
    name: str = "local-placeholder-runner"

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        usage = self.token_cost_service.with_estimated_cost(self._build_token_usage(request))
        metadata = self._build_summary_metadata(request=request, usage=usage)
        payload = TaskResultPayload(
            summary=self._build_summary(request.task_context),
            details=self._build_details(request.task_context, request.workspace_path),
            branch_name=request.task_context.branch_name,
            pr_url=request.task_context.pr_url,
            token_usage=[usage],
            metadata=metadata,
        )
        return AgentRunResult(payload=payload)

    def _build_token_usage(self, request: AgentRunRequest) -> TokenUsagePayload:
        instruction_text = request.task_context.instructions or ""
        tracker_title = (
            request.task_context.tracker_context.title
            if request.task_context.tracker_context
            else ""
        )
        execution_title = (
            request.task_context.execution_context.title
            if request.task_context.execution_context
            else ""
        )
        feedback_body = (
            request.task_context.current_feedback.body
            if request.task_context.current_feedback
            else ""
        )
        history_size = sum(
            len(entry.feedback.body) for entry in request.task_context.feedback_history
        )
        input_size = (
            len(instruction_text) + len(tracker_title) + len(execution_title) + len(feedback_body)
        )
        input_tokens = max(1, (input_size + history_size) // 4)

        output_tokens = 120 if request.task_context.flow_type == TaskType.EXECUTE else 80
        cached_tokens = history_size // 4
        return TokenUsagePayload(
            model=self.model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )

    def _build_summary(self, context: EffectiveTaskContext) -> str:
        execution_title = context.execution_context.title if context.execution_context else "task"
        if context.flow_type == TaskType.PR_FEEDBACK and context.current_feedback is not None:
            comment_id = context.current_feedback.comment_id
            return f"Prepared follow-up response for review comment {comment_id}."
        if context.flow_type == TaskType.EXECUTE:
            return f"Prepared local agent execution for {execution_title}."
        return f"Prepared local agent result for {execution_title}."

    def _build_details(self, context: EffectiveTaskContext, workspace_path: str) -> str:
        details = [f"Workspace: {workspace_path}", f"Flow: {context.flow_type.value}"]
        if context.instructions:
            details.append(f"Instructions: {context.instructions}")
        if context.current_feedback is not None:
            details.append(f"Feedback: {context.current_feedback.body}")
        return "\n".join(details)

    def _build_summary_metadata(
        self,
        *,
        request: AgentRunRequest,
        usage: TokenUsagePayload,
    ) -> dict[str, object]:
        total_cost = self.token_cost_service.total_estimated_cost([usage])
        return {
            "runner_adapter": "local",
            "runner": self.name,
            "mode": "placeholder",
            "provider": self.provider,
            "model": self.model,
            "flow_type": request.task_context.flow_type.value,
            "workspace_path": request.workspace_path,
            "has_feedback": request.task_context.current_feedback is not None,
            "feedback_history_count": len(request.task_context.feedback_history),
            "estimated_cost_usd": str(total_cost),
        }


@dataclass(slots=True)
class CliAgentRunner:
    config: CliAgentRunnerConfig

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        prompt = self._build_prompt(request)
        command = self._build_command(request=request, prompt=prompt)
        completed_process = subprocess.run(
            command,
            cwd=request.workspace_path,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
        )
        payload = self._build_payload(
            request=request,
            command=command,
            completed_process=completed_process,
        )
        return AgentRunResult(payload=payload)

    def _build_command(self, *, request: AgentRunRequest, prompt: str) -> list[str]:
        command = [self.config.command, self.config.subcommand, "--dir", request.workspace_path]

        model = self._resolve_model()
        if model is not None:
            command.extend(["--model", model])

        command.append(prompt)
        return command

    def _resolve_model(self) -> str | None:
        if self.config.provider_hint and self.config.model_hint:
            return f"{self.config.provider_hint}/{self.config.model_hint}"
        if self.config.model_hint:
            return self.config.model_hint
        return None

    def _build_prompt(self, request: AgentRunRequest) -> str:
        context = request.task_context
        parts = [
            f"workspace_path: {request.workspace_path}",
            f"flow_type: {context.flow_type.value}",
        ]

        if context.repo_url:
            parts.append(f"repo_url: {context.repo_url}")
        if context.repo_ref:
            parts.append(f"repo_ref: {context.repo_ref}")
        if context.branch_name:
            parts.append(f"branch_name: {context.branch_name}")
        if context.base_branch:
            parts.append(f"base_branch: {context.base_branch}")
        if context.instructions:
            parts.extend(["instructions:", context.instructions])

        tracker_context = context.tracker_context
        if tracker_context is not None:
            parts.extend(self._render_context_block("tracker_context", tracker_context))

        execution_context = context.execution_context
        if execution_context is not None:
            parts.extend(self._render_context_block("execution_context", execution_context))

        if context.current_feedback is not None:
            parts.extend(
                [
                    "current_feedback:",
                    f"comment_id: {context.current_feedback.comment_id}",
                    f"body: {context.current_feedback.body}",
                ]
            )

        if context.feedback_history:
            parts.append(f"feedback_history_count: {len(context.feedback_history)}")
            for index, entry in enumerate(context.feedback_history, start=1):
                parts.extend(
                    [
                        f"feedback_history[{index}].comment_id: {entry.feedback.comment_id}",
                        f"feedback_history[{index}].body: {entry.feedback.body}",
                    ]
                )

        return "\n".join(parts)

    def _render_context_block(self, label: str, context: TaskContext) -> list[str]:
        lines = [f"{label}:"]
        title = context.title
        lines.append(f"title: {title}")

        description = context.description
        if description:
            lines.append(f"description: {description}")

        acceptance_criteria = context.acceptance_criteria
        if acceptance_criteria:
            lines.append("acceptance_criteria:")
            lines.extend(f"- {criterion}" for criterion in acceptance_criteria)

        return lines

    def _build_payload(
        self,
        *,
        request: AgentRunRequest,
        command: list[str],
        completed_process: subprocess.CompletedProcess[str],
    ) -> TaskResultPayload:
        exit_code = completed_process.returncode
        stdout_preview = self._build_preview(completed_process.stdout)
        stderr_preview = self._build_preview(completed_process.stderr)
        details = self._build_details(stdout_preview=stdout_preview, stderr_preview=stderr_preview)
        runner_metadata: dict[str, object] = {
            "subcommand": self.config.subcommand,
            "profile": self.config.profile,
            "provider_hint": self.config.provider_hint,
            "model_hint": self.config.model_hint,
            "model_argument": self._resolve_model(),
            "api_key_env_var": self.config.api_key_env_var,
            "base_url_env_var": self.config.base_url_env_var,
        }
        metadata: dict[str, object] = {
            "runner_adapter": "cli",
            "runner": self.config.command,
            "flow_type": request.task_context.flow_type.value,
            "workspace_path": request.workspace_path,
            "request_metadata": dict(request.metadata),
            "command": command,
            "exit_code": exit_code,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "runner_metadata": runner_metadata,
        }
        return TaskResultPayload(
            summary=self._build_summary(exit_code),
            details=details,
            branch_name=request.task_context.branch_name,
            pr_url=request.task_context.pr_url,
            metadata=metadata,
        )

    def _build_summary(self, exit_code: int) -> str:
        if exit_code == 0:
            return "CLI agent run completed successfully."
        return f"CLI agent run failed with exit code {exit_code}."

    def _build_details(
        self, *, stdout_preview: str | None, stderr_preview: str | None
    ) -> str | None:
        details: list[str] = []
        if stdout_preview:
            details.extend(["stdout:", stdout_preview])
        if stderr_preview:
            details.extend(["stderr:", stderr_preview])
        if not details:
            return None
        return "\n".join(details)

    def _build_preview(self, value: str | None, limit: int = 1000) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."


__all__ = ["CliAgentRunner", "CliAgentRunnerConfig", "LocalAgentRunner"]
