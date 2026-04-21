from __future__ import annotations

from dataclasses import dataclass, field

from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.schemas import TaskResultPayload, TokenUsagePayload
from backend.services.token_costs import TokenCostService
from backend.task_constants import TaskType
from backend.task_context import EffectiveTaskContext


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
            "runner": self.name,
            "mode": "placeholder",
            "flow_type": request.task_context.flow_type.value,
            "workspace_path": request.workspace_path,
            "has_feedback": request.task_context.current_feedback is not None,
            "feedback_history_count": len(request.task_context.feedback_history),
            "estimated_cost_usd": str(total_cost),
        }


__all__ = ["LocalAgentRunner"]
