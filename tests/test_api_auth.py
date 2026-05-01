from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings

EXTERNAL_ADDR = "203.0.113.10"


def test_basic_auth_guard_is_disabled_when_credentials_are_incomplete() -> None:
    app = create_app(
        runtime=_runtime(username="heavy", password=None),
        session_factory=object(),
    )

    response = app.test_client().get(
        "/health",
        environ_base={"REMOTE_ADDR": EXTERNAL_ADDR},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


@pytest.mark.parametrize("remote_addr", ["127.0.0.1", "::1"])
def test_basic_auth_guard_bypasses_localhost(remote_addr: str) -> None:
    app = create_app(
        runtime=_runtime(username="heavy", password="lifting"),
        session_factory=object(),
    )

    response = app.test_client().get(
        "/health",
        environ_base={"REMOTE_ADDR": remote_addr},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_basic_auth_guard_rejects_external_request_without_auth() -> None:
    app = create_app(
        runtime=_runtime(username="heavy", password="lifting"),
        session_factory=object(),
    )

    response = app.test_client().get(
        "/health",
        environ_base={"REMOTE_ADDR": EXTERNAL_ADDR},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="heavy-lifting"'


def test_basic_auth_guard_rejects_external_request_with_invalid_auth() -> None:
    app = create_app(
        runtime=_runtime(username="heavy", password="lifting"),
        session_factory=object(),
    )

    response = app.test_client().get(
        "/health",
        headers={"Authorization": _basic_auth_header("heavy", "wrong")},
        environ_base={"REMOTE_ADDR": EXTERNAL_ADDR},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="heavy-lifting"'


def test_basic_auth_guard_allows_external_request_with_valid_auth() -> None:
    app = create_app(
        runtime=_runtime(username="heavy", password="lifting"),
        session_factory=object(),
    )

    response = app.test_client().get(
        "/health",
        headers={"Authorization": _basic_auth_header("heavy", "lifting")},
        environ_base={"REMOTE_ADDR": EXTERNAL_ADDR},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def _runtime(username: str | None, password: str | None) -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(
            get_settings(),
            api_basic_auth_username=username,
            api_basic_auth_password=password,
        ),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"
