from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from backend.schemas import (
    ScmBranchCreatePayload,
    ScmBranchReference,
    ScmCommitChangesPayload,
    ScmCommitReference,
    ScmPullRequestCreatePayload,
    ScmPullRequestFeedback,
    ScmPullRequestMetadata,
    ScmPullRequestReference,
    ScmPushBranchPayload,
    ScmPushReference,
    ScmReadPrFeedbackQuery,
    ScmReadPrFeedbackResult,
    ScmWorkspace,
    ScmWorkspaceEnsurePayload,
)

_PR_METADATA_TAG = "heavy-lifting:pr-metadata:v1"
_PR_METADATA_PATTERN = re.compile(r"<!-- " + re.escape(_PR_METADATA_TAG) + r" ([A-Za-z0-9_-]+) -->")
_HL_UNRESOLVED_KEY = "_hl_unresolved"

_FEEDBACK_SOURCES = ("issue", "review_comment", "review")
_GITHUB_PER_PAGE_MAX = 100


@dataclass(frozen=True, slots=True)
class GitHubScmConfig:
    api_base_url: str
    token_env_var: str
    user_name: str | None
    user_email: str | None
    default_remote: str
    workspace_root: Path
    default_repo_url: str | None


@dataclass(frozen=True, slots=True)
class GitHubResponse:
    status: int
    headers: Mapping[str, str]
    body: Any


class GitHubApiError(RuntimeError):
    def __init__(self, *, status: int, method: str, url: str, body_excerpt: str) -> None:
        self.status = status
        self.method = method
        self.url = url
        self.body_excerpt = body_excerpt
        super().__init__(f"{method} {url} -> {status}: {body_excerpt}")


class _GitRunnerProtocol(Protocol):
    def run(
        self,
        args: list[str],
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class _GithubHttpClientProtocol(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, str] | None = None,
    ) -> GitHubResponse: ...


@dataclass(frozen=True, slots=True)
class _SourceCursor:
    page: str  # "*" means exhausted
    offset: int

    @classmethod
    def initial(cls) -> _SourceCursor:
        return cls(page="1", offset=0)

    @property
    def exhausted(self) -> bool:
        return self.page == "*"

    @property
    def page_int(self) -> int:
        return int(self.page)


@dataclass(frozen=True, slots=True)
class _FeedbackCursor:
    """Composite cursor: <iso_updated_at>|<source>|<numeric_id>."""

    updated_at: str
    source: str
    numeric_id: int

    def serialize(self) -> str:
        return f"{self.updated_at}|{self.source}|{self.numeric_id}"

    @classmethod
    def parse(cls, value: str) -> _FeedbackCursor:
        parts = value.split("|")
        if len(parts) != 3:
            raise ValueError(f"Invalid feedback cursor: {value!r}")
        updated_at, source, numeric_id = parts
        return cls(updated_at=updated_at, source=source, numeric_id=int(numeric_id))

    def sort_key(self) -> tuple[str, str, int]:
        return (self.updated_at, self.source, self.numeric_id)


@dataclass(frozen=True, slots=True)
class _LoadedFeedbackItem:
    cursor: _FeedbackCursor
    feedback: ScmPullRequestFeedback


def _parse_repo_location(repo_url: str) -> tuple[str, str, str]:
    """Return (host, owner, repo) parsed from https://host/owner/repo or git@host:owner/repo."""

    if repo_url.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(repo_url)
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
    elif repo_url.startswith("git@"):
        match = re.match(r"^git@([^:]+):(.+)$", repo_url)
        if not match:
            raise ValueError(f"Cannot parse repo_url: {repo_url!r}")
        host = match.group(1)
        path = match.group(2)
    else:
        raise ValueError(f"Cannot parse repo_url: {repo_url!r}")

    path = path.removesuffix(".git")
    segments = path.split("/")
    if len(segments) < 2 or not all(segments):
        raise ValueError(f"Cannot parse owner/repo from: {repo_url!r}")
    owner = segments[-2]
    repo = segments[-1]
    if not host:
        raise ValueError(f"Cannot parse host from repo_url: {repo_url!r}")
    return host, owner, repo


def _safe_workspace_path(workspace_root: Path, workspace_key: str) -> Path:
    if not workspace_key:
        raise ValueError("workspace_key must not be empty")
    if any(c in workspace_key for c in ("\x00",)):
        raise ValueError(f"workspace_key contains forbidden characters: {workspace_key!r}")
    if workspace_key in (".", ".."):
        raise ValueError(f"workspace_key must not be '.' or '..': {workspace_key!r}")
    if "/" in workspace_key or "\\" in workspace_key:
        raise ValueError(f"workspace_key must not contain path separators: {workspace_key!r}")
    if Path(workspace_key).is_absolute():
        raise ValueError(f"workspace_key must not be absolute: {workspace_key!r}")

    root_resolved = workspace_root.resolve()
    candidate = (workspace_root / workspace_key).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ValueError(f"workspace_key escapes workspace_root: {workspace_key!r}")
    return candidate


def _git_auth_args(token: str | None) -> list[str]:
    if not token:
        return []
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return ["-c", f"http.extraHeader=Authorization: Basic {encoded}"]


def _normalized_review_body(state: str | None, body: str | None) -> str:
    if body and body.strip():
        return body
    if state == "APPROVED":
        return "(approved without comment)"
    if state == "CHANGES_REQUESTED":
        return "(changes requested without comment)"
    return "(review without comment)"


def _sanitize_token(text: str, token: str | None) -> str:
    if not token:
        return text
    return text.replace(token, "***")


class _GitRunner:
    def run(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — args constructed by adapter
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )


class _GithubHttpClient:
    def __init__(self, *, api_base_url: str, token_env_var: str) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._token_env_var = token_env_var

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, str] | None = None,
    ) -> GitHubResponse:
        url = f"{self._api_base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        token = os.getenv(self._token_env_var)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(  # noqa: S310 — urls constructed by adapter
            url, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                payload = response.read()
                response_headers = {k: v for k, v in response.headers.items()}
                parsed_body = _parse_json_or_none(payload)
                return GitHubResponse(
                    status=response.status,
                    headers=response_headers,
                    body=parsed_body,
                )
        except urllib.error.HTTPError as exc:
            payload_bytes = exc.read() if exc.fp is not None else b""
            response_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            text = payload_bytes.decode("utf-8", errors="replace")
            excerpt = text[:500]
            raise GitHubApiError(
                status=exc.code,
                method=method,
                url=url,
                body_excerpt=excerpt,
            ) from exc


def _parse_json_or_none(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _encode_pr_metadata_footer(metadata: ScmPullRequestMetadata) -> str:
    payload = json.dumps(
        metadata.model_dump(mode="json"),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return f"<!-- {_PR_METADATA_TAG} {encoded} -->"


def _decode_pr_metadata_footer(body: str | None) -> ScmPullRequestMetadata | None:
    if not body:
        return None
    match = _PR_METADATA_PATTERN.search(body)
    if not match:
        return None
    encoded = match.group(1)
    padding = "=" * (-len(encoded) % 4)
    try:
        payload = base64.urlsafe_b64decode(encoded + padding)
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    try:
        return ScmPullRequestMetadata.model_validate(decoded)
    except ValidationError:
        return None


class GitHubScm:
    def __init__(
        self,
        config: GitHubScmConfig,
        *,
        http_client: _GithubHttpClientProtocol | None = None,
        runner: _GitRunnerProtocol | None = None,
    ) -> None:
        self._config = config
        self._runner: _GitRunnerProtocol = runner or _GitRunner()
        self._http: _GithubHttpClientProtocol = http_client or _GithubHttpClient(
            api_base_url=config.api_base_url,
            token_env_var=config.token_env_var,
        )
        self._workspaces: dict[str, ScmWorkspace] = {}

    # --- ScmProtocol methods --------------------------------------------------

    def ensure_workspace(self, payload: ScmWorkspaceEnsurePayload) -> ScmWorkspace:
        repo_url = payload.repo_url or self._config.default_repo_url
        if not repo_url:
            raise RuntimeError(
                "repo_url required: set GITHUB_DEFAULT_REPO_URL or pass per-task repo_url"
            )

        local_path = _safe_workspace_path(self._config.workspace_root, payload.workspace_key)
        self._config.workspace_root.mkdir(parents=True, exist_ok=True)
        token = self._token()

        if not local_path.exists():
            self._git_run(
                [
                    "git",
                    *_git_auth_args(token),
                    "clone",
                    repo_url,
                    str(local_path),
                ],
                cwd=str(self._config.workspace_root),
                token=token,
            )
        else:
            self._git_run(
                [
                    "git",
                    *_git_auth_args(token),
                    "fetch",
                    self._config.default_remote,
                ],
                cwd=str(local_path),
                token=token,
            )

        resolved_ref = payload.repo_ref or self._resolve_default_branch(local_path)
        checked_out_branch = payload.branch_name
        if checked_out_branch:
            self._checkout_branch(
                local_path=local_path,
                branch_name=checked_out_branch,
                token=token,
            )
        else:
            self._git_run(
                ["git", "checkout", resolved_ref],
                cwd=str(local_path),
                token=token,
            )

        workspace = ScmWorkspace(
            repo_url=repo_url,
            workspace_key=payload.workspace_key,
            repo_ref=resolved_ref,
            local_path=str(local_path),
            branch_name=checked_out_branch,
            metadata=dict(payload.metadata),
        )
        self._workspaces[payload.workspace_key] = workspace
        return workspace.model_copy(deep=True)

    def create_branch(self, payload: ScmBranchCreatePayload) -> ScmBranchReference:
        workspace = self._require_workspace(payload.workspace_key)
        from_ref = payload.from_ref or workspace.repo_ref
        if not from_ref:
            raise RuntimeError(
                "create_branch requires from_ref or workspace.repo_ref "
                f"for {payload.workspace_key!r}"
            )
        token = self._token()
        self._git_run(
            [
                "git",
                *_git_auth_args(token),
                "fetch",
                self._config.default_remote,
                from_ref,
            ],
            cwd=workspace.local_path,
            token=token,
        )
        self._git_run(
            [
                "git",
                "checkout",
                "-B",
                payload.branch_name,
                f"{self._config.default_remote}/{from_ref}",
            ],
            cwd=workspace.local_path,
            token=token,
        )
        return ScmBranchReference(
            workspace_key=payload.workspace_key,
            branch_name=payload.branch_name,
            from_ref=from_ref,
            metadata=dict(payload.metadata),
        )

    def get_head_commit(self, workspace_key: str, _branch_name: str) -> str | None:
        workspace = self._require_workspace(workspace_key)
        token = self._token()
        rev = self._git_run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace.local_path,
            token=token,
        )
        commit_sha = rev.stdout.strip()
        return commit_sha or None

    def commit_changes(self, payload: ScmCommitChangesPayload) -> ScmCommitReference:
        workspace = self._require_workspace(payload.workspace_key)
        token = self._token()

        rev_before = self._git_run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace.local_path,
            token=token,
        )
        head_before = rev_before.stdout.strip()

        status = self._git_run(
            ["git", "status", "--porcelain"],
            cwd=workspace.local_path,
            token=token,
        )
        if not status.stdout.strip():
            if (
                payload.pre_run_head_sha is None
                or payload.pre_run_head_sha == head_before
                or not self._is_ancestor_commit(
                    workspace_path=workspace.local_path,
                    ancestor_sha=payload.pre_run_head_sha,
                    descendant_sha=head_before,
                    token=token,
                )
            ):
                raise RuntimeError("no changes to commit")
            return ScmCommitReference(
                workspace_key=payload.workspace_key,
                branch_name=payload.branch_name,
                commit_sha=head_before,
                message=payload.message,
                metadata={**dict(payload.metadata), "reused_existing_commit": True},
            )

        self._git_run(["git", "add", "-A"], cwd=workspace.local_path, token=token)
        commit_args = ["git"]
        if self._config.user_name:
            commit_args += ["-c", f"user.name={self._config.user_name}"]
        if self._config.user_email:
            commit_args += ["-c", f"user.email={self._config.user_email}"]
        commit_args += ["commit", "-m", payload.message]
        self._git_run(commit_args, cwd=workspace.local_path, token=token)

        rev = self._git_run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace.local_path,
            token=token,
        )
        commit_sha = rev.stdout.strip()
        return ScmCommitReference(
            workspace_key=payload.workspace_key,
            branch_name=payload.branch_name,
            commit_sha=commit_sha,
            message=payload.message,
            metadata={**dict(payload.metadata), "reused_existing_commit": False},
        )

    def push_branch(self, payload: ScmPushBranchPayload) -> ScmPushReference:
        workspace = self._require_workspace(payload.workspace_key)
        remote = payload.remote_name or self._config.default_remote
        token = self._token()
        self._git_run(
            [
                "git",
                *_git_auth_args(token),
                "push",
                "-u",
                remote,
                payload.branch_name,
            ],
            cwd=workspace.local_path,
            token=token,
        )
        branch_url = self._build_branch_url(workspace.repo_url, payload.branch_name)
        return ScmPushReference(
            workspace_key=payload.workspace_key,
            branch_name=payload.branch_name,
            remote_name=remote,
            remote_branch_name=payload.branch_name,
            branch_url=branch_url,
            metadata=dict(payload.metadata),
        )

    def create_pull_request(self, payload: ScmPullRequestCreatePayload) -> ScmPullRequestReference:
        workspace = self._require_workspace(payload.workspace_key)
        if not workspace.repo_url:
            raise RuntimeError(f"workspace {payload.workspace_key!r} has no repo_url")
        _, owner, repo = _parse_repo_location(workspace.repo_url)
        body = self._compose_pr_body(payload.body, payload.pr_metadata)
        request_body = {
            "title": payload.title,
            "body": body,
            "head": payload.branch_name,
            "base": payload.base_branch,
        }
        try:
            response = self._http.request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                body=request_body,
            )
        except GitHubApiError as exc:
            if exc.status == 422 and "already exists" in exc.body_excerpt.lower():
                existing = self._lookup_existing_pr(
                    owner=owner,
                    repo=repo,
                    branch_name=payload.branch_name,
                )
                if existing is not None:
                    return self._build_pull_request_reference(
                        owner=owner,
                        repo=repo,
                        repo_url=workspace.repo_url,
                        payload=payload,
                        body_data=existing,
                    )
            raise

        if not isinstance(response.body, dict):
            raise RuntimeError(f"unexpected create-PR response body: {response.body!r}")
        return self._build_pull_request_reference(
            owner=owner,
            repo=repo,
            repo_url=workspace.repo_url,
            payload=payload,
            body_data=response.body,
        )

    def read_pr_feedback(self, query: ScmReadPrFeedbackQuery) -> ScmReadPrFeedbackResult:
        if not query.pr_external_id:
            raise RuntimeError("read_pr_feedback requires pr_external_id for GitHubScm")
        repo_url = self._resolve_query_repo_url(query)
        if not repo_url:
            raise RuntimeError(
                "repo_url or workspace context required for GitHubScm.read_pr_feedback"
            )
        _, owner, repo = _parse_repo_location(repo_url)
        pr_number = query.pr_external_id
        per_page = min(query.limit, _GITHUB_PER_PAGE_MAX)

        cursors = self._parse_page_cursor(query.page_cursor)
        since_cursor = self._parse_since_cursor(query.since_cursor)

        per_source_loaded: dict[str, list[_LoadedFeedbackItem]] = {
            source: [] for source in _FEEDBACK_SOURCES
        }
        # source -> ordered list of after_offset entries: each is either a loaded
        # _LoadedFeedbackItem or None (filtered out by since/invalid). Order is
        # the GitHub page's original order, so we can later compute a strict
        # consumed-prefix that terminates at the first loaded-but-not-returned
        # element — guaranteeing skip-free pagination even with mixed
        # invalid/loaded items on a single page.
        per_source_order: dict[str, list[_LoadedFeedbackItem | None]] = {
            source: [] for source in _FEEDBACK_SOURCES
        }
        per_source_has_next: dict[str, bool] = {source: False for source in _FEEDBACK_SOURCES}

        for source in _FEEDBACK_SOURCES:
            cursor = cursors[source]
            if cursor.exhausted:
                continue
            items, has_next = self._fetch_source_page(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                source=source,
                page=cursor.page_int,
                per_page=per_page,
                since_cursor=since_cursor,
            )
            per_source_has_next[source] = has_next
            after_offset = items[cursor.offset :]
            for raw_item in after_offset:
                feedback_item = self._build_feedback_item(
                    source=source,
                    repo_url=repo_url,
                    pr_external_id=pr_number,
                    raw=raw_item,
                    query=query,
                )
                if feedback_item is None:
                    per_source_order[source].append(None)
                    continue
                if since_cursor is not None and (
                    feedback_item.cursor.sort_key() <= since_cursor.sort_key()
                ):
                    per_source_order[source].append(None)
                    continue
                per_source_order[source].append(feedback_item)
                per_source_loaded[source].append(feedback_item)

        merged: list[_LoadedFeedbackItem] = []
        for source_items in per_source_loaded.values():
            merged.extend(source_items)
        merged.sort(key=lambda item: item.cursor.sort_key())
        returned = merged[: query.limit]
        returned_keys: set[tuple[str, int]] = {
            (item.cursor.source, item.cursor.numeric_id) for item in returned
        }

        next_cursors: dict[str, _SourceCursor] = {}
        for source in _FEEDBACK_SOURCES:
            cursor = cursors[source]
            if cursor.exhausted:
                next_cursors[source] = cursor
                continue
            order = per_source_order[source]
            has_next = per_source_has_next[source]
            consumed = 0
            for entry in order:
                if entry is None:
                    consumed += 1
                    continue
                key = (entry.cursor.source, entry.cursor.numeric_id)
                if key in returned_keys:
                    consumed += 1
                    continue
                # First loaded-but-not-returned item: stop. It (and everything
                # after it on this page, including subsequent filtered items)
                # must be re-read on the next call so the leftover is observed.
                break
            after_offset_count = len(order)
            if consumed >= after_offset_count:
                # entire page (post-offset) consumed
                if has_next:
                    next_cursors[source] = _SourceCursor(page=str(cursor.page_int + 1), offset=0)
                else:
                    next_cursors[source] = _SourceCursor(page="*", offset=0)
            else:
                next_cursors[source] = _SourceCursor(
                    page=cursor.page, offset=cursor.offset + consumed
                )

        items_for_metadata: list[ScmPullRequestFeedback] = []
        if returned:
            pr_body_metadata = self._fetch_pr_body_metadata(
                owner=owner, repo=repo, pr_number=pr_number, query=query
            )
            for item in returned:
                metadata = pr_body_metadata or self._build_unresolved_metadata(query)
                items_for_metadata.append(
                    item.feedback.model_copy(update={"pr_metadata": metadata})
                )

        latest_cursor: str | None
        if returned:
            latest_cursor = returned[-1].cursor.serialize()
        else:
            latest_cursor = query.since_cursor

        if all(c.exhausted for c in next_cursors.values()):
            next_page_cursor = None
        else:
            next_page_cursor = self._serialize_page_cursor(next_cursors)

        return ScmReadPrFeedbackResult(
            items=items_for_metadata,
            next_page_cursor=next_page_cursor,
            latest_cursor=latest_cursor,
        )

    # --- private helpers ------------------------------------------------------

    def _token(self) -> str | None:
        return os.getenv(self._config.token_env_var)

    def _git_run(
        self,
        args: list[str],
        *,
        cwd: str,
        token: str | None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner.run(args, cwd=cwd)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            sanitized = _sanitize_token(stderr or stdout, token)
        raise RuntimeError(f"git command failed: {sanitized}")

    def _resolve_default_branch(self, local_path: Path) -> str:
        result = self._git_run(
            [
                "git",
                "symbolic-ref",
                "--short",
                f"refs/remotes/{self._config.default_remote}/HEAD",
            ],
            cwd=str(local_path),
            token=self._token(),
        )
        ref = result.stdout.strip()
        prefix = f"{self._config.default_remote}/"
        if ref.startswith(prefix):
            return ref[len(prefix) :]
        return ref

    def _is_ancestor_commit(
        self,
        *,
        workspace_path: str,
        ancestor_sha: str,
        descendant_sha: str,
        token: str | None,
    ) -> bool:
        try:
            self._runner.run(
                ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
                cwd=workspace_path,
            )
            return True
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 1:
                return False
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            sanitized = _sanitize_token(stderr or stdout, token)
            raise RuntimeError(f"git command failed: {sanitized}") from exc

    def _checkout_branch(
        self,
        *,
        local_path: Path,
        branch_name: str,
        token: str | None,
    ) -> None:
        remote_branch_ref = f"refs/remotes/{self._config.default_remote}/{branch_name}"
        has_remote_branch = self._git_ref_exists(
            local_path=local_path,
            ref=remote_branch_ref,
            token=token,
        )
        if has_remote_branch:
            self._git_run(
                [
                    "git",
                    "checkout",
                    "-B",
                    branch_name,
                    f"{self._config.default_remote}/{branch_name}",
                ],
                cwd=str(local_path),
                token=token,
            )
            return
        self._git_run(
            ["git", "checkout", branch_name],
            cwd=str(local_path),
            token=token,
        )

    def _git_ref_exists(
        self,
        *,
        local_path: Path,
        ref: str,
        token: str | None,
    ) -> bool:
        try:
            self._git_run(
                ["git", "rev-parse", "--verify", ref],
                cwd=str(local_path),
                token=token,
            )
        except RuntimeError:
            return False
        return True

    def _require_workspace(self, workspace_key: str) -> ScmWorkspace:
        try:
            return self._workspaces[workspace_key]
        except KeyError as exc:
            raise RuntimeError(f"workspace not initialized: {workspace_key!r}") from exc

    def _build_branch_url(self, repo_url: str, branch_name: str) -> str | None:
        try:
            host, owner, repo = _parse_repo_location(repo_url)
        except ValueError:
            return None
        return f"https://{host}/{owner}/{repo}/tree/{branch_name}"

    def _compose_pr_body(self, body: str | None, pr_metadata: ScmPullRequestMetadata) -> str:
        footer = _encode_pr_metadata_footer(pr_metadata)
        if not body:
            return footer
        return f"{body}\n\n{footer}"

    def _build_pull_request_reference(
        self,
        *,
        owner: str,
        repo: str,
        repo_url: str,
        payload: ScmPullRequestCreatePayload,
        body_data: Mapping[str, Any],
    ) -> ScmPullRequestReference:
        number = body_data.get("number")
        if number is None:
            raise RuntimeError(f"GitHub PR response is missing 'number': {body_data!r}")
        html_url = body_data.get("html_url")
        if not html_url:
            html_url = f"https://{_parse_repo_location(repo_url)[0]}/{owner}/{repo}/pull/{number}"
        return ScmPullRequestReference(
            external_id=str(number),
            url=str(html_url),
            workspace_key=payload.workspace_key,
            branch_name=payload.branch_name,
            base_branch=payload.base_branch,
            pr_metadata=payload.pr_metadata.model_copy(deep=True),
            metadata=dict(payload.metadata),
        )

    def _lookup_existing_pr(
        self, *, owner: str, repo: str, branch_name: str
    ) -> Mapping[str, Any] | None:
        response = self._http.request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            query={"head": f"{owner}:{branch_name}", "state": "open"},
        )
        if not isinstance(response.body, list) or not response.body:
            return None
        first = response.body[0]
        return first if isinstance(first, dict) else None

    def _resolve_query_repo_url(self, query: ScmReadPrFeedbackQuery) -> str | None:
        if query.repo_url:
            return query.repo_url
        if query.workspace_key:
            workspace = self._workspaces.get(query.workspace_key)
            if workspace is not None and workspace.repo_url:
                return workspace.repo_url
        return self._config.default_repo_url

    def _parse_page_cursor(self, page_cursor: str | None) -> dict[str, _SourceCursor]:
        if page_cursor is None:
            return {source: _SourceCursor.initial() for source in _FEEDBACK_SOURCES}
        result: dict[str, _SourceCursor] = {}
        parts = page_cursor.split(":")
        for part in parts:
            chunks = part.split("@")
            if len(chunks) != 3:
                raise ValueError(f"Invalid page_cursor part: {part!r}")
            source, page, offset = chunks
            if source not in _FEEDBACK_SOURCES:
                raise ValueError(f"Unknown source in page_cursor: {source!r}")
            result[source] = _SourceCursor(page=page, offset=int(offset))
        for source in _FEEDBACK_SOURCES:
            if source not in result:
                result[source] = _SourceCursor.initial()
        return result

    def _serialize_page_cursor(self, cursors: Mapping[str, _SourceCursor]) -> str:
        return ":".join(
            f"{source}@{cursors[source].page}@{cursors[source].offset}"
            for source in _FEEDBACK_SOURCES
        )

    def _parse_since_cursor(self, since_cursor: str | None) -> _FeedbackCursor | None:
        if not since_cursor:
            return None
        try:
            return _FeedbackCursor.parse(since_cursor)
        except ValueError:
            return None

    def _fetch_source_page(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: str,
        source: str,
        page: int,
        per_page: int,
        since_cursor: _FeedbackCursor | None,
    ) -> tuple[list[Mapping[str, Any]], bool]:
        path = self._source_endpoint(owner=owner, repo=repo, pr_number=pr_number, source=source)
        query: dict[str, str] = {
            "per_page": str(per_page),
            "page": str(page),
        }
        if source != "review" and since_cursor is not None:
            query["since"] = since_cursor.updated_at
        response = self._http.request("GET", path, query=query)
        items: list[Mapping[str, Any]] = []
        if isinstance(response.body, list):
            for entry in response.body:
                if isinstance(entry, dict):
                    items.append(entry)
        link_header = response.headers.get("Link") or response.headers.get("link") or ""
        has_next = 'rel="next"' in link_header
        return items, has_next

    def _source_endpoint(self, *, owner: str, repo: str, pr_number: str, source: str) -> str:
        if source == "issue":
            return f"/repos/{owner}/{repo}/issues/{pr_number}/comments"
        if source == "review_comment":
            return f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        if source == "review":
            return f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        raise ValueError(f"Unknown feedback source: {source!r}")

    def _build_feedback_item(
        self,
        *,
        source: str,
        repo_url: str,
        pr_external_id: str,
        raw: Mapping[str, Any],
        query: ScmReadPrFeedbackQuery,
    ) -> _LoadedFeedbackItem | None:
        numeric_id = raw.get("id")
        if not isinstance(numeric_id, int):
            return None

        if source == "review":
            updated_at = raw.get("submitted_at") or raw.get("updated_at")
        else:
            updated_at = raw.get("updated_at") or raw.get("created_at")
        if not isinstance(updated_at, str):
            return None

        user = raw.get("user")
        author = None
        if isinstance(user, dict):
            login = user.get("login")
            if isinstance(login, str):
                author = login

        path: str | None = None
        line: int | None = None
        side: str | None = None
        commit_sha: str | None = None
        body_text = raw.get("body")
        body_str = body_text if isinstance(body_text, str) else None
        review_state: str | None = None

        if source == "review_comment":
            raw_path = raw.get("path")
            if isinstance(raw_path, str):
                path = raw_path
            raw_line = raw.get("line")
            if isinstance(raw_line, int) and raw_line >= 1:
                line = raw_line
            raw_side = raw.get("side")
            if isinstance(raw_side, str):
                side = raw_side
            raw_commit = raw.get("commit_id")
            if isinstance(raw_commit, str):
                commit_sha = raw_commit
        elif source == "review":
            raw_state = raw.get("state")
            if isinstance(raw_state, str):
                review_state = raw_state
            body_str = _normalized_review_body(review_state, body_str)
            raw_commit = raw.get("commit_id")
            if isinstance(raw_commit, str):
                commit_sha = raw_commit

        if not isinstance(body_str, str):
            return None

        comment_id = self._format_comment_id(source, numeric_id)
        event_kind = self._event_kind_for(source, review_state)
        item_metadata: dict[str, Any] = {"event_kind": event_kind}
        if review_state is not None:
            item_metadata["review_state"] = review_state

        sentinel_metadata = self._build_unresolved_metadata(query)
        feedback = ScmPullRequestFeedback(
            pr_external_id=pr_external_id,
            comment_id=comment_id,
            body=body_str,
            author=author,
            path=path,
            line=line,
            side=side,
            commit_sha=commit_sha,
            pr_url=self._build_pr_html_url(repo_url, pr_external_id),
            metadata=item_metadata,
            pr_metadata=sentinel_metadata,
        )
        cursor = _FeedbackCursor(updated_at=updated_at, source=source, numeric_id=numeric_id)
        return _LoadedFeedbackItem(cursor=cursor, feedback=feedback)

    def _format_comment_id(self, source: str, numeric_id: int) -> str:
        return f"{source}-{numeric_id}"

    def _event_kind_for(self, source: str, review_state: str | None) -> str:
        if source != "review":
            return "pr_comment"
        if review_state == "APPROVED":
            return "pr_review_approved"
        if review_state == "CHANGES_REQUESTED":
            return "pr_review_requested_changes"
        return "pr_comment"

    def _build_pr_html_url(self, repo_url: str, pr_number: str) -> str | None:
        try:
            host, owner, repo = _parse_repo_location(repo_url)
        except ValueError:
            return None
        return f"https://{host}/{owner}/{repo}/pull/{pr_number}"

    def _build_unresolved_metadata(self, query: ScmReadPrFeedbackQuery) -> ScmPullRequestMetadata:
        return ScmPullRequestMetadata(
            execute_task_external_id="",
            workspace_key=query.workspace_key,
            repo_url=query.repo_url,
            metadata={_HL_UNRESOLVED_KEY: True},
        )

    def _fetch_pr_body_metadata(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: str,
        query: ScmReadPrFeedbackQuery,
    ) -> ScmPullRequestMetadata | None:
        try:
            response = self._http.request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
        except GitHubApiError:
            return None
        if not isinstance(response.body, dict):
            return None
        body = response.body.get("body")
        if not isinstance(body, str):
            return None
        return _decode_pr_metadata_footer(body)


def build_github_scm_config(
    *,
    api_base_url: str,
    token_env_var: str,
    user_name: str | None,
    user_email: str | None,
    default_remote: str,
    workspace_root: str | Path,
    default_repo_url: str | None,
) -> GitHubScmConfig:
    return GitHubScmConfig(
        api_base_url=api_base_url,
        token_env_var=token_env_var,
        user_name=user_name,
        user_email=user_email,
        default_remote=default_remote,
        workspace_root=Path(workspace_root),
        default_repo_url=default_repo_url,
    )


__all__ = [
    "GitHubApiError",
    "GitHubResponse",
    "GitHubScm",
    "GitHubScmConfig",
    "build_github_scm_config",
]
