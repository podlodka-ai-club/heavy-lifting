"""Provenance round-trip tests for ``LinearTracker`` (task18a §6.7a).

The Linear adapter must:

* attach our own links with ``subtitle="heavy-lifting:own-write"`` so a
  follow-up fetch can recognise them as own-writes;
* map fetched attachments back to ``TaskLink.origin`` based on that subtitle:
  ``"own_write"`` when the marker is present, ``"user"`` otherwise.

This file exercises the read path (``_to_tracker_task`` via ``fetch_tasks``)
to guarantee the round-trip. The write path (``attach_links``) is covered by
``test_linear_tracker.py``.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from backend.adapters.linear_tracker import LinearTracker, LinearTrackerConfig
from backend.schemas import TrackerFetchTasksQuery
from backend.task_constants import TaskStatus

_OWN_WRITE_SUBTITLE = "heavy-lifting:own-write"


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

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        return None


def _issue_with_attachments(attachment_nodes: list[dict[str, Any]]) -> bytes:
    issue = {
        "id": "ISS-1",
        "parent": None,
        "title": "Test",
        "description": None,
        "state": {"id": "s1", "type": "unstarted", "name": "Todo"},
        "labels": {"nodes": []},
        "attachments": {"nodes": attachment_nodes},
        "url": "https://linear.app/team/issue/ISS-1",
    }
    return json.dumps(
        {
            "data": {
                "issues": {
                    "nodes": [issue],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    ).encode("utf-8")


def _scripted_requester(body: bytes) -> Any:
    def fake(_req: urllib.request.Request, _timeout: float) -> _FakeResponse:
        return _FakeResponse(body)

    return fake


def test_to_tracker_task_marks_own_write_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "irrelevant")
    body = _issue_with_attachments(
        [
            {
                "url": "https://example.test/pr/1",
                "title": "PR #1",
                "subtitle": _OWN_WRITE_SUBTITLE,
            }
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=_scripted_requester(body))

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW]))

    assert len(result) == 1
    refs = result[0].context.references
    assert len(refs) == 1
    assert refs[0].origin == "own_write"


def test_to_tracker_task_marks_user_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "irrelevant")
    body = _issue_with_attachments(
        [
            {
                "url": "https://example.test/spec",
                "title": "API spec",
                "subtitle": "user_uploaded",
            }
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=_scripted_requester(body))

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW]))

    assert result[0].context.references[0].origin == "user"


def test_to_tracker_task_marks_attachment_without_subtitle_as_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY_TEST", "irrelevant")
    body = _issue_with_attachments(
        [{"url": "https://example.test/file", "title": "File"}]
    )
    tracker = LinearTracker(_make_config(), http_requester=_scripted_requester(body))

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW]))

    assert result[0].context.references[0].origin == "user"


def test_collision_label_pull_request_without_marker_stays_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-uploaded file titled ``pull_request`` must stay ``origin="user"``.

    The provenance is the marker (``subtitle``), not the title — without this
    rule the user could collide our naming and be silently filtered out of
    the re-triage hash.
    """

    monkeypatch.setenv("LINEAR_API_KEY_TEST", "irrelevant")
    body = _issue_with_attachments(
        [
            {
                "url": "https://attacker.example/file",
                "title": "pull_request",
                "subtitle": None,
            }
        ]
    )
    tracker = LinearTracker(_make_config(), http_requester=_scripted_requester(body))

    result = tracker.fetch_tasks(TrackerFetchTasksQuery(statuses=[TaskStatus.NEW]))

    assert result[0].context.references[0].origin == "user"
