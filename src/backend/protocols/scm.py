from typing import Protocol, runtime_checkable

from backend.schemas import (
    ScmBranchCreatePayload,
    ScmBranchReference,
    ScmCommitChangesPayload,
    ScmCommitReference,
    ScmPullRequestCreatePayload,
    ScmPullRequestReference,
    ScmPushBranchPayload,
    ScmPushReference,
    ScmReadPrFeedbackQuery,
    ScmReadPrFeedbackResult,
    ScmWorkspace,
    ScmWorkspaceEnsurePayload,
    ScmWorkspaceState,
)


@runtime_checkable
class ScmProtocol(Protocol):
    def ensure_workspace(self, payload: ScmWorkspaceEnsurePayload) -> ScmWorkspace: ...

    def get_head_commit(self, workspace_key: str, branch_name: str) -> str | None: ...

    def inspect_workspace(self, workspace_key: str) -> ScmWorkspaceState: ...

    def create_branch(self, payload: ScmBranchCreatePayload) -> ScmBranchReference: ...

    def create_branch_from_current_head(
        self, payload: ScmBranchCreatePayload
    ) -> ScmBranchReference: ...

    def commit_changes(self, payload: ScmCommitChangesPayload) -> ScmCommitReference: ...

    def push_branch(self, payload: ScmPushBranchPayload) -> ScmPushReference: ...

    def create_pull_request(
        self, payload: ScmPullRequestCreatePayload
    ) -> ScmPullRequestReference: ...

    def read_pr_feedback(self, query: ScmReadPrFeedbackQuery) -> ScmReadPrFeedbackResult: ...
