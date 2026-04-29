from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.composition import RuntimeContainer
from backend.services.runtime_settings import RuntimeSettingsSnapshot, RuntimeSettingsStore

settings_blueprint = Blueprint("settings", __name__)


class SettingsUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    prompts: dict[str, str] | None = None


def _get_runtime() -> RuntimeContainer:
    return cast(RuntimeContainer, current_app.extensions["runtime_container"])


def _build_store() -> RuntimeSettingsStore:
    settings = _get_runtime().settings
    return RuntimeSettingsStore(
        storage_path=Path(settings.runtime_settings_path),
        prompts_dir=Path(settings.agent_prompts_dir),
        api_key_env_var=settings.cli_agent_api_key_env_var,
    )


def _serialize_snapshot(snapshot: RuntimeSettingsSnapshot) -> dict[str, Any]:
    return {
        "api_key": {
            "configured": snapshot.api_key_configured,
            "source": snapshot.api_key_source,
            "env_var": snapshot.api_key_env_var,
        },
        "agents": [
            {
                "name": prompt.name,
                "prompt": prompt.prompt,
                "source": prompt.source,
            }
            for prompt in snapshot.agent_prompts
        ],
    }


@settings_blueprint.get("/settings")
def get_settings_route():
    return jsonify(_serialize_snapshot(_build_store().snapshot()))


@settings_blueprint.put("/settings")
def update_settings_route():
    payload_data = request.get_json(silent=True)
    if payload_data is None:
        return jsonify({"error": "Invalid settings payload", "details": []}), 400

    try:
        payload = SettingsUpdatePayload.model_validate(payload_data)
        snapshot = _build_store().update(
            api_key_provided="api_key" in payload.model_fields_set,
            api_key=payload.api_key,
            prompts=payload.prompts,
        )
    except ValidationError as exc:
        return (
            jsonify(
                {
                    "error": "Invalid settings payload",
                    "details": exc.errors(include_url=False),
                }
            ),
            400,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc), "details": []}), 400

    return jsonify(_serialize_snapshot(snapshot))


__all__ = ["settings_blueprint"]
