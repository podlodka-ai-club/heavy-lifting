"""Deterministic parser for the triage agent stdout contract.

The triage agent (see ``prompts/agents/triage.md``) emits exactly two XML-like
blocks to stdout:

* ``<triage_result>`` — three ``key: value`` lines (machine-readable).
* ``<markdown>`` — one of four Russian templates (human-readable).

This module validates that contract and returns a ``TriageDecision`` value
object suitable for downstream orchestration. Any contract violation raises
``TriageOutputError`` so the pipeline can fail fast and surface the raw stdout
to the human reviewer.

The parser is intentionally pure: it does not depend on the agent runner,
schemas, database, or any I/O. It can be exercised entirely from synthetic
strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "TriageDecision",
    "TriageOutputError",
    "parse_triage_output",
]


class TriageOutputError(ValueError):
    """Raised when raw triage output violates the contract."""


StoryPoints = Literal[1, 2, 3, 5, 8, 13]
TaskKind = Literal["implementation", "research", "clarification", "rejected"]
Outcome = Literal["routed", "needs_clarification", "blocked"]


_VALID_STORY_POINTS: Final[frozenset[int]] = frozenset({1, 2, 3, 5, 8, 13})
_VALID_TASK_KIND: Final[frozenset[str]] = frozenset(
    {"implementation", "research", "clarification", "rejected"}
)
_VALID_OUTCOME: Final[frozenset[str]] = frozenset(
    {"routed", "needs_clarification", "blocked"}
)

# SP → outcome mapping (mirror prompts/agents/triage.md <estimation_matrix>).
_SP_TO_OUTCOME: Final[dict[int, str]] = {
    1: "routed",
    2: "routed",
    3: "routed",
    5: "needs_clarification",
    8: "blocked",
    13: "blocked",
}

# SP → leading markdown heading (mirror prompts/agents/triage.md templates A–D).
_SP_TO_HEADING: Final[dict[int, str]] = {
    1: "## Agent Handover Brief",
    2: "## Agent Handover Brief",
    3: "## Agent Handover Brief",
    5: "## RFI",
    8: "## Decomposition",
    13: "## Needs System Design",
}

_SP_BRIEF: Final[frozenset[int]] = frozenset({1, 2, 3})
_SP_COMMENT: Final[frozenset[int]] = frozenset({5, 8, 13})

_RE_TRIAGE_RESULT: Final[re.Pattern[str]] = re.compile(
    r"<triage_result>\s*(.*?)\s*</triage_result>", re.DOTALL
)
_RE_MARKDOWN: Final[re.Pattern[str]] = re.compile(
    r"<markdown>\s*(.*?)\s*</markdown>", re.DOTALL
)
_RE_KV_LINE: Final[re.Pattern[str]] = re.compile(r"^([a-z_]+)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """Structured representation of a single triage decision."""

    story_points: StoryPoints
    task_kind: TaskKind
    outcome: Outcome
    brief_markdown: str | None
    comment_markdown: str | None
    raw_output: str


def parse_triage_output(raw: str) -> TriageDecision:
    """Parse raw stdout of the triage agent.

    Parameters
    ----------
    raw:
        Raw stdout captured from the triage agent run.

    Returns
    -------
    TriageDecision
        A frozen value object with the parsed Story Point, ``task_kind``,
        ``outcome`` and the human-readable markdown body routed to the correct
        slot (``brief_markdown`` for SP 1/2/3, ``comment_markdown`` for SP
        5/8/13).

    Raises
    ------
    TriageOutputError
        Raised on any contract violation: missing/duplicate envelope blocks,
        invalid enum values, ``outcome`` inconsistent with ``story_points``,
        or a markdown body whose leading heading does not match the template
        required by the chosen Story Point.
    """

    if not isinstance(raw, str):
        raise TriageOutputError(
            f"raw triage output must be str, got {type(raw).__name__}"
        )

    triage_blocks = _RE_TRIAGE_RESULT.findall(raw)
    markdown_blocks = _RE_MARKDOWN.findall(raw)

    if len(triage_blocks) != 1 or len(markdown_blocks) != 1:
        raise TriageOutputError(
            "expected exactly one <triage_result> and one <markdown> block, "
            f"got {len(triage_blocks)} triage_result / {len(markdown_blocks)} markdown"
        )

    triage_body = triage_blocks[0]
    markdown_body = markdown_blocks[0].strip()

    fields = _parse_key_value_lines(triage_body)

    story_points = _coerce_story_points(fields.get("story_points"))
    task_kind = _coerce_task_kind(fields.get("task_kind"))
    outcome = _coerce_outcome(fields.get("outcome"))

    expected_outcome = _SP_TO_OUTCOME[story_points]
    if outcome != expected_outcome:
        raise TriageOutputError(
            "outcome inconsistent with story_points: "
            f"story_points={story_points} expects outcome={expected_outcome!r}, "
            f"got outcome={outcome!r}"
        )

    expected_heading = _SP_TO_HEADING[story_points]
    if not markdown_body.startswith(expected_heading):
        raise TriageOutputError(
            "markdown body does not start with required heading: "
            f"story_points={story_points} expects {expected_heading!r}"
        )

    if story_points in _SP_BRIEF:
        brief_markdown: str | None = markdown_body
        comment_markdown: str | None = None
    else:
        brief_markdown = None
        comment_markdown = markdown_body

    return TriageDecision(
        story_points=story_points,  # type: ignore[arg-type]
        task_kind=task_kind,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        brief_markdown=brief_markdown,
        comment_markdown=comment_markdown,
        raw_output=raw,
    )


def _parse_key_value_lines(body: str) -> dict[str, str]:
    """Parse the three ``key: value`` lines inside ``<triage_result>``.

    Allows blank lines but rejects malformed lines and duplicated keys so the
    parser surfaces ambiguous output instead of silently overwriting fields.
    """

    fields: dict[str, str] = {}
    expected_keys = {"story_points", "task_kind", "outcome"}

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _RE_KV_LINE.match(line)
        if match is None:
            raise TriageOutputError(
                f"malformed line inside <triage_result>: {raw_line!r}"
            )
        key, value = match.group(1), match.group(2)
        if key not in expected_keys:
            raise TriageOutputError(
                f"unknown key inside <triage_result>: {key!r}"
            )
        if key in fields:
            raise TriageOutputError(
                f"duplicate key inside <triage_result>: {key!r}"
            )
        fields[key] = value

    missing = expected_keys - fields.keys()
    if missing:
        raise TriageOutputError(
            "missing required keys inside <triage_result>: "
            + ", ".join(sorted(missing))
        )

    return fields


def _coerce_story_points(raw_value: str | None) -> int:
    if raw_value is None:
        raise TriageOutputError("missing story_points")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise TriageOutputError(
            f"story_points must be an integer, got {raw_value!r}"
        ) from exc
    if value not in _VALID_STORY_POINTS:
        raise TriageOutputError(
            f"story_points must be one of {sorted(_VALID_STORY_POINTS)}, got {value}"
        )
    return value


def _coerce_task_kind(raw_value: str | None) -> str:
    if raw_value is None:
        raise TriageOutputError("missing task_kind")
    if raw_value not in _VALID_TASK_KIND:
        raise TriageOutputError(
            f"task_kind must be one of {sorted(_VALID_TASK_KIND)}, got {raw_value!r}"
        )
    return raw_value


def _coerce_outcome(raw_value: str | None) -> str:
    if raw_value is None:
        raise TriageOutputError("missing outcome")
    if raw_value not in _VALID_OUTCOME:
        raise TriageOutputError(
            f"outcome must be one of {sorted(_VALID_OUTCOME)}, got {raw_value!r}"
        )
    return raw_value
