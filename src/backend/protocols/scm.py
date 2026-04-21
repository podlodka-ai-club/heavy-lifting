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
)


@runtime_checkable
class ScmProtocol(Protocol):
    def ensure_workspace(self, payload: ScmWorkspaceEnsurePayload) -> ScmWorkspace: ...

    def create_branch(self, payload: ScmBranchCreatePayload) -> ScmBranchReference: ...

    def commit_changes(self, payload: ScmCommitChangesPayload) -> ScmCommitReference: ...

    def push_branch(self, payload: ScmPushBranchPayload) -> ScmPushReference: ...

    def create_pull_request(
        self, payload: ScmPullRequestCreatePayload
    ) -> ScmPullRequestReference: ...

    def read_pr_feedback(self, query: ScmReadPrFeedbackQuery) -> ScmReadPrFeedbackResult: ...
