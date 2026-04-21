from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from backend.composition import RuntimeContainer
from backend.db import create_session, get_session_factory
from backend.models import Task
from backend.repositories.task_repository import TaskRepository
from backend.schemas import TrackerTaskCreatePayload

tasks_blueprint = Blueprint("tasks", __name__)


def _serialize_task(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "root_id": task.root_id,
        "parent_id": task.parent_id,
        "task_type": task.task_type.value,
        "status": task.status.value,
        "tracker_name": task.tracker_name,
        "external_task_id": task.external_task_id,
        "external_parent_id": task.external_parent_id,
        "repo_url": task.repo_url,
        "repo_ref": task.repo_ref,
        "workspace_key": task.workspace_key,
        "branch_name": task.branch_name,
        "pr_external_id": task.pr_external_id,
        "pr_url": task.pr_url,
        "role": task.role,
        "context": task.context,
        "input_payload": task.input_payload,
        "result_payload": task.result_payload,
        "error": task.error,
        "attempt": task.attempt,
        "created_at": _serialize_datetime(task.created_at),
        "updated_at": _serialize_datetime(task.updated_at),
    }


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()

    return value.isoformat()


def _build_repository() -> tuple[Session, TaskRepository]:
    session_factory = cast(
        sessionmaker[Session],
        current_app.extensions.get("session_factory") or get_session_factory(),
    )
    session = create_session(session_factory=session_factory)
    return session, TaskRepository(session)


def _get_runtime() -> RuntimeContainer:
    return cast(RuntimeContainer, current_app.extensions["runtime_container"])


@tasks_blueprint.get("/tasks")
def list_tasks():
    session, repository = _build_repository()
    try:
        payload = {"tasks": [_serialize_task(task) for task in repository.list_tasks()]}
    finally:
        session.close()

    return jsonify(payload)


@tasks_blueprint.get("/tasks/<int:task_id>")
def get_task(task_id: int):
    session, repository = _build_repository()
    try:
        task = repository.get_task(task_id)
        if task is None:
            return jsonify({"error": f"Task {task_id} not found"}), 404

        payload = {"task": _serialize_task(task)}
    finally:
        session.close()

    return jsonify(payload)


@tasks_blueprint.post("/tasks/intake")
def intake_task():
    payload_data = request.get_json(silent=True)
    if payload_data is None:
        return jsonify({"error": "Invalid task intake payload", "details": []}), 400

    try:
        payload = TrackerTaskCreatePayload.model_validate(payload_data)
    except ValidationError as exc:
        return (
            jsonify(
                {
                    "error": "Invalid task intake payload",
                    "details": exc.errors(include_url=False),
                }
            ),
            400,
        )

    created_task = _get_runtime().tracker.create_task(payload)
    return jsonify({"external_id": created_task.external_id}), 201


__all__ = ["tasks_blueprint"]
