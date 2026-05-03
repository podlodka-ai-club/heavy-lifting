from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.schemas import TaskResultPayload, TokenUsagePayload
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    task_context: EffectiveTaskContext
    workspace_path: str
    metadata: dict[str, object] = field(default_factory=dict)
    prompt_override: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    payload: TaskResultPayload
    raw_stdout: str = ""
    raw_stderr: str = ""

    @property
    def token_usage(self) -> tuple[TokenUsagePayload, ...]:
        return tuple(self.payload.token_usage)

    @property
    def summary_metadata(self) -> dict[str, object]:
        return dict(self.payload.metadata)

    @property
    def execution_failed(self) -> bool:
        status = self.payload.metadata.get("execution_status")
        return status == "failed"

    @property
    def failure_message(self) -> str | None:
        if not self.execution_failed:
            return None

        failure_message = self.payload.metadata.get("failure_message")
        if isinstance(failure_message, str) and failure_message.strip():
            return failure_message
        return self.payload.summary


@runtime_checkable
class AgentRunnerProtocol(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


__all__ = ["AgentRunRequest", "AgentRunResult", "AgentRunnerProtocol"]
