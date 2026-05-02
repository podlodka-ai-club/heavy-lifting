from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.logging_setup import get_logger
from backend.schemas import (
    TaskContext,
    TaskInputPayload,
    TaskLink,
    TrackerCommentCreatePayload,
    TrackerCommentPayload,
    TrackerCommentReference,
    TrackerFetchTasksQuery,
    TrackerLinksAttachPayload,
    TrackerReadCommentsQuery,
    TrackerReadCommentsResult,
    TrackerStatusUpdatePayload,
    TrackerSubtaskCreatePayload,
    TrackerTask,
    TrackerTaskCreatePayload,
    TrackerTaskReference,
    TrackerTaskSelectionClaimPayload,
)
from backend.task_constants import TaskStatus, TaskType
from backend.tracker_metadata import matches_estimated_selection

HttpRequester = Callable[[urllib.request.Request, float], Any]

INPUT_BLOCK_OPEN = "<!-- heavy-lifting:input -->"
INPUT_BLOCK_CLOSE = "<!-- /heavy-lifting:input -->"
COMMENT_METADATA_OPEN = "<!-- heavy-lifting:comment-meta -->"
COMMENT_METADATA_CLOSE = "<!-- /heavy-lifting:comment-meta -->"
_HIDDEN_METADATA_KEYS = frozenset({"estimate", "selection"})

_logger = get_logger(component="linear_tracker")

_WORKFLOW_STATES_QUERY = """
query LinearTeamStates($id: String!) {
  team(id: $id) {
    states {
      nodes {
        id
        name
        type
        position
      }
    }
  }
}
""".strip()

_STATE_TYPE_TO_TASK_STATUS: Mapping[str, TaskStatus] = {
    "triage": TaskStatus.NEW,
    "backlog": TaskStatus.NEW,
    "unstarted": TaskStatus.NEW,
    "started": TaskStatus.PROCESSING,
    "completed": TaskStatus.DONE,
    "canceled": TaskStatus.FAILED,
}

_TASK_STATUS_TO_FALLBACK_TYPES: Mapping[TaskStatus, tuple[str, ...]] = {
    TaskStatus.NEW: ("unstarted", "backlog"),
    TaskStatus.PROCESSING: ("started",),
    TaskStatus.DONE: ("completed",),
    TaskStatus.FAILED: ("canceled",),
}

_TASK_STATUS_TO_ENV_HINT: Mapping[TaskStatus, str] = {
    TaskStatus.NEW: "LINEAR_STATE_ID_NEW",
    TaskStatus.PROCESSING: "LINEAR_STATE_ID_PROCESSING",
    TaskStatus.DONE: "LINEAR_STATE_ID_DONE",
    TaskStatus.FAILED: "LINEAR_STATE_ID_FAILED",
}

_LINEAR_PAGE_LIMIT = 250

_FETCH_ISSUES_QUERY = """
query LinearFetchIssues(
  $filter: IssueFilter,
  $first: Int!,
  $after: String,
  $orderBy: PaginationOrderBy
) {
  issues(filter: $filter, first: $first, after: $after, orderBy: $orderBy) {
    nodes {
      id
      parent { id }
      title
      description
      state { id type name }
      labels { nodes { id name } }
      attachments { nodes { url title } }
      url
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()

_ISSUE_DESCRIPTION_QUERY = """
query LinearIssueDescription($id: String!) {
  issue(id: $id) {
    id
    description
  }
}
""".strip()

_ISSUE_CREATE_MUTATION = """
mutation LinearIssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      url
    }
  }
}
""".strip()

_COMMENT_CREATE_MUTATION = """
mutation LinearCommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment {
      id
    }
  }
}
""".strip()

_READ_ISSUE_COMMENTS_QUERY = """
query LinearReadIssueComments($id: String!, $first: Int!, $after: String) {
  issue(id: $id) {
    comments(first: $first, after: $after) {
      nodes {
        id
        body
        url
        user {
          id
          name
          displayName
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
""".strip()

_ISSUE_UPDATE_MUTATION = """
mutation LinearIssueUpdate($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue {
      id
      url
    }
  }
}
""".strip()

_ATTACHMENT_CREATE_MUTATION = """
mutation LinearAttachmentCreate($input: AttachmentCreateInput!) {
  attachmentCreate(input: $input) {
    success
    attachment {
      id
      url
    }
  }
}
""".strip()


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
    after = description[close_idx + len(INPUT_BLOCK_CLOSE) :].lstrip()
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


def _extract_comment_metadata(body: str | None) -> tuple[str, dict[str, Any] | None]:
    if not body:
        return body or "", None

    open_idx = body.find(COMMENT_METADATA_OPEN)
    if open_idx == -1:
        return body, None

    close_search_from = open_idx + len(COMMENT_METADATA_OPEN)
    close_idx = body.find(COMMENT_METADATA_CLOSE, close_search_from)
    if close_idx == -1:
        return body, None

    metadata_text = body[close_search_from:close_idx].strip()
    before = body[:open_idx].rstrip()
    after = body[close_idx + len(COMMENT_METADATA_CLOSE) :].lstrip()
    cleaned = (before + ("\n" if before and after else "") + after).strip()
    if not metadata_text:
        return cleaned, None
    try:
        parsed = json.loads(metadata_text)
    except json.JSONDecodeError:
        return cleaned, None
    return cleaned, dict(parsed) if isinstance(parsed, dict) else None


def _inject_comment_metadata(body: str, metadata: Mapping[str, Any]) -> str:
    if not metadata:
        return body
    metadata_block = (
        COMMENT_METADATA_OPEN
        + "\n"
        + json.dumps(dict(metadata), ensure_ascii=False, indent=2)
        + "\n"
        + COMMENT_METADATA_CLOSE
    )
    if not body:
        return metadata_block
    return body.rstrip() + "\n\n" + metadata_block


def _copy_json_mapping(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _extract_hidden_block_metadata(
    payload_dict: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, str | None, dict[str, Any] | None, dict[str, Any]]:
    if not payload_dict:
        return None, None, None, None, {}

    def _opt_str(key: str) -> str | None:
        value = payload_dict.get(key)
        return value if isinstance(value, str) and value else None

    return (
        _opt_str("repo_url"),
        _opt_str("repo_ref"),
        _opt_str("workspace_key"),
        _copy_json_mapping(payload_dict.get("input")),
        {
            key: value
            for key, value in payload_dict.items()
            if key in _HIDDEN_METADATA_KEYS and isinstance(value, dict)
        },
    )


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
            raise RuntimeError(f"LINEAR token env var {self._token_env_var} is empty")

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
            # HTTPError IS a response — Linear may return RATELIMITED in the body
            # even on HTTP 400, so read the body before deciding which class
            # of error to raise.
            response = exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Linear GraphQL transport error at {self._api_url}: {exc.reason}"
            ) from None

        try:
            raw = response.read() or b""
        except Exception:
            raw = b""
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        status_attr = getattr(response, "status", None)
        if not isinstance(status_attr, int):
            status_attr = getattr(response, "code", 200)
        status: int = status_attr if isinstance(status_attr, int) else 200

        try:
            payload: Any = json.loads(raw.decode("utf-8")) if raw else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None

        errors = payload.get("errors") if isinstance(payload, dict) else None

        if isinstance(errors, list) and self._has_ratelimited(errors):
            raise LinearRateLimitError(
                f"Linear GraphQL rate-limited (RATELIMITED) at {self._api_url}"
            )

        if status == 429:
            raise LinearRateLimitError(f"Linear GraphQL rate-limited (HTTP 429) at {self._api_url}")

        if status >= 400:
            raise RuntimeError(f"Linear GraphQL HTTP {status} at {self._api_url}")

        if isinstance(errors, list) and errors:
            raise RuntimeError(
                f"Linear GraphQL errors at {self._api_url}: {self._summarize_errors(errors)}"
            )

        if payload is None:
            raise RuntimeError(f"Linear GraphQL invalid JSON response at {self._api_url}")

        data = payload.get("data") if isinstance(payload, dict) else None
        if data is None:
            raise RuntimeError(f"Linear GraphQL response missing data at {self._api_url}")
        if not isinstance(data, dict):
            raise RuntimeError(f"Linear GraphQL response data is not an object at {self._api_url}")
        return data

    @staticmethod
    def _has_ratelimited(errors: list[Any]) -> bool:
        for error in errors:
            if not isinstance(error, dict):
                continue
            extensions = error.get("extensions")
            if isinstance(extensions, dict) and extensions.get("code") == "RATELIMITED":
                return True
        return False

    @staticmethod
    def _summarize_errors(errors: list[Any]) -> str:
        messages: list[str] = []
        for error in errors:
            if isinstance(error, dict):
                msg = error.get("message")
                if isinstance(msg, str):
                    messages.append(msg)
        return "; ".join(messages) or "<no message>"


@dataclass(frozen=True, slots=True)
class _WorkflowState:
    id: str
    name: str
    type: str
    position: float


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
        self._workflow_states_by_type: dict[str, list[_WorkflowState]] | None = None

    def __repr__(self) -> str:
        return f"LinearTracker(api_url={self._config.api_url!r}, team_id={self._config.team_id!r})"

    def _resolve_workflow_states(self) -> dict[str, list[_WorkflowState]]:
        if self._workflow_states_by_type is not None:
            return self._workflow_states_by_type

        data = self._client.execute(_WORKFLOW_STATES_QUERY, {"id": self._config.team_id})
        team = data.get("team")
        if not isinstance(team, dict):
            raise RuntimeError(
                f"Linear team {self._config.team_id!r} not found or response missing 'team'"
            )
        states_block = team.get("states")
        if not isinstance(states_block, dict):
            raise RuntimeError(f"Linear team {self._config.team_id!r} response missing 'states'")
        nodes = states_block.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError(f"Linear team {self._config.team_id!r} states.nodes is not a list")

        by_type: dict[str, list[_WorkflowState]] = {}
        for raw in nodes:
            state = self._parse_workflow_state(raw)
            by_type.setdefault(state.type, []).append(state)

        for states in by_type.values():
            states.sort(key=lambda s: s.position)

        self._workflow_states_by_type = by_type
        return by_type

    @staticmethod
    def _parse_workflow_state(raw: Any) -> _WorkflowState:
        if not isinstance(raw, dict):
            raise RuntimeError(f"Linear workflow state entry is not an object: {raw!r}")
        id_ = raw.get("id")
        name = raw.get("name")
        type_ = raw.get("type")
        position = raw.get("position")
        if not isinstance(id_, str) or not isinstance(name, str) or not isinstance(type_, str):
            raise RuntimeError(f"Linear workflow state entry missing id/name/type: {raw!r}")
        if not isinstance(position, int | float) or isinstance(position, bool):
            raise RuntimeError(f"Linear workflow state position is not numeric: {raw!r}")
        return _WorkflowState(id=id_, name=name, type=type_, position=float(position))

    def _status_to_state_id(self, status: TaskStatus) -> str:
        explicit = self._config.explicit_status_to_state_id.get(status)
        if explicit:
            return explicit

        states_by_type = self._resolve_workflow_states()
        fallback_types = _TASK_STATUS_TO_FALLBACK_TYPES.get(status, ())
        for state_type in fallback_types:
            candidates = states_by_type.get(state_type)
            if candidates:
                return candidates[0].id

        env_hint = _TASK_STATUS_TO_ENV_HINT.get(status, "LINEAR_STATE_ID_*")
        raise RuntimeError(
            f"Linear: no workflow state for TaskStatus.{status.name}; "
            f"set {env_hint} env var or ensure team "
            f"{self._config.team_id!r} has a state with type in {fallback_types!r}"
        )

    @staticmethod
    def _state_to_task_status(state_type: str | None) -> TaskStatus | None:
        if not state_type:
            return None
        return _STATE_TYPE_TO_TASK_STATUS.get(state_type)

    def fetch_tasks(self, query: TrackerFetchTasksQuery) -> list[TrackerTask]:
        state_types = self._collect_fetch_state_types(query.statuses)
        if not state_types:
            return []

        filter_dict = self._build_issues_filter(state_types, query.task_type)

        collected: list[TrackerTask] = []
        after: str | None = None
        pages_done = 0
        has_next = True

        while len(collected) < query.limit and has_next and pages_done < self._config.max_pages:
            remaining = query.limit - len(collected)
            first = min(remaining, _LINEAR_PAGE_LIMIT)
            variables: dict[str, Any] = {
                "filter": filter_dict,
                "first": first,
                "after": after,
                "orderBy": "createdAt",
            }
            data = self._client.execute(_FETCH_ISSUES_QUERY, variables)
            issues_block = data.get("issues")
            if not isinstance(issues_block, dict):
                raise RuntimeError("Linear issues response missing 'issues' object")
            nodes = issues_block.get("nodes")
            if not isinstance(nodes, list):
                raise RuntimeError("Linear issues.nodes is not a list")

            for raw_issue in nodes:
                if not isinstance(raw_issue, dict):
                    continue
                tracker_task = self._to_tracker_task(raw_issue)
                if tracker_task is None:
                    continue
                if not matches_estimated_selection(
                    task=tracker_task,
                    selection=query.estimated_selection,
                ):
                    continue
                collected.append(tracker_task)
                if len(collected) >= query.limit:
                    break

            page_info = issues_block.get("pageInfo")
            if isinstance(page_info, dict):
                has_next = bool(page_info.get("hasNextPage"))
                end_cursor = page_info.get("endCursor")
                after = end_cursor if isinstance(end_cursor, str) else None
            else:
                has_next = False
                after = None

            pages_done += 1
            if after is None:
                break

        if has_next and len(collected) < query.limit and pages_done >= self._config.max_pages:
            _logger.warning(
                "linear_fetch_max_pages_reached",
                pages_done=pages_done,
                collected=len(collected),
                limit=query.limit,
                max_pages=self._config.max_pages,
            )

        return collected

    def _collect_fetch_state_types(self, statuses: Sequence[TaskStatus]) -> list[str]:
        desired = set(statuses)
        candidates = [
            state_type
            for state_type, status in _STATE_TYPE_TO_TASK_STATUS.items()
            if status in desired
        ]
        if self._config.fetch_state_types:
            allowed = set(self._config.fetch_state_types)
            candidates = [t for t in candidates if t in allowed]
        return candidates

    def _build_issues_filter(
        self,
        state_types: Sequence[str],
        task_type: TaskType | None,
    ) -> dict[str, Any]:
        label_ids: list[str] = []
        if task_type is not None:
            mapped = self._config.task_type_to_label_id.get(task_type)
            if mapped:
                label_ids.append(mapped)
            else:
                _logger.warning(
                    "linear_task_type_label_missing",
                    task_type=task_type.value,
                )
        if self._config.fetch_label_id:
            label_ids.append(self._config.fetch_label_id)

        state_clause: dict[str, Any] = {"state": {"type": {"in": list(state_types)}}}
        if not label_ids:
            return state_clause
        if len(label_ids) == 1:
            return {**state_clause, "labels": {"id": {"eq": label_ids[0]}}}
        label_clauses = [{"labels": {"id": {"eq": lid}}} for lid in label_ids]
        return {"and": [state_clause, *label_clauses]}

    def _to_tracker_task(self, issue: Mapping[str, Any]) -> TrackerTask | None:
        external_id = issue.get("id")
        if not isinstance(external_id, str) or not external_id:
            return None

        state = issue.get("state")
        state_type = state.get("type") if isinstance(state, dict) else None
        status_type = state_type if isinstance(state_type, str) else None
        status = self._state_to_task_status(status_type)
        if status is None:
            _logger.warning(
                "linear_unknown_state_type",
                state_type=status_type,
                issue_id=external_id,
            )
            return None

        parent = issue.get("parent")
        parent_id_raw = parent.get("id") if isinstance(parent, dict) else None
        parent_id = parent_id_raw if isinstance(parent_id_raw, str) else None

        title_raw = issue.get("title")
        title = title_raw if isinstance(title_raw, str) and title_raw else external_id

        description_raw = issue.get("description")
        description: str | None = description_raw if isinstance(description_raw, str) else None
        cleaned_description_raw, payload_dict = _extract_input_block(description)
        cleaned_description: str | None = cleaned_description_raw or None

        references = self._extract_references(issue.get("attachments"))
        task_type = self._extract_task_type(issue.get("labels"))
        repo_url, repo_ref, workspace_key, input_dict, hidden_metadata = (
            _extract_hidden_block_metadata(payload_dict)
        )
        input_payload = self._extract_input_payload(input_dict, external_id)

        metadata: dict[str, Any] = {"linear_team_id": self._config.team_id}
        issue_url = issue.get("url")
        if isinstance(issue_url, str) and issue_url:
            metadata["linear_issue_url"] = issue_url
        metadata.update(hidden_metadata)

        return TrackerTask(
            external_id=external_id,
            parent_external_id=parent_id,
            status=status,
            task_type=task_type,
            context=TaskContext(
                title=title,
                description=cleaned_description,
                references=references,
            ),
            input_payload=input_payload,
            repo_url=repo_url,
            repo_ref=repo_ref,
            workspace_key=workspace_key,
            metadata=metadata,
        )

    @staticmethod
    def _extract_references(attachments: Any) -> list[TaskLink]:
        nodes = attachments.get("nodes") if isinstance(attachments, dict) else None
        if not isinstance(nodes, list):
            return []
        result: list[TaskLink] = []
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if not isinstance(url, str) or not url:
                continue
            title = raw.get("title")
            label = title if isinstance(title, str) and title else url
            result.append(TaskLink(label=label, url=url))
        return result

    def _extract_task_type(self, labels: Any) -> TaskType | None:
        if not self._config.task_type_to_label_id:
            return None
        nodes = labels.get("nodes") if isinstance(labels, dict) else None
        if not isinstance(nodes, list):
            return None
        reverse = {
            label_id: task_type
            for task_type, label_id in self._config.task_type_to_label_id.items()
        }
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            label_id = raw.get("id")
            if isinstance(label_id, str) and label_id in reverse:
                return reverse[label_id]
        return None

    @staticmethod
    def _extract_input_payload(
        input_dict: dict[str, Any] | None, issue_id: str
    ) -> TaskInputPayload | None:
        input_payload: TaskInputPayload | None = None
        if isinstance(input_dict, dict):
            try:
                input_payload = TaskInputPayload.model_validate(input_dict)
            except ValidationError as exc:
                _logger.warning(
                    "linear_input_payload_invalid",
                    error=str(exc),
                    issue_id=issue_id,
                )
                input_payload = None

        return input_payload

    def create_task(self, payload: TrackerTaskCreatePayload) -> TrackerTaskReference:
        variables = self._build_create_variables(payload, parent_external_id=None)
        return self._execute_issue_create(variables)

    def create_subtask(self, payload: TrackerSubtaskCreatePayload) -> TrackerTaskReference:
        variables = self._build_create_variables(
            payload, parent_external_id=payload.parent_external_id
        )
        return self._execute_issue_create(variables)

    def _execute_issue_create(self, variables: dict[str, Any]) -> TrackerTaskReference:
        data = self._client.execute(_ISSUE_CREATE_MUTATION, {"input": variables})
        result = data.get("issueCreate")
        if not isinstance(result, dict):
            raise RuntimeError("Linear issueCreate response missing 'issueCreate'")
        if not result.get("success"):
            raise RuntimeError("Linear issueCreate returned success=false")
        issue = result.get("issue")
        if not isinstance(issue, dict):
            raise RuntimeError("Linear issueCreate response missing 'issue' object")
        external_id = issue.get("id")
        if not isinstance(external_id, str) or not external_id:
            raise RuntimeError("Linear issueCreate response missing issue id")
        url_raw = issue.get("url")
        url = url_raw if isinstance(url_raw, str) and url_raw else None
        return TrackerTaskReference(external_id=external_id, url=url)

    def _build_create_variables(
        self,
        payload: TrackerTaskCreatePayload,
        *,
        parent_external_id: str | None,
    ) -> dict[str, Any]:
        team_id = self._resolve_team_id(payload)
        state_id = self._status_to_state_id(payload.status)
        description = self._inject_input_block_with_warning(
            payload.context.description,
            self._build_input_block_payload(payload),
            title=payload.context.title,
        )

        variables: dict[str, Any] = {
            "teamId": team_id,
            "title": payload.context.title,
            "stateId": state_id,
        }
        if description is not None:
            variables["description"] = description
        label_ids = self._resolve_label_ids(payload.task_type)
        if label_ids:
            variables["labelIds"] = label_ids
        if parent_external_id:
            variables["parentId"] = parent_external_id
        return variables

    def _resolve_team_id(self, payload: TrackerTaskCreatePayload) -> str:
        override = payload.metadata.get("linear_team_id")
        if isinstance(override, str) and override:
            return override
        return self._config.team_id

    def _resolve_label_ids(self, task_type: TaskType | None) -> list[str]:
        if task_type is None:
            return []
        mapped = self._config.task_type_to_label_id.get(task_type)
        return [mapped] if mapped else []

    @staticmethod
    def _build_input_block_payload(
        payload: TrackerTaskCreatePayload,
    ) -> dict[str, Any]:
        block: dict[str, Any] = {}
        if payload.repo_url:
            block["repo_url"] = payload.repo_url
        if payload.repo_ref:
            block["repo_ref"] = payload.repo_ref
        if payload.workspace_key:
            block["workspace_key"] = payload.workspace_key
        if payload.input_payload is not None:
            input_dump = payload.input_payload.model_dump(mode="json", exclude_none=True)
            input_dump = {
                k: v for k, v in input_dump.items() if not (isinstance(v, dict) and not v)
            }
            if input_dump:
                block["input"] = input_dump
        for key in _HIDDEN_METADATA_KEYS:
            value = payload.metadata.get(key)
            if isinstance(value, dict):
                block[key] = dict(value)
        return block

    def _inject_input_block_with_warning(
        self,
        description: str | None,
        payload_dict: Mapping[str, Any],
        *,
        title: str,
    ) -> str | None:
        threshold = self._config.description_warn_threshold
        base_length = len(description) if description else 0

        if not payload_dict:
            if threshold > 0 and base_length > threshold:
                _logger.warning(
                    "linear_description_warn_threshold_exceeded",
                    title=title,
                    description_length=base_length,
                    block_length=0,
                    threshold=threshold,
                )
            return description

        injected = _inject_input_block(description, payload_dict)
        if threshold > 0 and len(injected) > threshold:
            block_length = len(injected) - base_length
            _logger.warning(
                "linear_description_warn_threshold_exceeded",
                title=title,
                description_length=len(injected),
                block_length=block_length,
                threshold=threshold,
            )
        return injected

    def add_comment(self, payload: TrackerCommentCreatePayload) -> TrackerCommentReference:
        variables = {
            "input": {
                "issueId": payload.external_task_id,
                "body": _inject_comment_metadata(payload.body, payload.metadata),
            }
        }
        data = self._client.execute(_COMMENT_CREATE_MUTATION, variables)
        comment = self._require_success_child(
            data, mutation_key="commentCreate", child_key="comment"
        )
        comment_id = comment.get("id")
        if not isinstance(comment_id, str) or not comment_id:
            raise RuntimeError("Linear commentCreate response missing comment id")
        return TrackerCommentReference(comment_id=comment_id)

    def read_comments(self, query: TrackerReadCommentsQuery) -> TrackerReadCommentsResult:
        variables = {
            "id": query.external_task_id,
            "first": min(query.limit, _LINEAR_PAGE_LIMIT),
            "after": query.page_cursor,
        }
        data = self._client.execute(_READ_ISSUE_COMMENTS_QUERY, variables)
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise RuntimeError("Linear issue comments response missing 'issue' object")
        comments_block = issue.get("comments")
        if not isinstance(comments_block, dict):
            raise RuntimeError("Linear issue comments response missing 'comments' object")
        nodes = comments_block.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError("Linear issue comments.nodes is not a list")

        items: list[TrackerCommentPayload] = []
        latest_cursor = query.since_cursor
        skip_until_since = query.page_cursor is None and query.since_cursor is not None

        for raw_comment in nodes:
            item = self._to_tracker_comment(raw_comment, external_task_id=query.external_task_id)
            if item is None:
                continue
            latest_cursor = item.comment_id
            if skip_until_since:
                if item.comment_id == query.since_cursor:
                    skip_until_since = False
                continue
            items.append(item)

        page_info = comments_block.get("pageInfo")
        next_page_cursor = None
        if isinstance(page_info, dict) and page_info.get("hasNextPage"):
            end_cursor = page_info.get("endCursor")
            if isinstance(end_cursor, str) and end_cursor:
                next_page_cursor = end_cursor

        return TrackerReadCommentsResult(
            items=items,
            next_page_cursor=next_page_cursor,
            latest_cursor=latest_cursor,
        )

    def update_status(self, payload: TrackerStatusUpdatePayload) -> TrackerTaskReference:
        state_id = self._status_to_state_id(payload.status)
        variables = {
            "id": payload.external_task_id,
            "input": {"stateId": state_id},
        }
        data = self._client.execute(_ISSUE_UPDATE_MUTATION, variables)
        issue = self._require_success_child(data, mutation_key="issueUpdate", child_key="issue")
        url_raw = issue.get("url")
        url = url_raw if isinstance(url_raw, str) and url_raw else None
        return TrackerTaskReference(external_id=payload.external_task_id, url=url)

    def claim_task_selection(
        self, payload: TrackerTaskSelectionClaimPayload
    ) -> TrackerTaskReference:
        description = self._fetch_issue_description(payload.external_task_id)
        cleaned_description, payload_dict = _extract_input_block(description)
        next_payload = dict(payload_dict) if isinstance(payload_dict, dict) else {}
        selection_value = next_payload.get("selection")
        selection_metadata = dict(selection_value) if isinstance(selection_value, dict) else {}
        selection_metadata["taken_in_work"] = True
        next_payload["selection"] = selection_metadata

        variables = {
            "id": payload.external_task_id,
            "input": {
                "description": _inject_input_block(cleaned_description or None, next_payload),
            },
        }
        data = self._client.execute(_ISSUE_UPDATE_MUTATION, variables)
        issue = self._require_success_child(data, mutation_key="issueUpdate", child_key="issue")
        url_raw = issue.get("url")
        url = url_raw if isinstance(url_raw, str) and url_raw else None
        return TrackerTaskReference(external_id=payload.external_task_id, url=url)

    def attach_links(self, payload: TrackerLinksAttachPayload) -> TrackerTaskReference:
        for link in payload.links:
            variables = {
                "input": {
                    "issueId": payload.external_task_id,
                    "url": link.url,
                    "title": link.label,
                }
            }
            data = self._client.execute(_ATTACHMENT_CREATE_MUTATION, variables)
            try:
                self._require_success_child(
                    data, mutation_key="attachmentCreate", child_key="attachment"
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Linear attachmentCreate failed for url={link.url!r}: {exc}"
                ) from None
        return TrackerTaskReference(external_id=payload.external_task_id)

    @staticmethod
    def _require_success_child(
        data: Mapping[str, Any], *, mutation_key: str, child_key: str
    ) -> dict[str, Any]:
        result = data.get(mutation_key)
        if not isinstance(result, dict):
            raise RuntimeError(f"Linear {mutation_key} response missing '{mutation_key}' object")
        if not result.get("success"):
            raise RuntimeError(f"Linear {mutation_key} returned success=false")
        child = result.get(child_key)
        if not isinstance(child, dict):
            raise RuntimeError(f"Linear {mutation_key} response missing '{child_key}' object")
        return child

    def _fetch_issue_description(self, issue_id: str) -> str | None:
        data = self._client.execute(_ISSUE_DESCRIPTION_QUERY, {"id": issue_id})
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise RuntimeError("Linear issue query response missing 'issue' object")
        description = issue.get("description")
        return description if isinstance(description, str) else None

    @staticmethod
    def _to_tracker_comment(
        raw_comment: Any, *, external_task_id: str
    ) -> TrackerCommentPayload | None:
        if not isinstance(raw_comment, dict):
            return None
        comment_id = raw_comment.get("id")
        if not isinstance(comment_id, str) or not comment_id:
            return None
        body_raw = raw_comment.get("body")
        body, metadata = _extract_comment_metadata(body_raw if isinstance(body_raw, str) else None)
        url_raw = raw_comment.get("url")
        url = url_raw if isinstance(url_raw, str) and url_raw else None
        user = raw_comment.get("user")
        author = None
        if isinstance(user, dict):
            display_name = user.get("displayName")
            name = user.get("name")
            if isinstance(display_name, str) and display_name:
                author = display_name
            elif isinstance(name, str) and name:
                author = name
        return TrackerCommentPayload(
            external_task_id=external_task_id,
            comment_id=comment_id,
            body=body,
            author=author,
            url=url,
            metadata=metadata or {},
        )


__all__ = [
    "HttpRequester",
    "LinearRateLimitError",
    "LinearTracker",
    "LinearTrackerConfig",
]
