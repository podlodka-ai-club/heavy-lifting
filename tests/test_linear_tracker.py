from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from backend.adapters.linear_tracker import (
    INPUT_BLOCK_CLOSE,
    INPUT_BLOCK_OPEN,
    LinearRateLimitError,
    LinearTracker,
    LinearTrackerConfig,
    _extract_input_block,
    _GraphqlClient,
    _inject_input_block,
)
from backend.protocols.tracker import TrackerProtocol
from backend.task_constants import TaskStatus


def _make_config(**overrides: Any) -> LinearTrackerConfig:
    defaults: dict[str, Any] = {
        "api_url": "https://api.linear.app/graphql",
        "token_env_var": "LINEAR_API_KEY_TEST",
        "team_id": "team-1",
        "timeout_seconds": 30,
        "fetch_label_id": None,
        "explicit_status_to_state_id": {},
        "fetch_state_types": ("triage", "backlog", "unstarted"),
        "task_type_to_label_id": {},
        "max_pages": 4,
        "description_warn_threshold": 50000,
    }
    defaults.update(overrides)
    return LinearTrackerConfig(**defaults)


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


def _never_called(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("http_requester must not be called in this test")


def test_linear_tracker_implements_tracker_protocol_runtime() -> None:
    tracker = LinearTracker(_make_config(), http_requester=_never_called)

    assert isinstance(tracker, TrackerProtocol)


def test_linear_tracker_repr_does_not_contain_token_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_supersecret_value")

    tracker = LinearTracker(_make_config(), http_requester=_never_called)

    assert "lin_api_supersecret_value" not in repr(tracker)
    assert "lin_api_supersecret_value" not in repr(tracker._config)


def test_extract_input_block_returns_empty_for_none_or_empty() -> None:
    assert _extract_input_block(None) == ("", None)
    assert _extract_input_block("") == ("", None)


def test_extract_input_block_returns_description_when_no_block() -> None:
    description = "Just a description without service block"

    cleaned, parsed = _extract_input_block(description)

    assert cleaned == description
    assert parsed is None


def test_extract_input_block_parses_valid_json_block() -> None:
    description = (
        "Hello world\n\n"
        f"{INPUT_BLOCK_OPEN}\n"
        '{"repo_url": "https://example.test/repo", '
        '"input": {"instructions": "do work"}}\n'
        f"{INPUT_BLOCK_CLOSE}"
    )

    cleaned, parsed = _extract_input_block(description)

    assert cleaned == "Hello world"
    assert parsed == {
        "repo_url": "https://example.test/repo",
        "input": {"instructions": "do work"},
    }


def test_extract_input_block_returns_none_when_close_marker_missing() -> None:
    description = f"head\n{INPUT_BLOCK_OPEN}\n{{\"x\": 1}}\nno close here"

    cleaned, parsed = _extract_input_block(description)

    assert cleaned == description
    assert parsed is None


def test_extract_input_block_returns_none_on_invalid_json() -> None:
    description = (
        f"prefix\n{INPUT_BLOCK_OPEN}\nthis is not json at all\n{INPUT_BLOCK_CLOSE}\nsuffix"
    )

    cleaned, parsed = _extract_input_block(description)

    assert "prefix" in cleaned
    assert "suffix" in cleaned
    assert INPUT_BLOCK_OPEN not in cleaned
    assert parsed is None


def test_extract_input_block_returns_none_when_block_is_array() -> None:
    description = (
        f"{INPUT_BLOCK_OPEN}\n[\"not\", \"an\", \"object\"]\n{INPUT_BLOCK_CLOSE}"
    )

    cleaned, parsed = _extract_input_block(description)

    assert parsed is None
    assert INPUT_BLOCK_OPEN not in cleaned


def test_inject_input_block_appends_to_existing_description() -> None:
    description = "Original description"
    payload = {"repo_url": "https://example.test/repo", "workspace_key": "k"}

    result = _inject_input_block(description, payload)

    assert result.startswith("Original description")
    assert INPUT_BLOCK_OPEN in result
    assert INPUT_BLOCK_CLOSE in result


def test_inject_input_block_handles_empty_description() -> None:
    payload = {"workspace_key": "key-1"}

    result = _inject_input_block(None, payload)

    assert result.startswith(INPUT_BLOCK_OPEN)
    assert result.endswith(INPUT_BLOCK_CLOSE)


def test_inject_then_extract_roundtrips_payload() -> None:
    description = "Some description"
    payload = {
        "repo_url": "https://example.test/repo",
        "repo_ref": "main",
        "workspace_key": "ws",
        "input": {"instructions": "run", "base_branch": "main"},
    }

    injected = _inject_input_block(description, payload)
    cleaned, parsed = _extract_input_block(injected)

    assert cleaned == "Some description"
    assert parsed == payload


def test_graphql_client_uses_injected_callable_without_patching_urlopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_test_secret")
    # Canary: prove DI does not delegate to urllib.request.urlopen.
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: pytest.fail(
            "urlopen must not be called when http_requester is injected"
        ),
    )

    captured: dict[str, Any] = {}

    def fake_requester(request: urllib.request.Request, timeout: float) -> Any:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data
        captured["auth"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        return _FakeResponse(b'{"data": {"foo": "bar"}}')

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=fake_requester,
    )

    data = client.execute("query { foo }", {"x": 1})

    assert data == {"foo": "bar"}
    assert captured["url"] == "https://api.linear.app/graphql"
    assert captured["timeout"] == 30.0
    assert captured["auth"] == "lin_api_test_secret"
    assert captured["content_type"] == "application/json"
    assert isinstance(captured["body"], bytes)
    assert json.loads(captured["body"].decode("utf-8")) == {
        "query": "query { foo }",
        "variables": {"x": 1},
    }


def test_graphql_client_raises_when_token_env_var_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LINEAR_API_KEY_TEST", raising=False)

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=_never_called,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("query", {})

    assert "LINEAR_API_KEY_TEST" in str(exc_info.value)


def test_graphql_client_token_is_read_lazily_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LINEAR_API_KEY_TEST", raising=False)

    captured: list[str | None] = []

    def fake_requester(request: urllib.request.Request, _timeout: float) -> Any:
        captured.append(request.get_header("Authorization"))
        return _FakeResponse(b'{"data": {}}')

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=fake_requester,
    )

    monkeypatch.setenv("LINEAR_API_KEY_TEST", "first-token")
    client.execute("q", {})
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "second-token")
    client.execute("q", {})

    assert captured == ["first-token", "second-token"]


def test_graphql_client_raises_rate_limit_on_http_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(b'{"errors":[]}', status=429),
    )

    with pytest.raises(LinearRateLimitError):
        client.execute("q", {})


def test_graphql_client_raises_rate_limit_on_extension_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    body = json.dumps(
        {"errors": [{"message": "rate limit", "extensions": {"code": "RATELIMITED"}}]}
    ).encode("utf-8")
    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(body),
    )

    with pytest.raises(LinearRateLimitError):
        client.execute("q", {})


def test_graphql_client_raises_runtime_error_on_other_graphql_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    body = json.dumps(
        {"errors": [{"message": "Field 'foo' is not defined"}]}
    ).encode("utf-8")
    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(body),
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("q", {})

    assert isinstance(exc_info.value, RuntimeError)
    assert not isinstance(exc_info.value, LinearRateLimitError)
    assert "Field 'foo'" in str(exc_info.value)


def test_graphql_client_raises_on_non_2xx_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(b'{"data":{}}', status=500),
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("q", {})

    assert "500" in str(exc_info.value)


def test_graphql_client_does_not_leak_token_into_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "lin_api_a1b2c3d4e5f6g7h8"
    monkeypatch.setenv("LINEAR_API_KEY_TEST", secret)

    body = json.dumps({"errors": [{"message": "oops"}]}).encode("utf-8")
    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(body),
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("q", {})

    assert secret not in str(exc_info.value)


def _states_response_body(nodes: list[dict[str, Any]]) -> bytes:
    return json.dumps({"data": {"team": {"states": {"nodes": nodes}}}}).encode("utf-8")


def _counting_http_requester(
    body: bytes,
) -> tuple[Any, list[urllib.request.Request]]:
    calls: list[urllib.request.Request] = []

    def fake(req: urllib.request.Request, _timeout: float) -> Any:
        calls.append(req)
        return _FakeResponse(body)

    return fake, calls


def test_status_to_state_id_uses_explicit_mapping_without_calling_api() -> None:
    config = _make_config(
        explicit_status_to_state_id={
            TaskStatus.PROCESSING: "explicit-proc-id",
            TaskStatus.DONE: "explicit-done-id",
        },
    )
    tracker = LinearTracker(config, http_requester=_never_called)

    assert tracker._status_to_state_id(TaskStatus.PROCESSING) == "explicit-proc-id"
    assert tracker._status_to_state_id(TaskStatus.DONE) == "explicit-done-id"


def test_status_to_state_id_falls_back_to_min_position_within_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "started-late", "name": "Doing", "type": "started", "position": 200.0},
            {"id": "started-early", "name": "In Progress", "type": "started", "position": 100.0},
            {"id": "unstarted-1", "name": "Todo", "type": "unstarted", "position": 50.0},
        ]
    )
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    assert tracker._status_to_state_id(TaskStatus.PROCESSING) == "started-early"


def test_status_to_state_id_for_new_prefers_unstarted_over_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "backlog-1", "name": "Backlog", "type": "backlog", "position": 10.0},
            {"id": "unstarted-1", "name": "Todo", "type": "unstarted", "position": 30.0},
        ]
    )
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    assert tracker._status_to_state_id(TaskStatus.NEW) == "unstarted-1"


def test_status_to_state_id_for_new_falls_back_to_backlog_when_no_unstarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "backlog-low", "name": "Icebox", "type": "backlog", "position": 100.0},
            {"id": "backlog-high", "name": "Backlog", "type": "backlog", "position": 50.0},
        ]
    )
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    assert tracker._status_to_state_id(TaskStatus.NEW) == "backlog-high"


def test_status_to_state_id_raises_when_no_explicit_and_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "started-1", "name": "Doing", "type": "started", "position": 10.0},
        ]
    )
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker._status_to_state_id(TaskStatus.DONE)

    message = str(exc_info.value)
    assert "LINEAR_STATE_ID_DONE" in message
    assert "TaskStatus.DONE" in message


def test_resolve_workflow_states_is_cached_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "started-1", "name": "Doing", "type": "started", "position": 10.0},
            {"id": "completed-1", "name": "Done", "type": "completed", "position": 20.0},
        ]
    )
    fake, calls = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    assert tracker._status_to_state_id(TaskStatus.PROCESSING) == "started-1"
    assert tracker._status_to_state_id(TaskStatus.DONE) == "completed-1"
    # second resolve must hit cache, not the API
    assert tracker._status_to_state_id(TaskStatus.PROCESSING) == "started-1"

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("state_type", "expected"),
    [
        ("triage", TaskStatus.NEW),
        ("backlog", TaskStatus.NEW),
        ("unstarted", TaskStatus.NEW),
        ("started", TaskStatus.PROCESSING),
        ("completed", TaskStatus.DONE),
        ("canceled", TaskStatus.FAILED),
    ],
)
def test_state_to_task_status_maps_known_types(
    state_type: str, expected: TaskStatus
) -> None:
    assert LinearTracker._state_to_task_status(state_type) is expected


@pytest.mark.parametrize("state_type", [None, "", "weird-custom-type"])
def test_state_to_task_status_returns_none_for_missing_or_unknown(
    state_type: str | None,
) -> None:
    assert LinearTracker._state_to_task_status(state_type) is None


def test_resolve_workflow_states_raises_when_team_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps({"data": {"team": None}}).encode("utf-8")
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(team_id="missing-team"), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker._status_to_state_id(TaskStatus.PROCESSING)

    assert "missing-team" in str(exc_info.value)


def test_resolve_workflow_states_raises_when_state_position_not_numeric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _states_response_body(
        [
            {"id": "s1", "name": "Doing", "type": "started", "position": "not-a-number"},
        ]
    )
    fake, _ = _counting_http_requester(body)
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker._status_to_state_id(TaskStatus.PROCESSING)

    assert "position" in str(exc_info.value)
