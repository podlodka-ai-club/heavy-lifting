from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.logging_setup import get_logger
from backend.schemas import (
    TrackerCommentCreatePayload,
    TrackerCommentReference,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskCreatePayload,
    TrackerTaskReference,
)
from backend.task_constants import TaskStatus, TaskType

HttpRequester = Callable[[urllib.request.Request, float], Any]

INPUT_BLOCK_OPEN = "<!-- heavy-lifting:input -->"
INPUT_BLOCK_CLOSE = "<!-- /heavy-lifting:input -->"

_logger = get_logger(component="linear_tracker")


class LinearRateLimitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LinearTrackerConfig:
    api_url: str
    token_env_var: str
    team_id: str
    timeout_seconds: int
    fetch_label_id: str | None
    explicit_status_to_state_id: Mapping[TaskStatus, str]
    fetch_state_types: tuple[str, ...]
    task_type_to_label_id: Mapping[TaskType, str]
    max_pages: int
    description_warn_threshold: int


def _default_http_requester(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _extract_input_block(description: str | None) -> tuple[str, dict[str, Any] | None]:
    if not description:
        return description or "", None

    open_idx = description.find(INPUT_BLOCK_OPEN)
    if open_idx == -1:
        return description, None

    close_search_from = open_idx + len(INPUT_BLOCK_OPEN)
    close_idx = description.find(INPUT_BLOCK_CLOSE, close_search_from)
    if close_idx == -1:
        return description, None

    body = description[close_search_from:close_idx].strip()
    before = description[:open_idx].rstrip()
    after = description[close_idx + len(INPUT_BLOCK_CLOSE):].lstrip()
    cleaned = (before + ("\n" if before and after else "") + after).strip()

    try:
        parsed = json.loads(body) if body else None
    except json.JSONDecodeError as exc:
        _logger.warning(
            "linear_input_block_invalid_json",
            error=str(exc),
            body_length=len(body),
        )
        return cleaned, None

    if not isinstance(parsed, dict):
        _logger.warning(
            "linear_input_block_not_object",
            body_length=len(body),
        )
        return cleaned, None

    return cleaned, parsed


def _inject_input_block(description: str | None, payload_dict: Mapping[str, Any]) -> str:
    block = (
        INPUT_BLOCK_OPEN
        + "\n"
        + json.dumps(dict(payload_dict), ensure_ascii=False, indent=2)
        + "\n"
        + INPUT_BLOCK_CLOSE
    )
    if not description:
        return block
    return description.rstrip() + "\n\n" + block


class _GraphqlClient:
    def __init__(
        self,
        *,
        api_url: str,
        token_env_var: str,
        timeout_seconds: int,
        http_requester: HttpRequester,
    ) -> None:
        self._api_url = api_url
        self._token_env_var = token_env_var
        self._timeout_seconds = timeout_seconds
        self._http_requester = http_requester

    def execute(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        token = os.getenv(self._token_env_var)
        if not token:
            raise RuntimeError(
                f"LINEAR token env var {self._token_env_var} is empty"
            )

        body = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
        request = urllib.request.Request(
            self._api_url,
            data=body,
            method="POST",
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
        )

        try:
            response = self._http_requester(request, float(self._timeout_seconds))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise LinearRateLimitError(
                    f"Linear GraphQL rate-limited (HTTP 429) at {self._api_url}"
                ) from None
            raise RuntimeError(
                f"Linear GraphQL HTTP {exc.code} at {self._api_url}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Linear GraphQL transport error at {self._api_url}: {exc.reason}"
            ) from None

        try:
            raw = response.read()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        status = getattr(response, "status", 200)
        if status >= 400:
            if status == 429:
                raise LinearRateLimitError(
                    f"Linear GraphQL rate-limited (HTTP 429) at {self._api_url}"
                )
            raise RuntimeError(f"Linear GraphQL HTTP {status} at {self._api_url}")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Linear GraphQL invalid JSON response at {self._api_url}: {exc}"
            ) from None

        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            for error in errors:
                if not isinstance(error, dict):
                    continue
                extensions = error.get("extensions")
                if isinstance(extensions, dict) and extensions.get("code") == "RATELIMITED":
                    raise LinearRateLimitError(
                        f"Linear GraphQL rate-limited (RATELIMITED) at {self._api_url}"
                    )
            raise RuntimeError(
                f"Linear GraphQL errors at {self._api_url}: "
                f"{self._summarize_errors(errors)}"
            )

        data = payload.get("data") if isinstance(payload, dict) else None
        if data is None:
            raise RuntimeError(
                f"Linear GraphQL response missing data at {self._api_url}"
            )
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Linear GraphQL response data is not an object at {self._api_url}"
            )
        return data

    @staticmethod
    def _summarize_errors(errors: list[Any]) -> str:
        messages: list[str] = []
        for error in errors:
            if isinstance(error, dict):
                msg = error.get("message")
                if isinstance(msg, str):
                    messages.append(msg)
        return "; ".join(messages) or "<no message>"


class LinearTracker:
    def __init__(
        self,
        config: LinearTrackerConfig,
        *,
        http_requester: HttpRequester | None = None,
    ) -> None:
        self._config = config
        self._client = _GraphqlClient(
            api_url=config.api_url,
            token_env_var=config.token_env_var,
            timeout_seconds=config.timeout_seconds,
            http_requester=http_requester or _default_http_requester,
        )

    def __repr__(self) -> str:
        return (
            f"LinearTracker(api_url={self._config.api_url!r}, "
            f"team_id={self._config.team_id!r})"
        )

    def fetch_tasks(self, query: TrackerFetchTasksQuery) -> list[TrackerTask]:
        raise NotImplementedError("fetch_tasks will be implemented in task04")

    def create_task(self, payload: TrackerTaskCreatePayload) -> TrackerTaskReference:
        raise NotImplementedError("create_task will be implemented in task05")

    def create_subtask(self, payload: TrackerSubtaskCreatePayload) -> TrackerTaskReference:
        raise NotImplementedError("create_subtask will be implemented in task05")

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference:
        raise NotImplementedError("add_comment will be implemented in task06")

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference:
        raise NotImplementedError("update_status will be implemented in task06")

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference:
        raise NotImplementedError("attach_links will be implemented in task06")


__all__ = [
    "HttpRequester",
    "LinearRateLimitError",
    "LinearTracker",
    "LinearTrackerConfig",
]
