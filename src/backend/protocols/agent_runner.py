from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.schemas import TaskResultPayload, TokenUsagePayload
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    task_context: EffectiveTaskContext
    workspace_path: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    payload: TaskResultPayload

    @property
    def token_usage(self) -> tuple[TokenUsagePayload, ...]:
        return tuple(self.payload.token_usage)

    @property
    def summary_metadata(self) -> dict[str, object]:
        return dict(self.payload.metadata)


@runtime_checkable
class AgentRunnerProtocol(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


__all__ = ["AgentRunRequest", "AgentRunResult", "AgentRunnerProtocol"]
