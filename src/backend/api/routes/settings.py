from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_session, get_session_factory
from backend.models import ApplicationSetting

settings_blueprint = Blueprint("settings", __name__)


def _serialize_setting(setting: ApplicationSetting) -> dict[str, Any]:
    return {
        "id": setting.id,
        "setting_key": setting.setting_key,
        "env_var": setting.env_var,
        "value_type": setting.value_type,
        "value": setting.value,
        "default_value": setting.default_value,
        "description": setting.description,
        "display_order": setting.display_order,
        "requires_restart": True,
        "created_at": _serialize_datetime(setting.created_at),
        "updated_at": _serialize_datetime(setting.updated_at),
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


@settings_blueprint.get("/settings")
def list_settings():
    session = _build_session()
    try:
        settings = (
            session.query(ApplicationSetting)
            .order_by(ApplicationSetting.display_order, ApplicationSetting.setting_key)
            .all()
        )
        payload = {"settings": [_serialize_setting(setting) for setting in settings]}
    finally:
        session.close()

    return jsonify(payload)


@settings_blueprint.patch("/settings/<setting_key>")
def update_setting(setting_key: str):
    payload_data = request.get_json(silent=True)
    if not isinstance(payload_data, dict) or not isinstance(payload_data.get("value"), str):
        return jsonify({"error": "Invalid setting update payload"}), 400

    session = _build_session()
    try:
        setting = (
            session.query(ApplicationSetting)
            .filter(ApplicationSetting.setting_key == setting_key)
            .one_or_none()
        )
        if setting is None:
            return jsonify({"error": f"Setting {setting_key} not found"}), 404

        next_value = payload_data["value"].strip()
        error = _validate_setting_value(setting.value_type, next_value)
        if error is not None:
            return jsonify({"error": error}), 400

        setting.value = next_value
        session.commit()
        payload = {"setting": _serialize_setting(setting)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return jsonify(payload)


def _validate_setting_value(value_type: str, value: str) -> str | None:
    if value_type == "int":
        try:
            parsed = int(value)
        except ValueError:
            return "Setting value must be a positive integer"
        if parsed <= 0:
            return "Setting value must be a positive integer"
        return None

    if value_type == "string":
        if not value:
            return "Setting value must not be empty"
        return None

    return "Unsupported setting value type"


__all__ = ["settings_blueprint"]
