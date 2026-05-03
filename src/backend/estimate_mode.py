from __future__ import annotations

from backend.schemas import TaskInputPayload
from backend.task_context import EffectiveTaskContext

_ESTIMATE_ONLY_METADATA_KEY = "estimate_only"


def mark_input_payload_estimate_only(*, payload: TaskInputPayload | None) -> TaskInputPayload:
    base_payload = payload or TaskInputPayload()
    metadata = dict(base_payload.metadata)
    metadata[_ESTIMATE_ONLY_METADATA_KEY] = True
    return base_payload.model_copy(update={"metadata": metadata})


def is_explicit_estimate_only_payload(payload: TaskInputPayload | None) -> bool:
    if payload is None:
        return False
    value = payload.metadata.get(_ESTIMATE_ONLY_METADATA_KEY)
    return value is True


def is_explicit_estimate_only_context(context: EffectiveTaskContext) -> bool:
    execute_entry = context.execute_task
    if execute_entry is None:
        return False
    return is_explicit_estimate_only_payload(execute_entry.input_payload)
