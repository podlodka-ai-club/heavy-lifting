from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import inspect

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import ApplicationSetting, Base
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_get_settings_lists_runtime_settings_ordered_by_display_order(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/settings")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert [setting["setting_key"] for setting in payload["settings"]] == [
        "tracker_fetch_limit",
        "execute_worker_batch_size",
        "pr_feedback_fetch_limit",
        "local_agent_provider",
        "local_agent_model",
        "local_agent_name",
        "cli_agent_preview_chars",
    ]
    assert [setting["value"] for setting in payload["settings"]] == [
        "100",
        "1",
        "100",
        "openai",
        "gpt-5.4",
        "local-placeholder-runner",
        "1000",
    ]


def test_get_settings_bootstraps_missing_application_settings_table(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'existing.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table_name, table in Base.metadata.tables.items()
            if table_name != ApplicationSetting.__tablename__
        ],
    )
    session_factory = build_session_factory(engine)
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/settings")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert [setting["setting_key"] for setting in payload["settings"]] == [
        "tracker_fetch_limit",
        "execute_worker_batch_size",
        "pr_feedback_fetch_limit",
        "local_agent_provider",
        "local_agent_model",
        "local_agent_name",
        "cli_agent_preview_chars",
    ]
    assert ApplicationSetting.__tablename__ in inspect(engine).get_table_names()


def test_create_app_does_not_bootstrap_settings_until_settings_route(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(
        "backend.api.routes.settings.ensure_application_settings_schema",
        lambda session_factory: calls.append(session_factory),
    )

    app = create_app(runtime=_runtime(), session_factory=object())

    assert calls == []

    response = app.test_client().get("/openapi.json")

    assert response.status_code == 200
    assert calls == []


def test_patch_setting_updates_value_by_key(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch(
        "/settings/tracker_fetch_limit",
        json={"value": "25"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["setting"]["setting_key"] == "tracker_fetch_limit"
    assert payload["setting"]["value"] == "25"

    with session_scope(session_factory=session_factory) as session:
        stored_setting = (
            session.query(ApplicationSetting)
            .filter(ApplicationSetting.setting_key == "tracker_fetch_limit")
            .one()
        )

    assert stored_setting.value == "25"


def test_setting_endpoint_returns_json_404_for_missing_setting(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch("/settings/missing", json={"value": "25"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "Setting missing not found"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"value": None},
        {"value": 123},
    ],
)
def test_patch_setting_returns_json_400_for_invalid_payload(session_factory, payload) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch("/settings/tracker_fetch_limit", json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid setting update payload"}


@pytest.mark.parametrize("value", ["0", "-1", "not-int"])
def test_patch_setting_rejects_invalid_int_value(session_factory, value) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch("/settings/tracker_fetch_limit", json={"value": value})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Setting value must be a positive integer"}


def test_patch_setting_rejects_empty_string_value(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch("/settings/local_agent_model", json={"value": " "})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Setting value must not be empty"}


def _seed_settings(session_factory) -> tuple[ApplicationSetting, ApplicationSetting]:
    with session_scope(session_factory=session_factory) as session:
        first = ApplicationSetting(
            setting_key="tracker_fetch_limit",
            env_var="TRACKER_FETCH_LIMIT",
            value_type="int",
            value="100",
            default_value="100",
            description="Fetch limit",
            display_order=10,
        )
        second = ApplicationSetting(
            setting_key="local_agent_model",
            env_var="LOCAL_AGENT_MODEL",
            value_type="string",
            value="gpt-5.4",
            default_value="gpt-5.4",
            description="Local model",
            display_order=40,
        )
        session.add_all([second, first])

    return first, second


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
