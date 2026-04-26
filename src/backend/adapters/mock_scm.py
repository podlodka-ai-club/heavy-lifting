from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from backend.schemas import (
    ScmBranchCreatePayload,
    ScmBranchReference,
    ScmCommitChangesPayload,
    ScmCommitReference,
    ScmPullRequestCreatePayload,
    ScmPullRequestFeedback,
    ScmPullRequestReference,
    ScmPushBranchPayload,
    ScmPushReference,
    ScmReadPrFeedbackQuery,
    ScmReadPrFeedbackResult,
    ScmWorkspace,
    ScmWorkspaceEnsurePayload,
)


class MockScm:
    def __init__(self) -> None:
        self._workspaces: dict[str, ScmWorkspace] = {}
        self._branches: dict[tuple[str, str], ScmBranchReference] = {}
        self._pull_requests: dict[str, ScmPullRequestReference] = {}
        self._pr_feedback: list[ScmPullRequestFeedback] = []
        self._commit_sequence = 0
        self._pull_request_sequence = 0
        self._feedback_sequence = 0

    def ensure_workspace(self, payload: ScmWorkspaceEnsurePayload) -> ScmWorkspace:
        if payload.repo_url is None:
            raise ValueError("MockScm requires repo_url")
        stored_payload = payload.model_copy(deep=True)
        repo_url = stored_payload.repo_url
        assert repo_url is not None  # narrowed above; re-asserted for type checker
        workspace = self._workspaces.get(stored_payload.workspace_key)
        local_path = self._resolve_local_workspace_path(repo_url)
        if local_path is None:
            local_path = f"/tmp/mock-scm/{stored_payload.workspace_key}"

        if workspace is None:
            workspace = ScmWorkspace(
                repo_url=repo_url,
                workspace_key=stored_payload.workspace_key,
                repo_ref=stored_payload.repo_ref,
                local_path=local_path,
                metadata=stored_payload.metadata,
            )
            self._workspaces[stored_payload.workspace_key] = workspace
        else:
            workspace.repo_url = repo_url
            workspace.repo_ref = stored_payload.repo_ref
            workspace.local_path = local_path
            if stored_payload.metadata:
                workspace.metadata = stored_payload.metadata

        return workspace.model_copy(deep=True)

    def create_branch(self, payload: ScmBranchCreatePayload) -> ScmBranchReference:
        workspace = self._require_workspace(payload.workspace_key)
        stored_payload = payload.model_copy(deep=True)
        branch = ScmBranchReference(
            workspace_key=stored_payload.workspace_key,
            branch_name=stored_payload.branch_name,
            from_ref=stored_payload.from_ref or workspace.repo_ref,
            metadata=stored_payload.metadata,
        )
        self._branches[(stored_payload.workspace_key, stored_payload.branch_name)] = branch
        workspace.branch_name = stored_payload.branch_name
        return branch.model_copy(deep=True)

    def commit_changes(self, payload: ScmCommitChangesPayload) -> ScmCommitReference:
        branch = self._require_branch(payload.workspace_key, payload.branch_name)
        stored_payload = payload.model_copy(deep=True)
        self._commit_sequence += 1
        commit = ScmCommitReference(
            workspace_key=stored_payload.workspace_key,
            branch_name=stored_payload.branch_name,
            commit_sha=f"mock-commit-{self._commit_sequence:04d}",
            message=stored_payload.message,
            metadata=stored_payload.metadata,
        )
        branch.head_commit_sha = commit.commit_sha
        return commit.model_copy(deep=True)

    def push_branch(self, payload: ScmPushBranchPayload) -> ScmPushReference:
        self._require_branch(payload.workspace_key, payload.branch_name)
        stored_payload = payload.model_copy(deep=True)
        workspace = self._require_workspace(stored_payload.workspace_key)
        return ScmPushReference(
            workspace_key=stored_payload.workspace_key,
            branch_name=stored_payload.branch_name,
            remote_name=stored_payload.remote_name,
            remote_branch_name=stored_payload.branch_name,
            branch_url=self._build_repo_url(
                workspace.repo_url, f"tree/{stored_payload.branch_name}"
            ),
            metadata=stored_payload.metadata,
        )

    def create_pull_request(self, payload: ScmPullRequestCreatePayload) -> ScmPullRequestReference:
        self._require_branch(payload.workspace_key, payload.branch_name)
        stored_payload = payload.model_copy(deep=True)
        workspace = self._require_workspace(stored_payload.workspace_key)
        self._pull_request_sequence += 1
        external_id = str(self._pull_request_sequence)
        pull_request = ScmPullRequestReference(
            external_id=external_id,
            url=self._build_pull_request_url(workspace.repo_url, external_id),
            workspace_key=stored_payload.workspace_key,
            branch_name=stored_payload.branch_name,
            base_branch=stored_payload.base_branch,
            pr_metadata=stored_payload.pr_metadata,
            metadata=stored_payload.metadata,
        )
        self._pull_requests[external_id] = pull_request
        return pull_request.model_copy(deep=True)

    def read_pr_feedback(self, query: ScmReadPrFeedbackQuery) -> ScmReadPrFeedbackResult:
        feedback_items = [
            feedback
            for feedback in self._pr_feedback
            if self._matches_feedback_query(feedback, query)
        ]
        feedback_items.sort(key=lambda item: int(item.comment_id.split("-")[-1]))
        page_start = int(query.page_cursor) if query.page_cursor is not None else 0
        page_items = feedback_items[page_start : page_start + query.limit]
        next_page_cursor = None
        if page_start + len(page_items) < len(feedback_items):
            next_page_cursor = str(page_start + len(page_items))
        latest_cursor = feedback_items[-1].comment_id if feedback_items else query.since_cursor
        return ScmReadPrFeedbackResult(
            items=[item.model_copy(deep=True) for item in page_items],
            next_page_cursor=next_page_cursor,
            latest_cursor=latest_cursor,
        )

    def add_pr_feedback(
        self,
        pr_external_id: str,
        body: str,
        *,
        author: str | None = None,
        path: str | None = None,
        line: int | None = None,
        side: str | None = None,
        commit_sha: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ScmPullRequestFeedback:
        pull_request = self._pull_requests[pr_external_id]
        self._feedback_sequence += 1
        feedback = ScmPullRequestFeedback(
            pr_external_id=pr_external_id,
            comment_id=f"comment-{self._feedback_sequence}",
            body=body,
            author=author,
            path=path,
            line=line,
            side=side,
            commit_sha=commit_sha,
            pr_url=pull_request.url,
            metadata=metadata or {},
            pr_metadata=pull_request.pr_metadata.model_copy(deep=True),
        )
        self._pr_feedback.append(feedback)
        return feedback.model_copy(deep=True)

    def _require_workspace(self, workspace_key: str) -> ScmWorkspace:
        return self._workspaces[workspace_key]

    def _require_branch(self, workspace_key: str, branch_name: str) -> ScmBranchReference:
        return self._branches[(workspace_key, branch_name)]

    def _matches_feedback_query(
        self, feedback: ScmPullRequestFeedback, query: ScmReadPrFeedbackQuery
    ) -> bool:
        if (
            query.workspace_key is not None
            and feedback.pr_metadata.workspace_key != query.workspace_key
        ):
            return False

        if query.repo_url is not None and feedback.pr_metadata.repo_url != query.repo_url:
            return False

        if query.pr_external_id is not None and feedback.pr_external_id != query.pr_external_id:
            return False

        pull_request = self._pull_requests[feedback.pr_external_id]
        if query.branch_name is not None and pull_request.branch_name != query.branch_name:
            return False

        if query.since_cursor is not None and self._cursor_value(
            feedback.comment_id
        ) <= self._cursor_value(query.since_cursor):
            return False

        return True

    def _build_repo_url(self, repo_url: str, suffix: str) -> str | None:
        if repo_url.startswith(("http://", "https://")):
            return f"{repo_url.removesuffix('.git')}/{suffix}"
        return None

    def _build_pull_request_url(self, repo_url: str, external_id: str) -> str:
        return (
            self._build_repo_url(repo_url, f"pull/{external_id}")
            or f"mock-scm://pull/{external_id}"
        )

    def _cursor_value(self, cursor: str) -> int:
        return int(cursor.split("-")[-1])

    def _resolve_local_workspace_path(self, repo_url: str) -> str | None:
        parsed = urlparse(repo_url)
        candidate: Path | None = None

        if parsed.scheme == "file":
            if parsed.netloc not in ("", "localhost"):
                return None
            candidate = Path(unquote(parsed.path)).expanduser()
        elif parsed.scheme == "":
            candidate = Path(repo_url).expanduser()
        else:
            return None

        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None

        if not resolved.is_dir():
            return None

        return str(resolved)
