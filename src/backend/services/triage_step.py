"""Triage orchestration step.

Pure step (no DB / no I/O beyond the agent runner): builds the triage prompt
from an :class:`EffectiveTaskContext`, invokes the supplied agent runner, parses
its raw stdout via :func:`parse_triage_output`, and materialises the resulting
:class:`TriageDecision` into a :class:`TaskResultPayload` according to the
SP→action matrix described in ``temp/plans/triage-story-point-agent.md`` §5.2 /
§6.4.

Caller (``ExecuteWorker`` in task06) is responsible for persisting the payload
to the DB, creating the deliver-task and — for SP 1/2/3 — the sibling
implementation execute. ``TriageStep`` itself is intentionally stateless.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from backend.protocols.agent_runner import (
    AgentRunnerProtocol,
    AgentRunRequest,
    AgentRunResult,
)
from backend.schemas import (
    TaskClassificationPayload,
    TaskDeliveryPayload,
    TaskEstimatePayload,
    TaskResultPayload,
    TaskRoutingPayload,
)
from backend.services.triage_parser import (
    TriageDecision,
    TriageOutputError,
    parse_triage_output,
)
from backend.task_context import EffectiveTaskContext

__all__ = [
    "TriageStep",
    "TriageStepError",
    "TriageStepResult",
    "load_triage_prompt",
]


# Story Point → tracker labels (mirror plan §5.2 lines 109–124).
_SP_TO_LABELS: Final[dict[int, list[str]]] = {
    1: ["sp:1", "triage:ready"],
    2: ["sp:2", "triage:ready"],
    3: ["sp:3", "triage:ready"],
    5: ["sp:5", "triage:rfi"],
    8: ["sp:8", "triage:split"],
    13: ["sp:13", "triage:block"],
}

# Story Point → estimate.complexity (mirror TaskEstimatePayload Literal).
_SP_TO_COMPLEXITY: Final[dict[int, str]] = {
    1: "trivial",
    2: "low",
    3: "medium",
    5: "high",
    8: "epic",
    13: "architectural",
}

# Story Point → escalation_kind (None for SP 1/2/3).
_SP_TO_ESCALATION: Final[dict[int, str | None]] = {
    1: None,
    2: None,
    3: None,
    5: "rfi",
    8: "decomposition",
    13: "system_design",
}

_SP_BRIEF: Final[frozenset[int]] = frozenset({1, 2, 3})

_SP_TO_SUMMARY: Final[dict[int, str]] = {
    1: "Triage завершён: SP=1, routed to implementer.",
    2: "Triage завершён: SP=2, routed to implementer.",
    3: "Triage завершён: SP=3, routed to implementer.",
    5: "Triage SP=5: запрос дополнительной информации.",
    8: "Triage SP=8: задача требует декомпозиции.",
    13: "Triage SP=13: требуется архитектурное решение.",
}

_SP_TO_BLOCKING_REASONS: Final[dict[int, list[str]]] = {
    1: [],
    2: [],
    3: [],
    5: ["information_deficit"],
    8: ["scope_too_large"],
    13: ["architectural_ambiguity"],
}


@dataclass(frozen=True, slots=True)
class TriageStepResult:
    """Outcome of a single triage-step run.

    Carried up to :class:`ExecuteWorker` (task06), which writes the payload to
    the DB, creates the deliver-task and (for SP 1/2/3) the sibling
    implementation execute.
    """

    decision: TriageDecision
    result_payload: TaskResultPayload
    agent_run_result: AgentRunResult


class TriageStepError(RuntimeError):
    """Raised when the triage agent output cannot be turned into a decision.

    Carries ``raw_stdout`` so the caller
    (``ExecuteWorker._handle_triage_step_error``) can persist a truncated
    preview into ``task.result_payload.metadata`` for downstream debugging.
    """

    def __init__(self, message: str, *, raw_stdout: str = "") -> None:
        super().__init__(message)
        self.raw_stdout = raw_stdout


@dataclass(slots=True)
class TriageStep:
    """Pure orchestration node for the triage agent.

    Holds an :class:`AgentRunnerProtocol` and the loaded triage prompt text.
    The caller injects an already-loaded prompt so unit tests can substitute a
    short fixture instead of round-tripping through the filesystem.
    """

    agent_runner: AgentRunnerProtocol
    triage_prompt_text: str
    name: str = "triage-step"

    def run(
        self,
        *,
        task_context: EffectiveTaskContext,
        workspace_path: str,
        runtime_metadata: dict[str, object] | None = None,
    ) -> TriageStepResult:
        """Run the triage agent and materialise the structured payload.

        Raises
        ------
        TriageStepError
            If the agent stdout violates the contract enforced by
            :func:`parse_triage_output`.
        """

        prompt = self.build_prompt(task_context=task_context)
        request = AgentRunRequest(
            task_context=task_context,
            workspace_path=workspace_path,
            metadata=dict(runtime_metadata or {}),
            prompt_override=prompt,
        )
        agent_result = self.agent_runner.run(request)
        triage_raw_output = agent_result.parsed_stdout or agent_result.raw_stdout

        try:
            decision = parse_triage_output(triage_raw_output)
        except TriageOutputError as exc:
            raise TriageStepError(
                f"triage_output_malformed: {exc}",
                raw_stdout=agent_result.raw_stdout,
            ) from exc

        result_payload = self._build_result_payload(
            decision=decision,
            agent_result=agent_result,
        )
        return TriageStepResult(
            decision=decision,
            result_payload=result_payload,
            agent_run_result=agent_result,
        )

    def build_prompt(self, *, task_context: EffectiveTaskContext) -> str:
        """Render the prompt fed to the triage agent.

        The prompt is composed of four XML-ish blocks consumed by the agent
        per ``prompts/agents/triage.md``:

        * ``<role>`` — the verbatim contents of ``prompts/agents/triage.md``;
        * ``<task_context>`` — title / description / acceptance criteria
          taken from :attr:`EffectiveTaskContext.tracker_context`;
        * ``<repo_signals>`` — repo URL / ref / workspace key plus a
          ``repo_available`` boolean flag;
        * ``<expected_output>`` — short reminder of the two-block contract.
        """

        lines: list[str] = ["<role>", self.triage_prompt_text.rstrip(), "</role>", ""]
        lines.extend(self._render_task_context_block(task_context))
        lines.append("")
        lines.extend(self._render_repo_signals_block(task_context))
        lines.append("")
        lines.extend(
            [
                "<expected_output>",
                "- machine: <triage_result> блок с story_points/task_kind/outcome",
                "- human: <markdown> блок с одним из четырёх шаблонов на русском",
                "</expected_output>",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Prompt rendering helpers
    # ------------------------------------------------------------------

    def _render_task_context_block(self, task_context: EffectiveTaskContext) -> list[str]:
        tracker_context = task_context.tracker_context
        lines: list[str] = ["<task_context>"]
        if tracker_context is not None:
            lines.append(f"title: {tracker_context.title}")
            description = tracker_context.description
            if description:
                lines.append(f"description: {description}")
            else:
                lines.append("description:")
            acceptance_criteria = tracker_context.acceptance_criteria
            if acceptance_criteria:
                lines.append("acceptance_criteria:")
                lines.extend(f"- {criterion}" for criterion in acceptance_criteria)
            else:
                lines.append("acceptance_criteria:")
        else:
            lines.append("title:")
            lines.append("description:")
            lines.append("acceptance_criteria:")
        lines.append("</task_context>")
        return lines

    def _render_repo_signals_block(self, task_context: EffectiveTaskContext) -> list[str]:
        repo_url = task_context.repo_url or ""
        repo_ref = task_context.repo_ref or ""
        workspace_key = task_context.workspace_key or ""
        repo_available = bool(repo_url and repo_ref and workspace_key)
        return [
            "<repo_signals>",
            f"repo_url: {repo_url}",
            f"repo_ref: {repo_ref}",
            f"workspace_key: {workspace_key}",
            f"repo_available: {'true' if repo_available else 'false'}",
            "</repo_signals>",
        ]

    # ------------------------------------------------------------------
    # Decision → TaskResultPayload
    # ------------------------------------------------------------------

    def _build_result_payload(
        self,
        *,
        decision: TriageDecision,
        agent_result: AgentRunResult,
    ) -> TaskResultPayload:
        sp = int(decision.story_points)

        classification = TaskClassificationPayload(
            task_kind=decision.task_kind,
        )

        estimate = TaskEstimatePayload(
            story_points=decision.story_points,
            complexity=_SP_TO_COMPLEXITY[sp],  # type: ignore[arg-type]
            can_take_in_work=sp in _SP_BRIEF,
            blocking_reasons=list(_SP_TO_BLOCKING_REASONS[sp]),
        )

        if sp in _SP_BRIEF:
            routing = TaskRoutingPayload(
                next_task_type="execute",
                next_role="implementation",
                create_followup_task=True,
                requires_human_approval=False,
            )
        else:
            routing = TaskRoutingPayload(
                next_task_type="deliver",
                next_role="deliver",
                create_followup_task=False,
                requires_human_approval=True,
            )

        escalation_kind = _SP_TO_ESCALATION[sp]
        if sp in _SP_BRIEF:
            comment_body: str | None = (
                f"Triage SP={sp}: Brief сохранён, передано в работу."
            )
        else:
            comment_body = decision.comment_markdown

        delivery = TaskDeliveryPayload(
            tracker_status=None,
            tracker_estimate=decision.story_points,
            tracker_labels=list(_SP_TO_LABELS[sp]),
            escalation_kind=escalation_kind,  # type: ignore[arg-type]
            comment_body=comment_body,
        )

        metadata: dict[str, object] = {}
        tracker_comment: str | None = None
        if sp in _SP_BRIEF:
            if decision.brief_markdown is not None:
                metadata["handover_brief"] = decision.brief_markdown
        else:
            if decision.comment_markdown is not None:
                tracker_comment = decision.comment_markdown

        return TaskResultPayload(
            outcome=decision.outcome,
            classification=classification,
            estimate=estimate,
            routing=routing,
            delivery=delivery,
            summary=_SP_TO_SUMMARY[sp],
            tracker_comment=tracker_comment,
            token_usage=list(agent_result.payload.token_usage),
            metadata=metadata,
        )


def load_triage_prompt(prompts_dir: Path) -> str:
    """Read ``<prompts_dir>/agents/triage.md`` from disk.

    Caller (typically the worker composition layer in task06) is responsible
    for choosing ``prompts_dir`` — usually the repository-relative
    ``prompts`` directory or a settings-driven path.
    """

    return (prompts_dir / "agents" / "triage.md").read_text(encoding="utf-8")
