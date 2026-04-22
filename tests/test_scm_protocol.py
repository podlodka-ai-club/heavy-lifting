from backend.adapters.mock_scm import MockScm
from backend.protocols.scm import ScmProtocol
from backend.schemas import (
    ScmBranchCreatePayload,
    ScmCommitChangesPayload,
    ScmPullRequestCreatePayload,
    ScmPullRequestMetadata,
    ScmPushBranchPayload,
    ScmReadPrFeedbackQuery,
    ScmWorkspaceEnsurePayload,
)


def test_mock_scm_matches_scm_protocol_at_runtime() -> None:
    scm = MockScm()

    assert isinstance(scm, ScmProtocol)


def test_mock_scm_supports_mvp_scm_operations() -> None:
    scm = MockScm()

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-1",
        )
    )
    branch = scm.create_branch(
        ScmBranchCreatePayload(
            workspace_key=workspace.workspace_key,
            branch_name="task18/scm-boundary",
        )
    )
    commit = scm.commit_changes(
        ScmCommitChangesPayload(
            workspace_key=workspace.workspace_key,
            branch_name=branch.branch_name,
            message="task18 define scm boundary",
        )
    )
    pushed = scm.push_branch(
        ScmPushBranchPayload(
            workspace_key=workspace.workspace_key,
            branch_name=branch.branch_name,
        )
    )
    pull_request = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key=workspace.workspace_key,
            branch_name=branch.branch_name,
            base_branch="main",
            title="Define SCM boundary",
            body="Adds SCM DTOs and protocol.",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="TASK-18",
                tracker_name="mock-tracker",
                workspace_key=workspace.workspace_key,
                repo_url=workspace.repo_url,
            ),
        )
    )
    feedback = scm.add_pr_feedback(
        pull_request.external_id,
        "Please add one more adapter regression test.",
        author="reviewer",
        path="tests/test_scm_protocol.py",
        line=21,
        metadata={"category": "tests"},
    )
    feedback_items = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            workspace_key=workspace.workspace_key,
            pr_external_id=pull_request.external_id,
        )
    )

    assert workspace.local_path == "/tmp/mock-scm/repo-1"
    assert workspace.repo_ref == "main"
    assert branch.from_ref == "main"
    assert commit.commit_sha == "mock-commit-0001"
    assert pushed.branch_url == "https://example.test/repo/tree/task18/scm-boundary"
    assert pull_request.external_id == "1"
    assert pull_request.pr_metadata.execute_task_external_id == "TASK-18"
    assert feedback.comment_id == "comment-1"
    assert feedback_items.items == [feedback]
    assert feedback_items.next_page_cursor is None
    assert feedback_items.latest_cursor == feedback.comment_id


def test_mock_scm_isolates_state_from_mutation_after_writes_and_reads() -> None:
    scm = MockScm()
    workspace_payload = ScmWorkspaceEnsurePayload(
        repo_url="https://example.test/repo.git",
        repo_ref="main",
        workspace_key="repo-1",
        metadata={"owner": "platform"},
    )
    scm.ensure_workspace(workspace_payload)
    workspace_payload.metadata["owner"] = "mutated"

    branch_payload = ScmBranchCreatePayload(
        workspace_key="repo-1",
        branch_name="task18/scm-boundary",
        metadata={"source": "task18"},
    )
    scm.create_branch(branch_payload)
    branch_payload.metadata["source"] = "mutated"

    pull_request = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="repo-1",
            branch_name="task18/scm-boundary",
            base_branch="main",
            title="Define SCM boundary",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="TASK-18",
                workspace_key="repo-1",
                repo_url="https://example.test/repo.git",
                metadata={"root_task": "TASK-1"},
            ),
        )
    )
    feedback = scm.add_pr_feedback(
        pull_request.external_id,
        "Please add one more contract test.",
        metadata={"severity": "medium"},
    )

    feedback.metadata["severity"] = "low"
    feedback.pr_metadata.metadata["root_task"] = "TASK-2"

    stored_feedback = scm.read_pr_feedback(ScmReadPrFeedbackQuery()).items[0]
    stored_workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-1",
        )
    )

    assert stored_workspace.metadata == {"owner": "platform"}
    assert stored_feedback.metadata == {"severity": "medium"}
    assert stored_feedback.pr_metadata.metadata == {"root_task": "TASK-1"}


def test_mock_scm_filters_feedback_by_cursor_and_branch() -> None:
    scm = MockScm()
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-1",
        )
    )
    scm.create_branch(ScmBranchCreatePayload(workspace_key="repo-1", branch_name="task18/first"))
    first_pr = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="repo-1",
            branch_name="task18/first",
            base_branch="main",
            title="First PR",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="TASK-18",
                workspace_key="repo-1",
                repo_url="https://example.test/repo.git",
            ),
        )
    )
    first_feedback = scm.add_pr_feedback(first_pr.external_id, "First comment")
    scm.add_pr_feedback(first_pr.external_id, "Second comment")

    scm.create_branch(ScmBranchCreatePayload(workspace_key="repo-1", branch_name="task18/second"))
    second_pr = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="repo-1",
            branch_name="task18/second",
            base_branch="main",
            title="Second PR",
            pr_metadata=ScmPullRequestMetadata(
                execute_task_external_id="TASK-19",
                workspace_key="repo-1",
                repo_url="https://example.test/repo.git",
            ),
        )
    )
    scm.add_pr_feedback(second_pr.external_id, "Other branch comment")

    filtered_feedback = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            branch_name="task18/first",
            since_cursor=first_feedback.comment_id,
        )
    )

    assert [item.body for item in filtered_feedback.items] == ["Second comment"]
    assert filtered_feedback.next_page_cursor is None
    assert filtered_feedback.latest_cursor == "comment-2"


def test_mock_scm_uses_mock_pr_url_for_non_http_repositories() -> None:
    scm = MockScm()
    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="git@example.test:team/repo.git",
            repo_ref="main",
            workspace_key="repo-ssh",
        )
    )
    scm.create_branch(
        ScmBranchCreatePayload(
            workspace_key=workspace.workspace_key,
            branch_name="task32/mock-url",
        )
    )

    pushed = scm.push_branch(
        ScmPushBranchPayload(
            workspace_key=workspace.workspace_key,
            branch_name="task32/mock-url",
        )
    )
    pull_request = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key=workspace.workspace_key,
            branch_name="task32/mock-url",
            base_branch="main",
            title="Use mock URLs",
            pr_metadata=ScmPullRequestMetadata(execute_task_external_id="TASK-32"),
        )
    )

    assert pushed.branch_url is None
    assert pull_request.url == "mock-scm://pull/1"


def test_mock_scm_preserves_workspace_metadata_when_update_metadata_empty() -> None:
    scm = MockScm()
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="main",
            workspace_key="repo-1",
            metadata={"owner": "platform"},
        )
    )

    updated = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://example.test/repo.git",
            repo_ref="develop",
            workspace_key="repo-1",
        )
    )

    assert updated.repo_ref == "develop"
    assert updated.metadata == {"owner": "platform"}


def test_mock_scm_uses_existing_local_directory_as_workspace_path(tmp_path) -> None:
    scm = MockScm()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url=str(repo_dir),
            repo_ref="main",
            workspace_key="repo-local",
        )
    )

    assert workspace.local_path == str(repo_dir.resolve())


def test_mock_scm_uses_existing_file_uri_as_workspace_path(tmp_path) -> None:
    scm = MockScm()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url=repo_dir.resolve().as_uri(),
            repo_ref="main",
            workspace_key="repo-file-uri",
        )
    )

    assert workspace.local_path == str(repo_dir.resolve())
