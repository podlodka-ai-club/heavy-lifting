from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings


def test_get_settings_returns_agent_prompts_without_api_key_value(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().get("/settings")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        "api_key": {
            "configured": False,
            "source": "none",
            "env_var": "OPENAI_API_KEY",
        },
        "agents": [
            {"name": "implementer", "prompt": "Implement prompt\n", "source": "default"},
            {"name": "reviewer", "prompt": "Review prompt\n", "source": "default"},
        ],
    }
    assert "sk-" not in json.dumps(payload)


def test_update_settings_persists_runtime_api_key_and_prompt_overrides(tmp_path) -> None:
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().put(
        "/settings",
        json={
            "api_key": "sk-runtime",
            "prompts": {"implementer": "Custom implementer prompt\n"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["api_key"] == {
        "configured": True,
        "source": "runtime",
        "env_var": "OPENAI_API_KEY",
    }
    assert payload["agents"] == [
        {"name": "implementer", "prompt": "Custom implementer prompt\n", "source": "runtime"},
        {"name": "reviewer", "prompt": "Review prompt\n", "source": "default"},
    ]
    assert "sk-runtime" not in json.dumps(payload)

    stored = json.loads((tmp_path / "var" / "runtime-settings.json").read_text())
    assert stored == {
        "api_key": "sk-runtime",
        "prompts": {"implementer": "Custom implementer prompt\n"},
    }

    followup = app.test_client().get("/settings")
    assert followup.status_code == 200
    assert followup.get_json() == payload


def test_update_settings_clears_runtime_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime_path = tmp_path / "var" / "runtime-settings.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text('{"api_key": "sk-runtime"}\n', encoding="utf-8")
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().put("/settings", json={"api_key": ""})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["api_key"]["configured"] is False
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {}


def test_get_settings_reports_env_api_key_without_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().get("/settings")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["api_key"] == {
        "configured": True,
        "source": "env",
        "env_var": "OPENAI_API_KEY",
    }
    assert "sk-env" not in json.dumps(payload)


def test_get_settings_ignores_corrupted_runtime_settings_json(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime_path = tmp_path / "var" / "runtime-settings.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text('{"broken"', encoding="utf-8")
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().get("/settings")

    assert response.status_code == 200
    assert response.get_json() == {
        "api_key": {
            "configured": False,
            "source": "none",
            "env_var": "OPENAI_API_KEY",
        },
        "agents": [
            {"name": "implementer", "prompt": "Implement prompt\n", "source": "default"},
            {"name": "reviewer", "prompt": "Review prompt\n", "source": "default"},
        ],
    }


def test_update_settings_overwrites_corrupted_runtime_settings_json(tmp_path) -> None:
    runtime_path = tmp_path / "var" / "runtime-settings.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text('{"broken"', encoding="utf-8")
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().put("/settings", json={"api_key": "sk-runtime"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["api_key"] == {
        "configured": True,
        "source": "runtime",
        "env_var": "OPENAI_API_KEY",
    }
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"api_key": "sk-runtime"}


def test_update_settings_rejects_unknown_agent_prompt(tmp_path) -> None:
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().put(
        "/settings",
        json={"prompts": {"unknown": "No such prompt"}},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Unknown agent prompt: unknown",
        "details": [],
    }


def test_update_settings_rejects_invalid_json(tmp_path) -> None:
    app = create_app(runtime=_runtime(tmp_path))

    response = app.test_client().put(
        "/settings",
        data="not-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid settings payload", "details": []}


def _runtime(tmp_path: Path) -> RuntimeContainer:
    prompts_dir = tmp_path / "prompts" / "agents"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "reviewer.md").write_text("Review prompt\n", encoding="utf-8")
    (prompts_dir / "implementer.md").write_text("Implement prompt\n", encoding="utf-8")

    return RuntimeContainer(
        settings=replace(
            get_settings(),
            runtime_settings_path=str(tmp_path / "var" / "runtime-settings.json"),
            agent_prompts_dir=str(prompts_dir),
            cli_agent_api_key_env_var="OPENAI_API_KEY",
        ),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
