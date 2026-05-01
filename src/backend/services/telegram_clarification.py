from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.schemas import TaskContext, TaskInputPayload, TaskResultPayload
from backend.task_context import EffectiveTaskContext

TELEGRAM_CLARIFICATION_ROLE = "telegram_clarification"

_CONFIRMATION_WORDS = frozenset(
    {
        "да",
        "ок",
        "окей",
        "готово",
        "фиксируй",
        "fix",
        "yes",
        "confirm",
        "confirmed",
    }
)


@dataclass(frozen=True, slots=True)
class ClarificationSubtask:
    title: str
    description: str | None = None
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClarificationProposal:
    summary: str
    subtasks: tuple[ClarificationSubtask, ...]
    open_questions: tuple[str, ...] = ()


def should_route_to_telegram(
    *,
    agent_payload: TaskResultPayload,
    story_points_threshold: int,
) -> bool:
    metadata = agent_payload.metadata
    routing = _mapping(metadata.get("routing"))
    if routing.get("outcome") == "reply_with_clarification":
        return True

    telegram = _mapping(metadata.get("telegram"))
    if telegram.get("required") is True:
        return True

    story_points = _extract_story_points(metadata)
    return (
        story_points_threshold > 0
        and story_points is not None
        and story_points > story_points_threshold
    )


def build_clarification_question(
    *,
    task_context: EffectiveTaskContext,
    agent_payload: TaskResultPayload,
) -> str:
    metadata = agent_payload.metadata
    telegram = _mapping(metadata.get("telegram"))
    question = _first_text(
        telegram.get("question"),
        telegram.get("clarification_question"),
        metadata.get("clarification_question"),
        agent_payload.tracker_comment,
        agent_payload.details,
        agent_payload.summary,
    )
    title = _first_text(
        task_context.execution_context.title if task_context.execution_context else None,
        task_context.tracker_context.title if task_context.tracker_context else None,
        f"Task {task_context.current_task.task.id}",
    )
    return (
        f"Нужно уточнение по задаче: {title}\n\n"
        f"{question}\n\n"
        "Обсудите задачу в ответах к этому сообщению. Когда итоговая декомпозиция будет "
        "согласована, бот предложит финальный вариант и попросит явное подтверждение."
    )


def build_proposal(
    *,
    original_context: TaskContext | None,
    agent_payload: TaskResultPayload,
    transcript: list[dict[str, object]],
) -> ClarificationProposal:
    if not transcript:
        return ClarificationProposal(
            summary=agent_payload.summary,
            subtasks=(),
            open_questions=("waiting for Telegram discussion",),
        )

    latest_text = _latest_human_text(transcript)
    if latest_text and "?" in latest_text:
        return ClarificationProposal(
            summary=latest_text,
            subtasks=(),
            open_questions=("latest Telegram message contains an unresolved question",),
        )

    metadata = agent_payload.metadata
    telegram = _mapping(metadata.get("telegram"))
    summary = _first_text(
        telegram.get("final_summary"),
        metadata.get("final_summary"),
        latest_text,
        agent_payload.tracker_comment,
        agent_payload.summary,
    )
    subtasks = _extract_structured_subtasks(telegram.get("subtasks"))
    if not subtasks:
        subtasks = _extract_structured_subtasks(metadata.get("subtasks"))
    if not subtasks:
        subtasks = _extract_transcript_subtasks(transcript)
    if not subtasks:
        title = original_context.title if original_context is not None else "Clarified task"
        subtasks = (
            ClarificationSubtask(
                title=title,
                description=summary,
                acceptance_criteria=tuple(original_context.acceptance_criteria)
                if original_context is not None
                else (),
            ),
        )
    return ClarificationProposal(summary=summary, subtasks=subtasks)


def format_proposal_message(proposal: ClarificationProposal) -> str:
    lines = [
        "Финальный вариант для фиксации в трекере:",
        "",
        proposal.summary,
        "",
        "Подзадачи:",
    ]
    for index, subtask in enumerate(proposal.subtasks, start=1):
        lines.append(f"{index}. {subtask.title}")
        if subtask.description:
            lines.append(f"   {subtask.description}")
        for criterion in subtask.acceptance_criteria:
            lines.append(f"   AC: {criterion}")
    lines.extend(
        [
            "",
            "Ответьте `да`, `ок`, `готово`, `фиксируй` или `fix`, чтобы применить итог.",
        ]
    )
    return "\n".join(lines)


def is_confirmation(text: str | None) -> bool:
    if text is None:
        return False
    normalized = re.sub(r"[^\wа-яА-ЯёЁ]+", " ", text.lower(), flags=re.UNICODE).strip()
    if not normalized:
        return False
    words = normalized.split()
    return len(words) <= 3 and any(word in _CONFIRMATION_WORDS for word in words)


def dump_proposal(proposal: ClarificationProposal) -> dict[str, object]:
    return {
        "summary": proposal.summary,
        "subtasks": [
            {
                "title": subtask.title,
                "description": subtask.description,
                "acceptance_criteria": list(subtask.acceptance_criteria),
            }
            for subtask in proposal.subtasks
        ],
    }


def load_proposal(value: object) -> ClarificationProposal | None:
    mapping = _mapping(value)
    summary = mapping.get("summary")
    subtasks = _extract_structured_subtasks(mapping.get("subtasks"))
    if not isinstance(summary, str) or not summary.strip() or not subtasks:
        return None
    return ClarificationProposal(summary=summary, subtasks=subtasks)


def proposal_subtask_to_tracker_payload(
    *,
    subtask: ClarificationSubtask,
    source_metadata: dict[str, object],
) -> tuple[TaskContext, TaskInputPayload]:
    context = TaskContext(
        title=subtask.title,
        description=subtask.description,
        acceptance_criteria=list(subtask.acceptance_criteria),
        metadata={"source": TELEGRAM_CLARIFICATION_ROLE, **source_metadata},
    )
    input_payload = TaskInputPayload(
        instructions=subtask.description or subtask.title,
        metadata={"source": TELEGRAM_CLARIFICATION_ROLE},
    )
    return context, input_payload


def _extract_story_points(metadata: dict[str, object]) -> int | None:
    candidates = [
        metadata.get("story_points"),
        _mapping(metadata.get("estimate")).get("story_points"),
        _mapping(metadata.get("routing")).get("story_points"),
        _mapping(metadata.get("telegram")).get("story_points"),
    ]
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.strip().isdigit():
            return int(candidate)
    return None


def _extract_structured_subtasks(value: object) -> tuple[ClarificationSubtask, ...]:
    if not isinstance(value, list):
        return ()
    result: list[ClarificationSubtask] = []
    for raw in value:
        if isinstance(raw, str):
            title = raw.strip()
            if title:
                result.append(ClarificationSubtask(title=title))
            continue
        mapping = _mapping(raw)
        title = _first_text(mapping.get("title"), mapping.get("name"))
        if not title:
            continue
        criteria_value = mapping.get("acceptance_criteria")
        criteria = (
            tuple(
                item.strip()
                for item in criteria_value
                if isinstance(item, str) and item.strip()
            )
            if isinstance(criteria_value, list)
            else ()
        )
        result.append(
            ClarificationSubtask(
                title=title,
                description=_first_text(mapping.get("description"), mapping.get("details")),
                acceptance_criteria=criteria,
            )
        )
    return tuple(result)


def _extract_transcript_subtasks(
    transcript: list[dict[str, object]],
) -> tuple[ClarificationSubtask, ...]:
    result: list[ClarificationSubtask] = []
    for item in transcript:
        text = item.get("text")
        if not isinstance(text, str):
            continue
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            if cleaned != line.strip() and cleaned:
                result.append(ClarificationSubtask(title=cleaned))
    return tuple(result)


def _latest_human_text(transcript: list[dict[str, object]]) -> str | None:
    for item in reversed(transcript):
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


__all__ = [
    "TELEGRAM_CLARIFICATION_ROLE",
    "ClarificationProposal",
    "ClarificationSubtask",
    "build_clarification_question",
    "build_proposal",
    "dump_proposal",
    "format_proposal_message",
    "is_confirmation",
    "load_proposal",
    "proposal_subtask_to_tracker_payload",
    "should_route_to_telegram",
]
