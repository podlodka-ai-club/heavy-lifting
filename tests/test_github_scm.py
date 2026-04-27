from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from backend.adapters.github_scm import (
    GitHubApiError,
    GitHubResponse,
    GitHubScm,
    GitHubScmConfig,
    _git_auth_args,
)
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


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self._responders: list = []

    def add_response(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        self._responders.append((stdout, stderr, returncode))

    def add_failure(self, *, stderr: str = "boom", returncode: int = 1) -> None:
        self._responders.append((None, stderr, returncode))

    def run(
        self, args: list[str], cwd: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, cwd))
        if not self._responders:
            stdout, stderr, returncode = "", "", 0
        else:
            stdout, stderr, returncode = self._responders.pop(0)
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, args, output=stdout or "", stderr=stderr or ""
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout or "",
            stderr=stderr or "",
        )


class LeakyCalledProcessRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []

    def run(
        self, args: list[str], cwd: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, cwd))
        raise subprocess.CalledProcessError(
            1,
            [
                "git",
                "-c",
                "http.extraHeader=Authorization: Basic c2VjcmV0",
                "clone",
                "https://github.com/acme/widgets",
            ],
            stderr="invalid credentials for secret",
        )


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Mapping[str, str] | None]] = []
        self._responses: list[GitHubResponse | GitHubApiError] = []

    def add_response(self, response: GitHubResponse | GitHubApiError) -> None:
        self._responses.append(response)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, str] | None = None,
    ) -> GitHubResponse:
        self.calls.append((method, path, body, query))
        response = self._responses.pop(0)
        if isinstance(response, GitHubApiError):
            raise response
        return response


def _build_config(workspace_root: Path, *, default_repo_url: str | None = None) -> GitHubScmConfig:
    return GitHubScmConfig(
        api_base_url="https://api.github.com",
        token_env_var="GITHUB_TOKEN_TEST",
        user_name="hl-bot",
        user_email="hl@example.test",
        default_remote="origin",
        workspace_root=workspace_root,
        default_repo_url=default_repo_url,
    )


def test_git_auth_args_uses_basic_x_access_token_header() -> None:
    token = "ghu_test_token"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")

    args = _git_auth_args(token)

    assert args == ["-c", f"http.extraHeader=Authorization: Basic {encoded}"]
    assert (
        base64.b64decode(
            args[1].removeprefix("http.extraHeader=Authorization: Basic ")
        ).decode("utf-8")
        == f"x-access-token:{token}"
    )


def test_git_auth_args_returns_empty_list_without_token() -> None:
    assert _git_auth_args(None) == []
    assert _git_auth_args("") == []


def test_github_scm_implements_scm_protocol(tmp_path) -> None:
    scm = GitHubScm(
        _build_config(tmp_path),
        runner=FakeRunner(),
        http_client=FakeHttpClient(),
    )

    assert isinstance(scm, ScmProtocol)


def test_ensure_workspace_clones_when_missing_and_checks_out_repo_ref(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()  # clone
    runner.add_response()  # checkout
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-1",
            repo_ref="develop",
        )
    )

    assert workspace.repo_url == "https://github.com/acme/widgets"
    assert workspace.repo_ref == "develop"
    expected_local_path = (tmp_path / "widgets-1").resolve()
    assert workspace.local_path == str(expected_local_path)

    clone_args, clone_cwd = runner.calls[0]
    assert clone_args[0] == "git"
    assert "clone" in clone_args
    assert "https://github.com/acme/widgets" in clone_args
    assert str(expected_local_path) in clone_args
    assert clone_cwd == str(tmp_path)

    checkout_args, checkout_cwd = runner.calls[1]
    assert checkout_args == ["git", "checkout", "develop"]
    assert checkout_cwd == str(expected_local_path)


def test_ensure_workspace_resolves_default_branch_when_repo_ref_absent(tmp_path) -> None:
    repo_dir = tmp_path / "widgets-2"
    repo_dir.mkdir()
    runner = FakeRunner()
    runner.add_response()  # fetch
    runner.add_response(stdout="origin/main\n")  # symbolic-ref
    runner.add_response()  # checkout
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-2",
        )
    )

    assert workspace.repo_ref == "main"
    fetch_args, _ = runner.calls[0]
    assert "fetch" in fetch_args
    assert "origin" in fetch_args
    sym_args, _ = runner.calls[1]
    assert sym_args[1:] == ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]


def test_ensure_workspace_uses_default_repo_url_when_payload_missing(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()  # clone
    runner.add_response()  # checkout
    scm = GitHubScm(
        _build_config(tmp_path, default_repo_url="https://github.com/acme/default-repo"),
        runner=runner,
        http_client=FakeHttpClient(),
    )

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(workspace_key="default-1", repo_ref="main")
    )

    assert workspace.repo_url == "https://github.com/acme/default-repo"
    clone_args, _ = runner.calls[0]
    assert "https://github.com/acme/default-repo" in clone_args


def test_ensure_workspace_payload_overrides_default_repo_url(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    scm = GitHubScm(
        _build_config(tmp_path, default_repo_url="https://github.com/acme/default-repo"),
        runner=runner,
        http_client=FakeHttpClient(),
    )

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/override-repo",
            workspace_key="override-1",
            repo_ref="main",
        )
    )

    assert workspace.repo_url == "https://github.com/acme/override-repo"
    clone_args, _ = runner.calls[0]
    assert "https://github.com/acme/override-repo" in clone_args


def test_ensure_workspace_raises_when_no_repo_url_anywhere(tmp_path) -> None:
    scm = GitHubScm(_build_config(tmp_path), runner=FakeRunner(), http_client=FakeHttpClient())

    with pytest.raises(RuntimeError, match="GITHUB_DEFAULT_REPO_URL"):
        scm.ensure_workspace(ScmWorkspaceEnsurePayload(workspace_key="missing"))


def test_safe_workspace_path_rejects_traversal(tmp_path) -> None:
    scm = GitHubScm(_build_config(tmp_path), runner=FakeRunner(), http_client=FakeHttpClient())

    for bad_key in ("..", "../escape", "/abs/path", "foo/bar", ""):
        with pytest.raises(ValueError):
            scm.ensure_workspace(
                ScmWorkspaceEnsurePayload(
                    repo_url="https://github.com/acme/widgets",
                    workspace_key=bad_key,
                )
            )


def test_create_branch_uses_default_remote_from_config(tmp_path) -> None:
    runner = FakeRunner()
    # ensure_workspace: clone + checkout
    runner.add_response()
    runner.add_response()
    # create_branch: fetch + checkout -B
    runner.add_response()
    runner.add_response()
    config = GitHubScmConfig(
        api_base_url="https://api.github.com",
        token_env_var="GITHUB_TOKEN_TEST",
        user_name=None,
        user_email=None,
        default_remote="upstream",
        workspace_root=tmp_path,
        default_repo_url=None,
    )
    scm = GitHubScm(config, runner=runner, http_client=FakeHttpClient())

    workspace = scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-3",
            repo_ref="main",
        )
    )
    scm.create_branch(
        ScmBranchCreatePayload(
            workspace_key=workspace.workspace_key,
            branch_name="feature/new",
        )
    )

    fetch_args, _ = runner.calls[2]
    assert "fetch" in fetch_args
    assert "upstream" in fetch_args
    checkout_args, _ = runner.calls[3]
    assert "upstream/main" in checkout_args
    assert "-B" in checkout_args


def test_commit_changes_raises_on_empty_diff(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()  # clone
    runner.add_response()  # checkout
    runner.add_response(stdout="")  # status --porcelain
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-4",
            repo_ref="main",
        )
    )

    with pytest.raises(RuntimeError, match="no changes to commit"):
        scm.commit_changes(
            ScmCommitChangesPayload(
                workspace_key="widgets-4",
                branch_name="feature/x",
                message="apply",
            )
        )


def test_commit_changes_returns_rev_parse_head(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    runner.add_response(stdout="M  file.py\n")  # status
    runner.add_response()  # add -A
    runner.add_response()  # commit
    runner.add_response(stdout="abc123def\n")  # rev-parse
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-5",
            repo_ref="main",
        )
    )

    commit = scm.commit_changes(
        ScmCommitChangesPayload(
            workspace_key="widgets-5",
            branch_name="feature/y",
            message="apply changes",
        )
    )

    assert commit.commit_sha == "abc123def"
    commit_args, _ = runner.calls[4]
    assert "commit" in commit_args
    assert "user.name=hl-bot" in commit_args
    assert "user.email=hl@example.test" in commit_args


def test_push_branch_returns_branch_url_for_https_repo(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()  # clone
    runner.add_response()  # checkout
    runner.add_response()  # push
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-6",
            repo_ref="main",
        )
    )

    pushed = scm.push_branch(
        ScmPushBranchPayload(workspace_key="widgets-6", branch_name="feature/z")
    )

    assert pushed.branch_url == "https://github.com/acme/widgets/tree/feature/z"


def test_push_branch_returns_branch_url_for_ssh_repo(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    runner.add_response()
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="git@github.com:acme/widgets.git",
            workspace_key="widgets-7",
            repo_ref="main",
        )
    )

    pushed = scm.push_branch(
        ScmPushBranchPayload(workspace_key="widgets-7", branch_name="feature/x")
    )

    assert pushed.branch_url == "https://github.com/acme/widgets/tree/feature/x"


def test_push_branch_returns_branch_url_for_ghe_host(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    runner.add_response()
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=FakeHttpClient())
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://ghe.example.test/acme/widgets",
            workspace_key="widgets-ghe",
            repo_ref="main",
        )
    )

    pushed = scm.push_branch(
        ScmPushBranchPayload(workspace_key="widgets-ghe", branch_name="feature/x")
    )

    assert pushed.branch_url == "https://ghe.example.test/acme/widgets/tree/feature/x"


def test_create_pull_request_embeds_pr_metadata_footer(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    http = FakeHttpClient()
    http.add_response(
        GitHubResponse(
            status=201,
            headers={},
            body={"number": 42, "html_url": "https://github.com/acme/widgets/pull/42"},
        )
    )
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-8",
            repo_ref="main",
        )
    )

    pr_metadata = ScmPullRequestMetadata(
        execute_task_external_id="TASK-1",
        tracker_name="linear",
        workspace_key="widgets-8",
        repo_url="https://github.com/acme/widgets",
        metadata={"hl_origin": "test", "tricky": "html-->endtag\nnewline"},
    )
    pr = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="widgets-8",
            branch_name="feature/x",
            base_branch="main",
            title="Test PR",
            body="Hello",
            pr_metadata=pr_metadata,
        )
    )

    assert pr.external_id == "42"
    method, path, body, _ = http.calls[0]
    assert method == "POST"
    assert path == "/repos/acme/widgets/pulls"
    pr_body = body["body"]
    assert "Hello" in pr_body
    assert "<!-- heavy-lifting:pr-metadata:v1 " in pr_body

    # Round-trip: extract footer and decode metadata
    footer_token = pr_body.split("<!-- heavy-lifting:pr-metadata:v1 ")[1].split(" -->")[0]
    padding = "=" * (-len(footer_token) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(footer_token + padding).decode("utf-8"))
    assert decoded["execute_task_external_id"] == "TASK-1"
    assert decoded["metadata"]["tricky"] == "html-->endtag\nnewline"


def test_create_pull_request_falls_back_to_existing_on_422(tmp_path) -> None:
    runner = FakeRunner()
    runner.add_response()
    runner.add_response()
    http = FakeHttpClient()
    http.add_response(
        GitHubApiError(
            status=422,
            method="POST",
            url="https://api.github.com/repos/acme/widgets/pulls",
            body_excerpt=(
                '{"errors":[{"message":"A pull request already exists '
                'for acme:feature/x."}]}'
            ),
        )
    )
    http.add_response(
        GitHubResponse(
            status=200,
            headers={},
            body=[
                {"number": 7, "html_url": "https://github.com/acme/widgets/pull/7"},
            ],
        )
    )
    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    scm.ensure_workspace(
        ScmWorkspaceEnsurePayload(
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-9",
            repo_ref="main",
        )
    )

    pr = scm.create_pull_request(
        ScmPullRequestCreatePayload(
            workspace_key="widgets-9",
            branch_name="feature/x",
            base_branch="main",
            title="Test PR",
            pr_metadata=ScmPullRequestMetadata(execute_task_external_id="TASK-2"),
        )
    )

    assert pr.external_id == "7"
    list_call = http.calls[1]
    assert list_call[0] == "GET"
    assert list_call[1] == "/repos/acme/widgets/pulls"
    assert list_call[3] == {"head": "acme:feature/x", "state": "open"}


def test_read_pr_feedback_merges_three_sources_and_maps_review_state(tmp_path) -> None:
    runner = FakeRunner()
    http = FakeHttpClient()
    pr_metadata = ScmPullRequestMetadata(
        execute_task_external_id="TASK-3",
        tracker_name="linear",
        workspace_key="widgets-10",
        repo_url="https://github.com/acme/widgets",
        metadata={},
    )
    issue_response = [
        {
            "id": 100,
            "user": {"login": "alice"},
            "body": "Issue comment",
            "updated_at": "2026-01-01T10:00:00Z",
            "created_at": "2026-01-01T10:00:00Z",
        }
    ]
    review_comment_response = [
        {
            "id": 200,
            "user": {"login": "bob"},
            "body": "Inline comment",
            "path": "src/foo.py",
            "line": 7,
            "side": "RIGHT",
            "commit_id": "deadbeef",
            "updated_at": "2026-01-01T11:00:00Z",
            "created_at": "2026-01-01T11:00:00Z",
        }
    ]
    review_response = [
        {
            "id": 300,
            "user": {"login": "carol"},
            "body": None,
            "state": "APPROVED",
            "submitted_at": "2026-01-01T12:00:00Z",
            "commit_id": "cafebabe",
        },
        {
            "id": 301,
            "user": {"login": "dave"},
            "body": "needs work",
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-01-01T13:00:00Z",
        },
    ]
    http.add_response(GitHubResponse(status=200, headers={}, body=issue_response))
    http.add_response(GitHubResponse(status=200, headers={}, body=review_comment_response))
    http.add_response(GitHubResponse(status=200, headers={}, body=review_response))
    # Then PR body fetch:
    http.add_response(
        GitHubResponse(
            status=200,
            headers={},
            body={"body": "PR body without footer"},
        )
    )

    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    result = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            workspace_key="widgets-10",
        )
    )

    bodies = [item.body for item in result.items]
    assert bodies == [
        "Issue comment",
        "Inline comment",
        "(approved without comment)",
        "needs work",
    ]
    review_item = result.items[2]
    assert review_item.metadata["event_kind"] == "pr_review_approved"
    assert review_item.metadata["review_state"] == "APPROVED"
    changes_item = result.items[3]
    assert changes_item.metadata["event_kind"] == "pr_review_requested_changes"
    assert review_item.path is None and review_item.line is None
    inline = result.items[1]
    assert inline.path == "src/foo.py"
    assert inline.line == 7

    # All four items used the unresolved sentinel pr_metadata since PR body has no footer.
    for item in result.items:
        assert item.pr_metadata.metadata.get("_hl_unresolved") is True
    _ = pr_metadata  # silence unused


def test_read_pr_feedback_skip_free_pagination(tmp_path) -> None:
    """At limit=2 the merged set of 3 items must paginate without skips/dupes."""

    runner = FakeRunner()
    http = FakeHttpClient()
    issue_items = [
        {
            "id": 1,
            "body": "i1",
            "user": {"login": "a"},
            "updated_at": "2026-01-01T10:00:00Z",
        },
        {
            "id": 2,
            "body": "i2",
            "user": {"login": "a"},
            "updated_at": "2026-01-01T11:00:00Z",
        },
    ]
    review_comment_items = [
        {
            "id": 50,
            "body": "rc1",
            "user": {"login": "b"},
            "updated_at": "2026-01-01T12:00:00Z",
        },
    ]
    # First call: page=1 for all three sources, no rel="next".
    http.add_response(GitHubResponse(status=200, headers={}, body=issue_items))
    http.add_response(GitHubResponse(status=200, headers={}, body=review_comment_items))
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    # PR body fetch on first call:
    http.add_response(GitHubResponse(status=200, headers={}, body={"body": ""}))

    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    first = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            limit=2,
        )
    )
    assert [item.body for item in first.items] == ["i1", "i2"]
    assert first.next_page_cursor is not None
    # Issue source fully consumed but page exhausted (<per_page=2 already at 2). It should be "*".
    # review_comment had only 1 item, page exhausted: "*".
    # We did not return any review_comment in first response — it should be re-readable next time.
    # Actually with our algorithm, an item from review_comment was loaded but trimmed.
    # On next call, issue should be "*", review_comment should be at offset=0 (re-read), review "*".

    # Second call — same review_comment page is fetched again (offset reset since not advanced):
    http.add_response(GitHubResponse(status=200, headers={}, body=review_comment_items))
    http.add_response(GitHubResponse(status=200, headers={}, body={"body": ""}))

    second = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            limit=2,
            page_cursor=first.next_page_cursor,
        )
    )
    assert [item.body for item in second.items] == ["rc1"]
    # All sources should now be exhausted.
    assert second.next_page_cursor is None


def test_read_pr_feedback_extracts_pr_metadata_from_footer(tmp_path) -> None:
    runner = FakeRunner()
    http = FakeHttpClient()
    http.add_response(
        GitHubResponse(
            status=200,
            headers={},
            body=[
                {
                    "id": 1,
                    "body": "i1",
                    "user": {"login": "a"},
                    "updated_at": "2026-01-01T10:00:00Z",
                }
            ],
        )
    )
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))

    pr_metadata = ScmPullRequestMetadata(
        execute_task_external_id="TASK-99",
        tracker_name="linear",
        workspace_key="repo-99",
        repo_url="https://github.com/acme/widgets",
    )
    payload_bytes = json.dumps(pr_metadata.model_dump(mode="json"), separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    pr_body = f"some body\n\n<!-- heavy-lifting:pr-metadata:v1 {encoded} -->"
    http.add_response(GitHubResponse(status=200, headers={}, body={"body": pr_body}))

    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    result = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
        )
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.pr_metadata.execute_task_external_id == "TASK-99"
    assert item.pr_metadata.tracker_name == "linear"
    assert item.pr_metadata.metadata.get("_hl_unresolved") is None


def test_read_pr_feedback_does_not_skip_loaded_item_after_filtered_tail(tmp_path) -> None:
    """Page contains [loaded_first, loaded_leftover, filtered_invalid] with limit=1.

    Old code summed filtered_out + returned and would advance offset by 2,
    skipping the loaded-but-not-returned item entirely. The fixed code stops
    counting at the first loaded-but-not-returned entry.
    """

    runner = FakeRunner()
    http = FakeHttpClient()
    issue_items = [
        {
            "id": 1,
            "user": {"login": "a"},
            "body": "first",
            "updated_at": "2026-01-01T10:00:00Z",
        },
        {
            "id": 2,
            "user": {"login": "b"},
            "body": "second",
            "updated_at": "2026-01-01T11:00:00Z",
        },
        # Invalid: missing required `id` -> _build_feedback_item returns None.
        {"user": {"login": "c"}, "body": "broken", "updated_at": "2026-01-01T12:00:00Z"},
    ]
    http.add_response(GitHubResponse(status=200, headers={}, body=issue_items))
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    http.add_response(GitHubResponse(status=200, headers={}, body={"body": ""}))

    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    first = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            limit=1,
        )
    )
    assert [item.body for item in first.items] == ["first"]
    assert first.next_page_cursor is not None
    # issue source: 1 returned, 1 loaded-leftover at index 1, 1 filtered at index 2.
    # Old buggy code advanced offset to 2, skipping "second". Fixed code stops at index 1.
    assert "issue@1@1" in first.next_page_cursor

    # Second call: re-read the page from offset=1 -> [second, broken].
    http.add_response(GitHubResponse(status=200, headers={}, body=issue_items))
    http.add_response(GitHubResponse(status=200, headers={}, body={"body": ""}))

    second = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            limit=1,
            page_cursor=first.next_page_cursor,
        )
    )
    assert [item.body for item in second.items] == ["second"]


def test_read_pr_feedback_advances_cursor_when_since_filters_all_items(tmp_path) -> None:
    """If every raw item is filtered by since_cursor, the cursor must still advance."""

    runner = FakeRunner()
    http = FakeHttpClient()
    # Reviews endpoint is filtered client-side, since GitHub does not honor `since`.
    review_items = [
        {
            "id": 1,
            "user": {"login": "a"},
            "body": "old approval",
            "state": "APPROVED",
            "submitted_at": "2026-01-01T08:00:00Z",
        },
        {
            "id": 2,
            "user": {"login": "b"},
            "body": "old changes",
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-01-01T09:00:00Z",
        },
    ]
    # issue + review_comment empty, only review has stale items below since_cursor.
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    http.add_response(GitHubResponse(status=200, headers={}, body=[]))
    http.add_response(GitHubResponse(status=200, headers={}, body=review_items))

    scm = GitHubScm(_build_config(tmp_path), runner=runner, http_client=http)
    since = "2026-01-01T23:59:59Z|review|9999"

    result = scm.read_pr_feedback(
        ScmReadPrFeedbackQuery(
            pr_external_id="42",
            repo_url="https://github.com/acme/widgets",
            since_cursor=since,
        )
    )

    # All review items are below since_cursor -> filtered -> empty result.
    assert result.items == []
    # Critical: cursor must terminate; we should NOT loop forever in tracker_intake.
    assert result.next_page_cursor is None
    assert result.latest_cursor == since


def test_read_pr_feedback_requires_repo_context(tmp_path) -> None:
    scm = GitHubScm(_build_config(tmp_path), runner=FakeRunner(), http_client=FakeHttpClient())

    with pytest.raises(RuntimeError, match="repo_url"):
        scm.read_pr_feedback(ScmReadPrFeedbackQuery(pr_external_id="42"))


def test_git_runner_failure_does_not_expose_secret_in_cause_or_context(
    monkeypatch,
) -> None:
    secret = "secret"
    encoded_secret = base64.b64encode(secret.encode()).decode("ascii")
    monkeypatch.setenv("GITHUB_TOKEN_TEST", secret)
    runner = LeakyCalledProcessRunner()
    scm = GitHubScm(
        _build_config(Path.cwd()), runner=runner, http_client=FakeHttpClient()
    )

    with pytest.raises(RuntimeError) as exc_info:
        scm.ensure_workspace(
            ScmWorkspaceEnsurePayload(
                repo_url="https://github.com/acme/widgets",
                workspace_key="repo-fail",
                repo_ref="main",
            )
        )

    raised = exc_info.value

    assert str(raised) == "git command failed: invalid credentials for ***"
    assert raised.__cause__ is None
    assert raised.__context__ is None

    for rendered in (
        repr(raised),
        repr(raised.__cause__),
        repr(raised.__context__),
    ):
        assert secret not in rendered
        assert encoded_secret not in rendered
