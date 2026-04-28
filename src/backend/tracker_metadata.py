from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.schemas import TrackerEstimatedSelectionQuery, TrackerTask


def get_nested_mapping(metadata: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    return dict(value) if isinstance(value, dict) else {}


def matches_estimated_selection(
    *,
    task: TrackerTask,
    selection: TrackerEstimatedSelectionQuery | None,
) -> bool:
    if selection is None:
        return True
    if selection.only_parent_tasks and task.parent_external_id is not None:
        return False

    estimate_metadata = get_nested_mapping(task.metadata, "estimate")
    selection_metadata = get_nested_mapping(task.metadata, "selection")

    if selection.can_take_in_work is not None:
        if estimate_metadata.get("can_take_in_work") is not selection.can_take_in_work:
            return False

    if selection.taken_in_work is not None:
        if selection_metadata.get("taken_in_work") is not selection.taken_in_work:
            return False

    if selection.max_story_points is not None:
        story_points = estimate_metadata.get("story_points")
        if not isinstance(story_points, int):
            return False
        if story_points > selection.max_story_points:
            return False

    return True


__all__ = ["get_nested_mapping", "matches_estimated_selection"]
