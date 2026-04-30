from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_session, get_session_factory
from backend.models import AgentFeedbackEntry
from backend.services.retro_service import RetroEntriesQuery, RetroService
from backend.task_constants import TaskType

retro_blueprint = Blueprint("retro", __name__)


@retro_blueprint.get("/retro/entries")
def list_retro_entries():
    query_or_error = _parse_entries_query()
    if isinstance(query_or_error, tuple):
        return jsonify(query_or_error[0]), query_or_error[1]

    session = _create_retro_session()
    try:
        entries = RetroService(session).list_entries(query_or_error)
        payload = {"entries": [_serialize_entry(entry) for entry in entries]}
    finally:
        session.close()

    return jsonify(payload)


@retro_blueprint.get("/retro/tags")
def list_retro_tags():
    session = _create_retro_session()
    try:
        payload = {"tags": RetroService(session).list_tag_aggregates()}
    finally:
        session.close()

    return jsonify(payload)


def _parse_entries_query() -> RetroEntriesQuery | tuple[dict[str, str], int]:
    task_type = None
    raw_task_type = request.args.get("task_type")
    if raw_task_type:
        try:
            task_type = TaskType(raw_task_type)
        except ValueError:
            return {"error": "Invalid task_type filter"}, 400

    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = 100
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            return {"error": "Invalid limit filter"}, 400
        if limit < 1 or limit > 1000:
            return {"error": "Invalid limit filter"}, 400

    source = request.args.get("source")
    if source is not None and source != "agent":
        return {"error": "Invalid source filter"}, 400

    return RetroEntriesQuery(
        task_type=task_type,
        tag=request.args.get("tag"),
        severity=request.args.get("severity"),
        source=source,
        limit=limit,
    )


def _serialize_entry(entry: AgentFeedbackEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "task_id": entry.task_id,
        "root_id": entry.root_id,
        "task_type": entry.task_type.value,
        "role": entry.role,
        "attempt": entry.attempt,
        "source": entry.source,
        "category": entry.category,
        "tag": entry.tag,
        "severity": entry.severity,
        "message": entry.message,
        "suggested_action": entry.suggested_action,
        "metadata": entry.entry_metadata or {},
        "created_at": _serialize_datetime(entry.created_at),
    }


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def _create_retro_session() -> Session:
    session_factory = cast(
        sessionmaker[Session],
        current_app.extensions.get("session_factory") or get_session_factory(),
    )
    return create_session(session_factory=session_factory)


__all__ = ["retro_blueprint"]
