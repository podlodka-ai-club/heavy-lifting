from __future__ import annotations

import io
import json
import urllib.error
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
from backend.schemas import (
    TaskContext,
    TaskInputPayload,
    TaskLink,
    TrackerCommentCreatePayload,
    TrackerEstimatedSelectionQuery,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTaskCreatePayload,
)
from backend.task_constants import TaskStatus, TaskType


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
    description = f'head\n{INPUT_BLOCK_OPEN}\n{{"x": 1}}\nno close here'

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
    description = f'{INPUT_BLOCK_OPEN}\n["not", "an", "object"]\n{INPUT_BLOCK_CLOSE}'

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


def test_inject_then_extract_roundtrips_estimate_and_selection_metadata() -> None:
    description = "Estimated task"
    payload = {
        "estimate": {"story_points": 3, "can_take_in_work": True},
        "selection": {"taken_in_work": False},
    }

    injected = _inject_input_block(description, payload)
    cleaned, parsed = _extract_input_block(injected)

    assert cleaned == description
    assert parsed == payload


def test_graphql_client_uses_injected_callable_without_patching_urlopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_test_secret")
    # Canary: prove DI does not delegate to urllib.request.urlopen.
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: pytest.fail("urlopen must not be called when http_requester is injected"),
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

    body = json.dumps({"errors": [{"message": "Field 'foo' is not defined"}]}).encode("utf-8")
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
def test_state_to_task_status_maps_known_types(state_type: str, expected: TaskStatus) -> None:
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


def _issues_response_body(
    nodes: list[dict[str, Any]],
    *,
    has_next: bool = False,
    end_cursor: str | None = None,
) -> bytes:
    return json.dumps(
        {
            "data": {
                "issues": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                }
            }
        }
    ).encode("utf-8")


def _scripted_http_requester(
    bodies: list[bytes],
) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    queue = list(bodies)

    def fake(req: urllib.request.Request, _timeout: float) -> Any:
        body_bytes = req.data or b""
        parsed = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        calls.append(
            {
                "query": parsed.get("query"),
                "variables": parsed.get("variables"),
            }
        )
        if not queue:
            raise AssertionError("no scripted response left for http_requester")
        return _FakeResponse(queue.pop(0))

    return fake, calls


def _issue_node(
    *,
    issue_id: str,
    state_type: str = "unstarted",
    title: str = "Some issue",
    description: str | None = None,
    parent_id: str | None = None,
    label_nodes: list[dict[str, Any]] | None = None,
    attachment_nodes: list[dict[str, Any]] | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "parent": {"id": parent_id} if parent_id else None,
        "title": title,
        "description": description,
        "state": {"id": f"state-{state_type}", "type": state_type, "name": state_type.upper()},
        "labels": {"nodes": label_nodes or []},
        "attachments": {"nodes": attachment_nodes or []},
        "url": url or f"https://linear.app/team/issue/{issue_id}",
    }


def test_fetch_tasks_returns_empty_when_state_intersection_is_empty() -> None:
    config = _make_config(fetch_state_types=("started",))
    tracker = LinearTracker(config, http_requester=_never_called)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=50))

    assert result == []


def test_fetch_tasks_single_page_maps_issue_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    issue = _issue_node(
        issue_id="ISS-1",
        title="Implement X",
        description="Hello\n\n"
        + INPUT_BLOCK_OPEN
        + "\n"
        + json.dumps(
            {
                "repo_url": "https://example.test/repo",
                "repo_ref": "main",
                "workspace_key": "ws-1",
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
                "input": {"instructions": "do work", "branch_name": "feat/x"},
            }
        )
        + "\n"
        + INPUT_BLOCK_CLOSE,
        parent_id="ISS-PARENT",
        attachment_nodes=[
            {"url": "https://example.test/pr/1", "title": "PR #1"},
            {"url": "https://example.test/pr/2", "title": None},
        ],
        url="https://linear.app/team/issue/ISS-1",
    )
    body = _issues_response_body([issue])
    fake, calls = _scripted_http_requester([body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=50))

    assert len(result) == 1
    task = result[0]
    assert task.external_id == "ISS-1"
    assert task.parent_external_id == "ISS-PARENT"
    assert task.status is TaskStatus.NEW
    assert task.context.title == "Implement X"
    assert task.context.description == "Hello"
    assert [link.url for link in task.context.references] == [
        "https://example.test/pr/1",
        "https://example.test/pr/2",
    ]
    assert task.context.references[0].label == "PR #1"
    # second attachment had no title — falls back to url as label
    assert task.context.references[1].label == "https://example.test/pr/2"
    assert task.repo_url == "https://example.test/repo"
    assert task.repo_ref == "main"
    assert task.workspace_key == "ws-1"
    assert task.input_payload is not None
    assert task.input_payload.instructions == "do work"
    assert task.input_payload.branch_name == "feat/x"
    assert task.metadata["estimate"] == {
        "story_points": 2,
        "can_take_in_work": True,
    }
    assert task.metadata["selection"] == {"taken_in_work": False}
    assert task.metadata["linear_issue_url"] == "https://linear.app/team/issue/ISS-1"
    assert task.metadata["linear_team_id"] == "team-1"

    assert len(calls) == 1
    variables = calls[0]["variables"]
    assert variables["orderBy"] == "createdAt"
    assert variables["first"] <= 250
    assert variables["after"] is None
    state_filter = variables["filter"]["state"]["type"]["in"]
    assert set(state_filter) == {"triage", "backlog", "unstarted"}


def test_fetch_tasks_filters_by_estimated_selection_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    issues = [
        _issue_node(
            issue_id="ISS-ELIGIBLE",
            state_type="completed",
            description=_inject_input_block(
                "Eligible",
                {
                    "estimate": {"story_points": 2, "can_take_in_work": True},
                    "selection": {"taken_in_work": False},
                },
            ),
        ),
        _issue_node(
            issue_id="ISS-TOO-LARGE",
            state_type="completed",
            description=_inject_input_block(
                "Too large",
                {
                    "estimate": {"story_points": 8, "can_take_in_work": True},
                    "selection": {"taken_in_work": False},
                },
            ),
        ),
        _issue_node(
            issue_id="ISS-CHILD",
            state_type="completed",
            parent_id="ISS-PARENT",
            description=_inject_input_block(
                "Child",
                {
                    "estimate": {"story_points": 1, "can_take_in_work": True},
                    "selection": {"taken_in_work": False},
                },
            ),
        ),
        _issue_node(
            issue_id="ISS-TAKEN",
            state_type="completed",
            description=_inject_input_block(
                "Taken",
                {
                    "estimate": {"story_points": 1, "can_take_in_work": True},
                    "selection": {"taken_in_work": True},
                },
            ),
        ),
    ]
    fake, _ = _scripted_http_requester([_issues_response_body(issues)])
    tracker = LinearTracker(_make_config(fetch_state_types=("completed",)), http_requester=fake)

    result = tracker.fetch_tasks(
        TrackerFetchTasksQuery(
            statuses=[TaskStatus.DONE],
            estimated_selection=TrackerEstimatedSelectionQuery(
                max_story_points=3,
                can_take_in_work=True,
                taken_in_work=False,
                only_parent_tasks=True,
            ),
            limit=10,
        )
    )

    assert [task.external_id for task in result] == ["ISS-ELIGIBLE"]


def test_fetch_tasks_paginates_with_clamp_to_250_aggregating_to_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    page1 = _issues_response_body(
        [_issue_node(issue_id=f"P1-{i}") for i in range(250)],
        has_next=True,
        end_cursor="cur-1",
    )
    page2 = _issues_response_body(
        [_issue_node(issue_id=f"P2-{i}") for i in range(250)],
        has_next=True,
        end_cursor="cur-2",
    )
    page3 = _issues_response_body(
        [_issue_node(issue_id=f"P3-{i}") for i in range(100)],
        has_next=False,
        end_cursor=None,
    )
    fake, calls = _scripted_http_requester([page1, page2, page3])
    tracker = LinearTracker(_make_config(max_pages=4), http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=600))

    assert len(result) == 600
    assert len(calls) == 3
    assert calls[0]["variables"]["first"] == 250
    assert calls[0]["variables"]["after"] is None
    assert calls[1]["variables"]["first"] == 250
    assert calls[1]["variables"]["after"] == "cur-1"
    assert calls[2]["variables"]["first"] == 100
    assert calls[2]["variables"]["after"] == "cur-2"


def test_fetch_tasks_stops_at_max_pages_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    page1 = _issues_response_body(
        [_issue_node(issue_id=f"P1-{i}") for i in range(250)],
        has_next=True,
        end_cursor="cur-1",
    )
    page2 = _issues_response_body(
        [_issue_node(issue_id=f"P2-{i}") for i in range(250)],
        has_next=True,
        end_cursor="cur-2",
    )
    fake, calls = _scripted_http_requester([page1, page2])
    tracker = LinearTracker(_make_config(max_pages=2), http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=1000))

    assert len(result) == 500
    assert len(calls) == 2
    warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict) and r.msg.get("event") == "linear_fetch_max_pages_reached"
    ]
    assert len(warnings) == 1
    assert warnings[0]["pages_done"] == 2
    assert warnings[0]["collected"] == 500
    assert warnings[0]["limit"] == 1000


def test_fetch_tasks_filter_includes_task_type_label_when_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        task_type_to_label_id={TaskType.PR_FEEDBACK: "label-prf"},
    )
    fake, calls = _scripted_http_requester([_issues_response_body([])])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.fetch_tasks(
        TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], task_type=TaskType.PR_FEEDBACK, limit=10)
    )

    filter_dict = calls[0]["variables"]["filter"]
    assert filter_dict["labels"] == {"id": {"eq": "label-prf"}}
    assert "and" not in filter_dict


def test_fetch_tasks_filter_combines_label_and_fetch_label_via_and(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        task_type_to_label_id={TaskType.EXECUTE: "label-exec"},
        fetch_label_id="label-fetch",
    )
    fake, calls = _scripted_http_requester([_issues_response_body([])])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.fetch_tasks(
        TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], task_type=TaskType.EXECUTE, limit=10)
    )

    filter_dict = calls[0]["variables"]["filter"]
    assert "and" in filter_dict
    label_clauses = [clause for clause in filter_dict["and"] if "labels" in clause]
    label_ids = sorted(c["labels"]["id"]["eq"] for c in label_clauses)
    assert label_ids == ["label-exec", "label-fetch"]


def test_fetch_tasks_warns_when_task_type_has_no_label_mapping(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    fake, calls = _scripted_http_requester([_issues_response_body([])])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    tracker.fetch_tasks(
        TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], task_type=TaskType.EXECUTE, limit=10)
    )

    filter_dict = calls[0]["variables"]["filter"]
    assert "labels" not in filter_dict
    warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict) and r.msg.get("event") == "linear_task_type_label_missing"
    ]
    assert len(warnings) == 1
    assert warnings[0]["task_type"] == "execute"


def test_fetch_tasks_skips_issue_with_unknown_state_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = _issues_response_body(
        [
            _issue_node(issue_id="GOOD", state_type="unstarted"),
            _issue_node(issue_id="WEIRD", state_type="custom-blocked"),
        ]
    )
    fake, _ = _scripted_http_requester([body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=50))

    assert [task.external_id for task in result] == ["GOOD"]


def test_fetch_tasks_assigns_task_type_via_reverse_label_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        task_type_to_label_id={TaskType.PR_FEEDBACK: "label-prf"},
    )
    issue = _issue_node(
        issue_id="ISS-2",
        label_nodes=[
            {"id": "label-prf", "name": "pr-feedback"},
            {"id": "other", "name": "misc"},
        ],
    )
    fake, _ = _scripted_http_requester([_issues_response_body([issue])])
    tracker = LinearTracker(config, http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=10))

    assert len(result) == 1
    assert result[0].task_type is TaskType.PR_FEEDBACK


def test_fetch_tasks_handles_invalid_input_payload_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    description = (
        "header\n\n"
        + INPUT_BLOCK_OPEN
        + "\n"
        + json.dumps({"input": {"unknown_field": "boom"}})
        + "\n"
        + INPUT_BLOCK_CLOSE
    )
    issue = _issue_node(issue_id="ISS-3", description=description)
    fake, _ = _scripted_http_requester([_issues_response_body([issue])])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=10))

    assert len(result) == 1
    assert result[0].input_payload is None
    invalid_warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict) and r.msg.get("event") == "linear_input_payload_invalid"
    ]
    assert len(invalid_warnings) == 1
    assert invalid_warnings[0]["issue_id"] == "ISS-3"


def _issue_create_response_body(
    *,
    issue_id: str = "ISS-NEW",
    url: str = "https://linear.app/team/issue/ISS-NEW",
    success: bool = True,
) -> bytes:
    return json.dumps(
        {
            "data": {
                "issueCreate": {
                    "success": success,
                    "issue": {"id": issue_id, "url": url} if success else None,
                }
            }
        }
    ).encode("utf-8")


def _create_payload(
    *,
    title: str = "Implement X",
    description: str | None = None,
    status: TaskStatus = TaskStatus.NEW,
    task_type: TaskType | None = None,
    input_payload: TaskInputPayload | None = None,
    repo_url: str | None = None,
    repo_ref: str | None = None,
    workspace_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TrackerTaskCreatePayload:
    return TrackerTaskCreatePayload(
        context=TaskContext(title=title, description=description),
        status=status,
        task_type=task_type,
        input_payload=input_payload,
        repo_url=repo_url,
        repo_ref=repo_ref,
        workspace_key=workspace_key,
        metadata=metadata or {},
    )


def test_create_task_uses_explicit_state_id_without_calling_team_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "explicit-new-id"},
    )
    fake, calls = _scripted_http_requester(
        [_issue_create_response_body(issue_id="ISS-100", url="https://linear.app/i/100")]
    )
    tracker = LinearTracker(config, http_requester=fake)

    ref = tracker.create_task(_create_payload(title="Hello", description="Body"))

    assert ref.external_id == "ISS-100"
    assert ref.url == "https://linear.app/i/100"
    assert len(calls) == 1
    input_vars = calls[0]["variables"]["input"]
    assert input_vars["teamId"] == "team-1"
    assert input_vars["title"] == "Hello"
    assert input_vars["description"] == "Body"
    assert input_vars["stateId"] == "explicit-new-id"
    assert "labelIds" not in input_vars
    assert "parentId" not in input_vars


def test_create_task_omits_description_when_none_and_no_block_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "explicit-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(description=None))

    input_vars = calls[0]["variables"]["input"]
    assert "description" not in input_vars


def test_create_task_includes_label_ids_when_task_type_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
        task_type_to_label_id={TaskType.PR_FEEDBACK: "label-prf"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(task_type=TaskType.PR_FEEDBACK))

    assert calls[0]["variables"]["input"]["labelIds"] == ["label-prf"]


def test_create_task_skips_label_ids_when_task_type_has_no_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(task_type=TaskType.EXECUTE))

    assert "labelIds" not in calls[0]["variables"]["input"]


def test_create_task_uses_metadata_team_id_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(metadata={"linear_team_id": "team-override"}))

    assert calls[0]["variables"]["input"]["teamId"] == "team-override"


def test_create_task_falls_back_to_team_states_when_no_explicit_state_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    states_body = _states_response_body(
        [
            {"id": "unstarted-late", "name": "Backlog Top", "type": "unstarted", "position": 200.0},
            {"id": "unstarted-early", "name": "Todo", "type": "unstarted", "position": 50.0},
        ]
    )
    fake, calls = _scripted_http_requester(
        [states_body, _issue_create_response_body(issue_id="ISS-FB")]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    ref = tracker.create_task(_create_payload(description="Body"))

    assert ref.external_id == "ISS-FB"
    # first call resolves states, second is the mutation
    assert len(calls) == 2
    assert calls[1]["variables"]["input"]["stateId"] == "unstarted-early"


def test_create_task_injects_input_block_with_repo_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    payload = _create_payload(
        description="Body text",
        input_payload=TaskInputPayload(
            instructions="run", base_branch="main", branch_name="feat/x"
        ),
        repo_url="https://example.test/repo",
        repo_ref="main",
        workspace_key="ws-1",
    )

    tracker.create_task(payload)

    sent_description = calls[0]["variables"]["input"]["description"]
    assert sent_description.startswith("Body text")
    assert INPUT_BLOCK_OPEN in sent_description
    cleaned, parsed = _extract_input_block(sent_description)
    assert cleaned == "Body text"
    assert parsed == {
        "repo_url": "https://example.test/repo",
        "repo_ref": "main",
        "workspace_key": "ws-1",
        "input": {
            "instructions": "run",
            "base_branch": "main",
            "branch_name": "feat/x",
        },
    }


def test_create_task_preserves_estimate_and_selection_metadata_in_hidden_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(
        _create_payload(
            description="Body text",
            repo_url="https://example.test/repo",
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {"taken_in_work": False},
                "linear_team_id": "team-override",
            },
        )
    )

    input_vars = calls[0]["variables"]["input"]
    assert input_vars["teamId"] == "team-override"
    cleaned, parsed = _extract_input_block(input_vars["description"])
    assert cleaned == "Body text"
    assert parsed == {
        "repo_url": "https://example.test/repo",
        "estimate": {"story_points": 2, "can_take_in_work": True},
        "selection": {"taken_in_work": False},
    }


def test_create_subtask_preserves_estimate_and_selection_metadata_in_hidden_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body(issue_id="SUB-EST")])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_subtask(
        TrackerSubtaskCreatePayload(
            parent_external_id="ISS-PARENT",
            context=TaskContext(title="Selected subtask", description="Body"),
            status=TaskStatus.NEW,
            metadata={
                "estimate": {"story_points": 2, "can_take_in_work": True},
                "selection": {
                    "taken_in_work": False,
                    "selected_from_parent_external_id": "ISS-PARENT",
                },
            },
        )
    )

    input_vars = calls[0]["variables"]["input"]
    assert input_vars["parentId"] == "ISS-PARENT"
    cleaned, parsed = _extract_input_block(input_vars["description"])
    assert cleaned == "Body"
    assert parsed == {
        "estimate": {"story_points": 2, "can_take_in_work": True},
        "selection": {
            "taken_in_work": False,
            "selected_from_parent_external_id": "ISS-PARENT",
        },
    }


def test_create_task_injects_block_when_description_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(description=None, repo_url="https://example.test/repo"))

    sent_description = calls[0]["variables"]["input"]["description"]
    cleaned, parsed = _extract_input_block(sent_description)
    assert cleaned == ""
    assert parsed == {"repo_url": "https://example.test/repo"}


def test_create_task_warns_when_description_exceeds_threshold(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
        description_warn_threshold=50_000,
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    long_description = "x" * 60_000
    tracker.create_task(
        _create_payload(
            title="Long one",
            description=long_description,
            repo_url="https://example.test/repo",
        )
    )

    # mutation must still be sent (warning is non-blocking)
    assert len(calls) == 1
    sent_description = calls[0]["variables"]["input"]["description"]
    assert len(sent_description) > 60_000

    warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict)
        and r.msg.get("event") == "linear_description_warn_threshold_exceeded"
    ]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["title"] == "Long one"
    assert warning["threshold"] == 50_000
    assert warning["description_length"] == len(sent_description)
    assert warning["block_length"] > 0


def test_create_task_warns_for_long_description_without_block(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
        description_warn_threshold=50_000,
    )
    fake, _ = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(description="x" * 60_000))

    warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict)
        and r.msg.get("event") == "linear_description_warn_threshold_exceeded"
    ]
    assert len(warnings) == 1
    assert warnings[0]["block_length"] == 0


def test_create_task_does_not_warn_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    caplog.set_level("WARNING")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
        description_warn_threshold=50_000,
    )
    fake, _ = _scripted_http_requester([_issue_create_response_body()])
    tracker = LinearTracker(config, http_requester=fake)

    tracker.create_task(_create_payload(description="short", repo_url="https://example.test/repo"))

    warnings = [
        r.msg
        for r in caplog.records
        if isinstance(r.msg, dict)
        and r.msg.get("event") == "linear_description_warn_threshold_exceeded"
    ]
    assert warnings == []


def test_create_subtask_includes_parent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, calls = _scripted_http_requester([_issue_create_response_body(issue_id="SUB-1")])
    tracker = LinearTracker(config, http_requester=fake)

    payload = TrackerSubtaskCreatePayload(
        context=TaskContext(title="Sub", description="Body"),
        status=TaskStatus.NEW,
        parent_external_id="ISS-PARENT",
    )

    ref = tracker.create_subtask(payload)

    assert ref.external_id == "SUB-1"
    input_vars = calls[0]["variables"]["input"]
    assert input_vars["parentId"] == "ISS-PARENT"
    assert input_vars["title"] == "Sub"
    assert input_vars["stateId"] == "state-new"


def test_create_task_raises_when_response_success_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    fake, _ = _scripted_http_requester([_issue_create_response_body(success=False)])
    tracker = LinearTracker(config, http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.create_task(_create_payload(description="Body"))

    assert "success=false" in str(exc_info.value)


def test_create_task_raises_when_issue_payload_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps({"data": {"issueCreate": {"success": True, "issue": None}}}).encode("utf-8")
    fake, _ = _scripted_http_requester([body])
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.NEW: "state-new"},
    )
    tracker = LinearTracker(config, http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.create_task(_create_payload(description="Body"))

    assert "issue" in str(exc_info.value)


def _comment_create_response_body(*, comment_id: str = "cmt-1", success: bool = True) -> bytes:
    return json.dumps(
        {
            "data": {
                "commentCreate": {
                    "success": success,
                    "comment": {"id": comment_id} if success else None,
                }
            }
        }
    ).encode("utf-8")


def _issue_update_response_body(
    *,
    issue_id: str = "ISS-1",
    url: str | None = "https://linear.app/team/issue/ISS-1",
    success: bool = True,
) -> bytes:
    return json.dumps(
        {
            "data": {
                "issueUpdate": {
                    "success": success,
                    "issue": {"id": issue_id, "url": url} if success else None,
                }
            }
        }
    ).encode("utf-8")


def _attachment_create_response_body(
    *,
    attachment_id: str = "att-1",
    url: str = "https://example.test/pr/1",
    success: bool = True,
) -> bytes:
    return json.dumps(
        {
            "data": {
                "attachmentCreate": {
                    "success": success,
                    "attachment": ({"id": attachment_id, "url": url} if success else None),
                }
            }
        }
    ).encode("utf-8")


def test_add_comment_sends_issue_id_and_body_and_returns_comment_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    fake, calls = _scripted_http_requester([_comment_create_response_body(comment_id="cmt-42")])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    ref = tracker.add_comment(
        TrackerCommentCreatePayload(external_task_id="ISS-7", body="Hello from worker")
    )

    assert ref.comment_id == "cmt-42"
    assert len(calls) == 1
    input_vars = calls[0]["variables"]["input"]
    assert input_vars == {"issueId": "ISS-7", "body": "Hello from worker"}


def test_add_comment_raises_when_response_success_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    fake, _ = _scripted_http_requester([_comment_create_response_body(success=False)])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.add_comment(TrackerCommentCreatePayload(external_task_id="ISS-1", body="x"))

    assert "success=false" in str(exc_info.value)


def test_add_comment_raises_when_comment_payload_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps({"data": {"commentCreate": {"success": True, "comment": None}}}).encode(
        "utf-8"
    )
    fake, _ = _scripted_http_requester([body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.add_comment(TrackerCommentCreatePayload(external_task_id="ISS-1", body="x"))

    assert "comment" in str(exc_info.value)


def test_add_comment_raises_when_comment_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps({"data": {"commentCreate": {"success": True, "comment": {"id": ""}}}}).encode(
        "utf-8"
    )
    fake, _ = _scripted_http_requester([body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.add_comment(TrackerCommentCreatePayload(external_task_id="ISS-1", body="x"))

    assert "comment id" in str(exc_info.value)


def test_update_status_uses_explicit_state_id_without_calling_team_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.DONE: "state-done"},
    )
    fake, calls = _scripted_http_requester(
        [_issue_update_response_body(issue_id="ISS-9", url="https://l/i/9")]
    )
    tracker = LinearTracker(config, http_requester=fake)

    ref = tracker.update_status(
        TrackerStatusUpdatePayload(external_task_id="ISS-9", status=TaskStatus.DONE)
    )

    assert ref.external_id == "ISS-9"
    assert ref.url == "https://l/i/9"
    assert len(calls) == 1
    variables = calls[0]["variables"]
    assert variables["id"] == "ISS-9"
    assert variables["input"] == {"stateId": "state-done"}


def test_update_status_falls_back_to_team_states_when_no_explicit_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    states_body = _states_response_body(
        [
            {"id": "started-late", "name": "WIP", "type": "started", "position": 200.0},
            {"id": "started-early", "name": "Doing", "type": "started", "position": 50.0},
        ]
    )
    fake, calls = _scripted_http_requester(
        [states_body, _issue_update_response_body(issue_id="ISS-9")]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    tracker.update_status(
        TrackerStatusUpdatePayload(external_task_id="ISS-9", status=TaskStatus.PROCESSING)
    )

    assert len(calls) == 2
    assert calls[1]["variables"]["input"] == {"stateId": "started-early"}


def test_update_status_propagates_runtime_error_when_status_unmappable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    states_body = _states_response_body(
        [
            {"id": "started-1", "name": "Doing", "type": "started", "position": 10.0},
        ]
    )
    fake, _ = _scripted_http_requester([states_body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.update_status(
            TrackerStatusUpdatePayload(external_task_id="ISS-1", status=TaskStatus.DONE)
        )

    assert "LINEAR_STATE_ID_DONE" in str(exc_info.value)


def test_update_status_raises_when_response_success_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.DONE: "state-done"},
    )
    fake, _ = _scripted_http_requester([_issue_update_response_body(success=False)])
    tracker = LinearTracker(config, http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.update_status(
            TrackerStatusUpdatePayload(external_task_id="ISS-1", status=TaskStatus.DONE)
        )

    assert "success=false" in str(exc_info.value)


def test_update_status_returns_reference_without_url_when_response_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.DONE: "state-done"},
    )
    fake, _ = _scripted_http_requester([_issue_update_response_body(url=None)])
    tracker = LinearTracker(config, http_requester=fake)

    ref = tracker.update_status(
        TrackerStatusUpdatePayload(external_task_id="ISS-1", status=TaskStatus.DONE)
    )

    assert ref.external_id == "ISS-1"
    assert ref.url is None


def test_attach_links_sends_one_mutation_per_link_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    fake, calls = _scripted_http_requester(
        [
            _attachment_create_response_body(
                attachment_id="att-1", url="https://example.test/pr/1"
            ),
            _attachment_create_response_body(
                attachment_id="att-2", url="https://example.test/pr/2"
            ),
            _attachment_create_response_body(
                attachment_id="att-3", url="https://example.test/pr/3"
            ),
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    ref = tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id="ISS-5",
            links=[
                TaskLink(label="PR #1", url="https://example.test/pr/1"),
                TaskLink(label="PR #2", url="https://example.test/pr/2"),
                TaskLink(label="PR #3", url="https://example.test/pr/3"),
            ],
        )
    )

    assert ref.external_id == "ISS-5"
    assert ref.url is None
    assert len(calls) == 3
    for index, call in enumerate(calls, start=1):
        input_vars = call["variables"]["input"]
        assert input_vars == {
            "issueId": "ISS-5",
            "url": f"https://example.test/pr/{index}",
            "title": f"PR #{index}",
        }


def test_attach_links_with_single_link_sends_one_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    fake, calls = _scripted_http_requester(
        [_attachment_create_response_body(url="https://example.test/x")]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    tracker.attach_links(
        TrackerLinksAttachPayload(
            external_task_id="ISS-1",
            links=[TaskLink(label="X", url="https://example.test/x")],
        )
    )

    assert len(calls) == 1
    assert calls[0]["variables"]["input"] == {
        "issueId": "ISS-1",
        "url": "https://example.test/x",
        "title": "X",
    }


def test_attach_links_is_idempotent_on_repeat_call_with_same_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    # Linear returns success=true on duplicate (issueId, url) — it just
    # updates the existing attachment instead of creating a new one.
    fake, calls = _scripted_http_requester(
        [
            _attachment_create_response_body(
                attachment_id="att-1", url="https://example.test/pr/1"
            ),
            _attachment_create_response_body(
                attachment_id="att-1", url="https://example.test/pr/1"
            ),
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    payload = TrackerLinksAttachPayload(
        external_task_id="ISS-3",
        links=[TaskLink(label="PR #1", url="https://example.test/pr/1")],
    )

    tracker.attach_links(payload)
    tracker.attach_links(payload)

    assert len(calls) == 2
    for call in calls:
        assert call["variables"]["input"]["url"] == "https://example.test/pr/1"


def test_attach_links_raises_with_url_when_attachment_create_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    fake, _ = _scripted_http_requester(
        [
            _attachment_create_response_body(url="https://example.test/ok"),
            _attachment_create_response_body(url="https://example.test/bad", success=False),
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(RuntimeError) as exc_info:
        tracker.attach_links(
            TrackerLinksAttachPayload(
                external_task_id="ISS-1",
                links=[
                    TaskLink(label="ok", url="https://example.test/ok"),
                    TaskLink(label="bad", url="https://example.test/bad"),
                ],
            )
        )

    message = str(exc_info.value)
    assert "https://example.test/bad" in message
    assert "success=false" in message


def _make_http_error(
    *, code: int, body: bytes = b"", url: str = "https://api.linear.app/graphql"
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url,
        code,
        "rate-limited" if code == 429 else "err",
        {},
        io.BytesIO(body),  # type: ignore[arg-type]
    )


def test_linear_rate_limit_error_is_runtime_error_subclass() -> None:
    # Worker 1 catches generic Exception and re-raises; downstream consumers
    # may also rely on `except RuntimeError`. Subclass invariant guarantees
    # both still pick up rate-limit errors.
    assert issubclass(LinearRateLimitError, RuntimeError)


def test_graphql_client_rate_limit_on_urllib_http_error_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    def http_requester(req: urllib.request.Request, _t: float) -> Any:
        raise _make_http_error(code=429)

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=http_requester,
    )

    with pytest.raises(LinearRateLimitError) as exc_info:
        client.execute("q", {})

    assert "429" in str(exc_info.value)


def test_graphql_client_rate_limit_on_http_error_400_with_ratelimited_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Linear may surface RATELIMITED as HTTP 400 with structured GraphQL
    # errors in the body. Adapter must treat that as rate-limit, not a generic
    # 400 RuntimeError.
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps(
        {
            "errors": [
                {
                    "message": "rate limit exceeded",
                    "extensions": {"code": "RATELIMITED"},
                }
            ]
        }
    ).encode("utf-8")

    def http_requester(req: urllib.request.Request, _t: float) -> Any:
        raise _make_http_error(code=400, body=body)

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=http_requester,
    )

    with pytest.raises(LinearRateLimitError) as exc_info:
        client.execute("q", {})

    assert "RATELIMITED" in str(exc_info.value)


def test_graphql_client_runtime_error_on_http_error_500_without_ratelimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps(
        {"errors": [{"message": "internal", "extensions": {"code": "INTERNAL"}}]}
    ).encode("utf-8")

    def http_requester(req: urllib.request.Request, _t: float) -> Any:
        raise _make_http_error(code=500, body=body)

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=http_requester,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("q", {})

    assert not isinstance(exc_info.value, LinearRateLimitError)
    assert "500" in str(exc_info.value)


def test_graphql_client_url_error_is_runtime_error_not_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")

    def http_requester(req: urllib.request.Request, _t: float) -> Any:
        raise urllib.error.URLError("connection timed out")

    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=http_requester,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.execute("q", {})

    assert not isinstance(exc_info.value, LinearRateLimitError)
    assert "transport" in str(exc_info.value)
    assert "connection timed out" in str(exc_info.value)


def test_graphql_client_rate_limit_takes_priority_over_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps(
        {
            "errors": [
                {"message": "field error", "extensions": {"code": "INVALID_INPUT"}},
                {"message": "rate limit", "extensions": {"code": "RATELIMITED"}},
            ]
        }
    ).encode("utf-8")
    client = _GraphqlClient(
        api_url="https://api.linear.app/graphql",
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(body),
    )

    with pytest.raises(LinearRateLimitError):
        client.execute("q", {})


def test_graphql_client_rate_limit_message_contains_endpoint_and_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "lin_api_z9y8x7w6v5u4t3s2"
    monkeypatch.setenv("LINEAR_API_KEY_TEST", secret)
    body = json.dumps({"errors": [{"extensions": {"code": "RATELIMITED"}}]}).encode("utf-8")
    endpoint = "https://api.linear.app/graphql"
    client = _GraphqlClient(
        api_url=endpoint,
        token_env_var="LINEAR_API_KEY_TEST",
        timeout_seconds=30,
        http_requester=lambda req, t: _FakeResponse(body),
    )

    with pytest.raises(LinearRateLimitError) as exc_info:
        client.execute("q", {})

    message = str(exc_info.value)
    assert endpoint in message
    assert secret not in message


def test_fetch_tasks_propagates_linear_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Worker 1 polling path: Linear answers the very first issues query with
    # a RATELIMITED extension code. fetch_tasks must surface
    # LinearRateLimitError so tracker_intake can log it and re-raise.
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    body = json.dumps({"errors": [{"extensions": {"code": "RATELIMITED"}}]}).encode("utf-8")
    fake, _ = _scripted_http_requester([body])
    tracker = LinearTracker(_make_config(), http_requester=fake)

    with pytest.raises(LinearRateLimitError):
        tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW], limit=10))


def test_update_status_propagates_linear_rate_limit_error_on_http_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Worker 3 deliver path: rate-limit on the issueUpdate mutation must
    # propagate as LinearRateLimitError so the orchestrator can decide to
    # retry on the next cycle instead of silently swallowing the failure.
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "lin_api_irrelevant")
    config = _make_config(
        explicit_status_to_state_id={TaskStatus.DONE: "state-done"},
    )

    def http_requester(req: urllib.request.Request, _t: float) -> Any:
        raise _make_http_error(code=429)

    tracker = LinearTracker(config, http_requester=http_requester)

    with pytest.raises(LinearRateLimitError):
        tracker.update_status(
            TrackerStatusUpdatePayload(external_task_id="ISS-1", status=TaskStatus.DONE)
        )
