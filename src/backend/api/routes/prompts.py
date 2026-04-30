from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_session, get_session_factory
from backend.models import AgentPrompt

prompts_blueprint = Blueprint("prompts", __name__)


def _serialize_prompt(prompt: AgentPrompt) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "prompt_key": prompt.prompt_key,
        "source_path": prompt.source_path,
        "content": prompt.content,
        "created_at": _serialize_datetime(prompt.created_at),
        "updated_at": _serialize_datetime(prompt.updated_at),
    }


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()

    return value.isoformat()


def _build_session() -> Session:
    session_factory = cast(
        sessionmaker[Session],
        current_app.extensions.get("session_factory") or get_session_factory(),
    )
    return create_session(session_factory=session_factory)


@prompts_blueprint.get("/prompts")
def list_prompts():
    session = _build_session()
    try:
        prompts = session.query(AgentPrompt).order_by(AgentPrompt.prompt_key).all()
        payload = {"prompts": [_serialize_prompt(prompt) for prompt in prompts]}
    finally:
        session.close()

    return jsonify(payload)


@prompts_blueprint.get("/prompts/<prompt_key>")
def get_prompt(prompt_key: str):
    session = _build_session()
    try:
        prompt = (
            session.query(AgentPrompt).filter(AgentPrompt.prompt_key == prompt_key).one_or_none()
        )
        if prompt is None:
            return jsonify({"error": f"Prompt {prompt_key} not found"}), 404

        payload = {"prompt": _serialize_prompt(prompt)}
    finally:
        session.close()

    return jsonify(payload)


@prompts_blueprint.patch("/prompts/<prompt_key>")
def update_prompt(prompt_key: str):
    payload_data = request.get_json(silent=True)
    if not isinstance(payload_data, dict) or not isinstance(payload_data.get("content"), str):
        return jsonify({"error": "Invalid prompt update payload"}), 400

    session = _build_session()
    try:
        prompt = (
            session.query(AgentPrompt).filter(AgentPrompt.prompt_key == prompt_key).one_or_none()
        )
        if prompt is None:
            return jsonify({"error": f"Prompt {prompt_key} not found"}), 404

        prompt.content = payload_data["content"]
        session.commit()
        payload = {"prompt": _serialize_prompt(prompt)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return jsonify(payload)


__all__ = ["prompts_blueprint"]
