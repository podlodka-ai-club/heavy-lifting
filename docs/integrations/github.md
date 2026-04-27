# GitHub SCM Integration

## Purpose

This page documents the durable surface of the `SCM_ADAPTER=github`
adapter (`src/backend/adapters/github_scm.py`). It is the operator
reference for wiring a GitHub repository to the Heavy Lifting orchestrator
and the contributor reference for the behaviours other workers rely on.

`docs/contracts/event-ingestion.md` defines how PR feedback is normalized
into `TaskInputPayload.pr_feedback`; this page defines how the GitHub
adapter populates those payloads from `git` and the GitHub REST API.

## Place In The Architecture

The GitHub adapter is an `ScmProtocol` implementation
(`src/backend/protocols/scm.py`). It is consumed by:

- **Worker 2** (`src/backend/workers/execute_worker.py`) calls
  `ensure_workspace`, `create_branch`, `commit_changes`, `push_branch`,
  and `create_pull_request` to materialise an agent's diff as a GitHub
  pull request.
- **Worker 1** (`src/backend/workers/tracker_intake.py`) calls
  `read_pr_feedback` once per `PR_POLL_INTERVAL` seconds for every
  execute task that has an open PR.

The factory `_build_github_scm` in `src/backend/composition.py` is
registered under the key `"github"` and is selected when
`SCM_ADAPTER=github`.

## Environment Variables

| Variable | Default | Required | Purpose |
| --- | --- | --- | --- |
| `GITHUB_API_BASE_URL` | `https://api.github.com` | no | REST endpoint. For GitHub Enterprise set `https://<host>/api/v3`. |
| `GITHUB_TOKEN_ENV_VAR` | `GITHUB_TOKEN` | no | **Name** of the env var that holds the PAT or installation token. The value is read lazily on every call. |
| `GITHUB_TOKEN` (or whatever `GITHUB_TOKEN_ENV_VAR` points to) | - | yes (at runtime) | The token itself, scoped to repo contents and pull requests. |
| `GITHUB_USER_NAME` | - | no | `git -c user.name=...` value used for commits. Falls back to the global git config. |
| `GITHUB_USER_EMAIL` | - | no | `git -c user.email=...` value used for commits. |
| `GITHUB_DEFAULT_REMOTE` | `origin` | no | Name of the remote used for `fetch`/`push`/default-branch resolution. |
| `GITHUB_DEFAULT_REPO_URL` | - | no | Default `repo_url` for single-repo deployments. If a task does not carry `repo_url`, the adapter clones this URL. Per-task `repo_url` always overrides the default. |
| `SCM_DEFAULT_BASE_BRANCH` | - | no | SCM-agnostic fallback for `base_branch` resolution in Worker 2. Used when neither the task nor `repo_ref` defines one; final fallback is `main`. |
| `SCM_BRANCH_PREFIX` | `execute/` | no | SCM-agnostic prefix for auto-generated branch names. Worker 2 builds `<prefix><slug-of-tracker-id>`. |
| `WORKSPACE_ROOT` | `/workspace/repos` | no | Filesystem root for cloned repositories. The adapter refuses workspace keys that escape this root. |

`SCM_*` keys are not GitHub-specific by name because they live in the
SCM-agnostic `ExecuteWorker`. They keep the same meaning if you swap the
adapter for `mock` or a future GitLab/Bitbucket implementation.

## Single-repo vs Multi-repo Deployment

| Scenario | `.env.local` | Tracker issue service block |
| --- | --- | --- |
| **Single-repo** (1 team → 1 repo, typical) | Set `GITHUB_DEFAULT_REPO_URL`, optionally `SCM_DEFAULT_BASE_BRANCH=main`. | Only `instructions` is required. `repo_url`/`base_branch`/`branch_name` may be omitted. |
| **Multi-repo** (1 team → many repos) | Leave `GITHUB_DEFAULT_REPO_URL` unset. | Every issue must include its own `repo_url`. |
| **Hybrid** | Set `GITHUB_DEFAULT_REPO_URL` to the primary repo. | Issues without `repo_url` go to the primary; issues with explicit `repo_url` go to their own repo. |

If neither the operator nor the tracker provides `repo_url`,
`ensure_workspace` raises `RuntimeError("repo_url required: set
GITHUB_DEFAULT_REPO_URL or pass per-task repo_url")`. The error names
both fixes so the operator can choose.

After `ensure_workspace` resolves the final URL, Worker 2 writes it back
to the `tasks` row via `TaskRepository.update_task_workspace_context`.
The next polling cycle (and any child PR_FEEDBACK tasks created from PR
comments) sees the resolved URL as if it had been there from the start.

## Authentication

- The adapter never injects the token into the remote URL; it would leak
  through `git remote -v`. Instead it passes
  `git -c http.extraHeader="Authorization: Basic <base64("x-access-token:<token>")>"`
  for the duration of `clone`/`fetch`/`push`. This format works for
  classic PATs, fine-grained PATs, and GitHub App installation tokens.
- HTTP requests use a separate REST client path that keeps
  `Authorization: Bearer <token>` unchanged.
- `_sanitize_token` is applied to `git` stderr inside `_git_run`, so
  `RuntimeError("git command failed: ...")` cannot echo the token even
  if `git` itself prints it. HTTP responses do not contain the token —
  it lives only in the request `Authorization` header, never in the
  URL — so `GitHubApiError` does not run a second pass of token
  stripping. It exposes `status`, `method`, `url` (as constructed by
  the adapter) and a `body_excerpt` truncated to the first 500
  characters of the response body.

## Workspace Path Safety

`workspace_key` is treated as untrusted input. The helper
`_safe_workspace_path`:

1. rejects empty strings, `.`, `..`, NUL, `/`, `\`, and absolute paths;
2. resolves `(workspace_root / workspace_key)` and confirms it is a
   subpath of `workspace_root.resolve()`.

Anything else raises `ValueError`.

## Pull Request Body Footer

`create_pull_request` appends a machine-readable footer to the PR body:

```
<!-- heavy-lifting:pr-metadata:v1 <BASE64URL_NO_PADDING(json_bytes)> -->
```

The payload is `ScmPullRequestMetadata.model_dump(mode="json")` encoded
as compact JSON. base64url is used so HTML-comment delimiters,
newlines, NUL bytes, and the `-->` sequence inside metadata cannot
break the marker. The version tag (`:v1`) reserves room for future
schema changes.

`read_pr_feedback` calls `GET /repos/{owner}/{repo}/pulls/{number}` at
most once per invocation (skipped when no feedback items are returned
by the three list endpoints below), finds the footer with a strict
regex, and decodes it.
If the footer is absent (legacy PR, edited body, fork mismatch), the
adapter returns each feedback item with sentinel metadata
`{"_hl_unresolved": true}`. `tracker_intake._ingest_pr_feedback` then
rebuilds `pr_metadata` from the matching execute task's
`(execute_task_external_id, tracker_name, workspace_key, repo_url)`
before persisting the feedback as a child task.

## PR Feedback Sources And Pagination

`read_pr_feedback` merges three GitHub endpoints:

| `metadata.event_kind` | Endpoint | Notes |
| --- | --- | --- |
| `pr_comment` (issue) | `GET /repos/{o}/{r}/issues/{n}/comments` | General PR conversation. |
| `pr_comment` (review_comment) | `GET /repos/{o}/{r}/pulls/{n}/comments` | Inline diff comments. `path`/`line`/`side`/`commit_sha` populated. |
| `pr_review_approved` / `pr_review_requested_changes` / `pr_comment` | `GET /repos/{o}/{r}/pulls/{n}/reviews` | Review verdict. `commit_sha` populated. Empty review bodies are normalized to `(approved without comment)` for `APPROVED`, `(changes requested without comment)` for `CHANGES_REQUESTED`, and `(review without comment)` for `COMMENTED` or any other state, so `PrFeedbackPayload.body` stays non-empty. |

`comment_id` is namespaced as `<source>-<numeric_id>` so collisions
across endpoints are impossible.

The composite item cursor is `<iso_updated_at>|<source>|<numeric_id>`.
Sorting and `since_cursor` filtering use the tuple
`(updated_at, source, numeric_id)` so equal-timestamp comments are
neither dropped nor duplicated.

The page cursor is
`issue@<page>@<offset>:review_comment@<page>@<offset>:review@<page>@<offset>`
where `<page>` is GitHub's 1-based pagination index, `<offset>` is the
number of items already returned from that page, and `*` marks an
exhausted source. A repeated call with the same `next_page_cursor` is
idempotent: only the leftover items are returned, no items are
re-emitted, no items are skipped.

`reviews` does not support `since`, so the adapter applies it
client-side. On large PRs (hundreds of reviews) this is an O(n) scan;
that is documented as a known limitation in
`docs/contracts/event-ingestion.md`.

## Idempotency And Edge Cases

- `ensure_workspace`: clones if the local path is missing, otherwise
  fetches. Always runs `git checkout` to land on the requested ref.
- `create_branch`: uses `git checkout -B`, so re-runs reset the branch
  to the resolved `from_ref`.
- `commit_changes`: empty `git status --porcelain` raises
  `RuntimeError("no changes to commit")` to fail fast rather than
  produce empty PRs.
- `create_pull_request`: a 422 with `"already exists"` triggers
  `GET /repos/{o}/{r}/pulls?head=<owner>:<branch>&state=open` and
  returns the existing PR.

## GitHub Enterprise

`_parse_repo_location` extracts the host from `repo_url`, so HTML URLs
(`branch_url`, fallback PR URL) work for any host. Set
`GITHUB_API_BASE_URL=https://<host>/api/v3` to point the REST client at
the enterprise installation; the adapter does not auto-derive the suffix
because GHE versions differ.

## Worker Behaviour On Adapter Errors

Errors propagate to the caller. Worker 2 marks the task `failed` with
the error message; Worker 1 logs `pr_feedback_poll_failed` and re-raises
so the next `PR_POLL_INTERVAL` tick retries. Notable error classes:

- `RuntimeError("repo_url required: ...")` — neither default nor
  per-task URL provided.
- `RuntimeError("no changes to commit")` — agent produced an empty
  diff.
- `RuntimeError("git command failed: ...")` — sanitized git stderr
  (token replaced with `***`).
- `GitHubApiError` — non-2xx HTTP, surfaces `status`, `method`, `url`,
  and a 500-char `body_excerpt`.

## Limitations

- **Footer in PR body**: an admin or reviewer can delete the footer by
  editing the PR description. The fallback enrichment in Worker 1
  recovers the metadata, but a future iteration should persist
  `pr_metadata` directly on `tasks` instead of relying on the body.
- **Reviews `since` filter**: GitHub's reviews endpoint does not accept
  `since`; the adapter scans every page client-side.
- **Large clones**: the MVP performs full clones. `--filter=blob:none`
  partial clones are a future optimisation.

## Source References

- REST PRs: <https://docs.github.com/en/rest/pulls>
- REST issues comments: <https://docs.github.com/en/rest/issues/comments>
- REST review comments: <https://docs.github.com/en/rest/pulls/comments>
- REST reviews: <https://docs.github.com/en/rest/pulls/reviews>
- Pagination Link header: <https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api>
- GHE: <https://docs.github.com/en/enterprise-server>
