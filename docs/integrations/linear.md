# Linear Tracker Integration

## Purpose

This page documents the durable surface of the `TRACKER_ADAPTER=linear`
adapter (`src/backend/adapters/linear_tracker.py`). It is the operator
reference for wiring a Linear workspace to the Heavy Lifting orchestrator
and the contributor reference for the behaviours other workers rely on.

`docs/contracts/task-handoff.md` defines the payload shapes that move
between stages; this page defines how those shapes are mapped to and
from Linear's GraphQL API.

## Place In The Architecture

The Linear adapter is a `TrackerProtocol` implementation. It is consumed
by:

- **Worker 1 / Loop 1** (`src/backend/workers/tracker_intake.py`) calls
  `fetch_tasks` once per `TRACKER_POLL_INTERVAL` seconds.
- **Worker 3 / Loop 3** (`src/backend/workers/deliver_worker.py`) calls
  `add_comment`, `update_status`, and `attach_links` to deliver results.
- The orchestrator and pre-processing steps may call `create_task` and
  `create_subtask` when they need to write a new tracker record.

The factory `_build_linear_tracker` in `src/backend/composition.py` is
registered under the key `"linear"` and is selected when
`TRACKER_ADAPTER=linear`.

`tracker_name` recorded in the database is taken from
`settings.tracker_adapter`, so switching adapters does not require any
code changes in the workers.

## Environment Variables

The adapter is configured entirely through environment variables exposed
by `src/backend/settings.py`. The complete list:

| Variable | Default | Required | Purpose |
| --- | --- | --- | --- |
| `LINEAR_API_URL` | `https://api.linear.app/graphql` | no | GraphQL endpoint. Override only for self-hosted proxies. |
| `LINEAR_TOKEN_ENV_VAR` | `LINEAR_API_KEY` | yes | **Name** of the env var that holds the personal API key. The value is read lazily at every GraphQL call, never at startup. |
| `LINEAR_API_KEY` (or whatever `LINEAR_TOKEN_ENV_VAR` points to) | - | yes (at runtime) | The personal API key itself, format `lin_api_…`. Generated in Linear → Settings → Account → Security & access → API keys. |
| `LINEAR_TEAM_ID` | - | yes | UUID of the team the adapter writes to. Validated when the runtime container is built. |
| `LINEAR_REQUEST_TIMEOUT_SECONDS` | `30` | no | Per-request HTTP timeout. |
| `LINEAR_FETCH_LABEL_ID` | - | no | Extra label filter applied to `fetch_tasks`. Only issues carrying this label will be ingested. |
| `LINEAR_STATE_ID_NEW` | - | recommended | Workflow state UUID written when creating an issue with `TaskStatus.NEW`. If empty, the adapter falls back to the lowest-position state of type `unstarted` (or `backlog`). |
| `LINEAR_STATE_ID_PROCESSING` | - | recommended | Same, for `TaskStatus.PROCESSING` (fallback type: `started`). |
| `LINEAR_STATE_ID_DONE` | - | recommended | Same, for `TaskStatus.DONE` (fallback type: `completed`). |
| `LINEAR_STATE_ID_FAILED` | - | recommended | Same, for `TaskStatus.FAILED` (fallback type: `canceled`). |
| `LINEAR_FETCH_STATE_TYPES` | `triage,backlog,unstarted` | no | CSV of `state.type` values that count as "new" during polling. |
| `LINEAR_TASK_TYPE_LABEL_MAPPING` | `{}` | no | JSON object mapping `TaskType` values (`fetch`, `execute`, `deliver`, `pr_feedback`) to label UUIDs. Unknown keys are warned and skipped. |
| `LINEAR_MAX_PAGES` | `4` | no | Hard cap on the number of pagination round-trips per `fetch_tasks` call. |
| `LINEAR_DESCRIPTION_WARN_THRESHOLD` | `50000` | no | Soft length limit for issue `description`. Exceeding it logs a warning but does not fail the request. |

Why explicit `state_id` rather than `state.type`: a single Linear
workflow may contain multiple states of the same type (for example two
`started` states). Selecting by `type` for **writes** would be
non-deterministic, so the adapter requires either an explicit UUID or a
deterministic fallback (`min(position)` within the desired type).

## How To Discover IDs From Linear

Linear's web UI does not display the UUIDs of teams, workflow states, or
labels. Use the GraphQL API directly. All snippets below assume the API
key is exported as `LINEAR_API_KEY`:

```bash
export LINEAR_API_KEY=lin_api_xxxxxxxxxxxx
```

### 1. Find your `LINEAR_TEAM_ID`

```bash
curl -sS \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query { teams { nodes { id key name } } }"}' \
  https://api.linear.app/graphql
```

Pick the `id` of the team you want the orchestrator to operate on.
`key` is the short prefix shown in Linear (e.g. `ENG`); `id` is the UUID
needed by `LINEAR_TEAM_ID`.

### 2. Find `LINEAR_STATE_ID_*`

Workflow states belong to a team. Replace `<TEAM_ID>` with the value
from the previous step:

```bash
curl -sS \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query":"query($id: String!) { team(id:$id) { states { nodes { id name type position } } } }",
    "variables":{"id":"<TEAM_ID>"}
  }' \
  https://api.linear.app/graphql
```

For each `TaskStatus`, pick the `id` of the state you want the
orchestrator to write:

| `TaskStatus` | Pick a state with `type` ∈ |
| --- | --- |
| `NEW` | `unstarted` (or `backlog` if the team has no `unstarted`) |
| `PROCESSING` | `started` |
| `DONE` | `completed` |
| `FAILED` | `canceled` (Linear uses the American spelling, one `l`) |

If multiple states share the desired type, prefer the one with the
lowest `position` — that matches the adapter's fallback rule, so a future
omission of the env var still selects the same state.

### 3. Find label UUIDs for `LINEAR_TASK_TYPE_LABEL_MAPPING` and `LINEAR_FETCH_LABEL_ID`

```bash
curl -sS \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query":"query($id: String!) { team(id:$id) { labels { nodes { id name } } } }",
    "variables":{"id":"<TEAM_ID>"}
  }' \
  https://api.linear.app/graphql
```

Use the `id` values to populate the mapping. Example:

```
LINEAR_TASK_TYPE_LABEL_MAPPING={"execute":"<label-uuid-1>","deliver":"<label-uuid-2>"}
LINEAR_FETCH_LABEL_ID=<label-uuid-for-orchestrator-intake>
```

Keys must be lower-case `TaskType` values (`fetch`, `execute`, `deliver`,
`pr_feedback`); unknown keys are logged as
`linear_task_type_label_mapping_unknown_key` and dropped at startup so a
single typo does not block runtime assembly.

## Status Mapping

### Direct mapping (writes)

`create_task`, `create_subtask`, and `update_status` translate
`TaskStatus` to a Linear `stateId` in two steps:

1. Look up `LINEAR_STATE_ID_<STATUS>`. If set, use it.
2. Otherwise resolve the team's workflow states (cached after the first
   call) and pick the lowest-`position` state whose `type` matches the
   table below. The result is cached in memory for the lifetime of the
   adapter.

| `TaskStatus` | Fallback `state.type` priority |
| --- | --- |
| `NEW` | `unstarted` → `backlog` |
| `PROCESSING` | `started` |
| `DONE` | `completed` |
| `FAILED` | `canceled` |

If neither an explicit env nor a fallback state is found, the adapter
raises `RuntimeError` with a hint pointing at the missing env var.

### Reverse mapping (reads)

`fetch_tasks` maps Linear `state.type` back to `TaskStatus`:

| `state.type` | `TaskStatus` |
| --- | --- |
| `triage` | `NEW` (toggle via `LINEAR_FETCH_STATE_TYPES`) |
| `backlog` | `NEW` |
| `unstarted` | `NEW` |
| `started` | `PROCESSING` |
| `completed` | `DONE` |
| `canceled` | `FAILED` |

`triage` is read-only by design: the adapter ingests issues sitting in
the team's triage queue but never writes them back into a triage state
through `update_status`. Some Linear workflows reject `stateId` updates
into triage, and forcing it would make the worker brittle.

## Service Block In Issue Description

Linear custom fields require the Plus plan, so the adapter carries
orchestrator-specific metadata (`repo_url`, `repo_ref`, `workspace_key`,
and `input_payload`) inside the issue `description`, between two HTML
comment markers:

```
<!-- heavy-lifting:input -->
{
  "repo_url": "https://github.com/org/repo",
  "repo_ref": "main",
  "workspace_key": "org-repo",
  "input": {
    "instructions": "Сделать что-то полезное",
    "base_branch": "main",
    "branch_name": "feat/something"
  }
}
<!-- /heavy-lifting:input -->
```

Behaviour:

- **On read (`fetch_tasks`):** the block is parsed with stdlib
  `json.loads`. `repo_url`, `repo_ref`, `workspace_key` are mapped to the
  identically named `TrackerTask` fields. The `input` object is fed to
  `TaskInputPayload.model_validate(...)` (Pydantic, `extra="forbid"`).
  Any parse error logs `linear_input_block_invalid_json` /
  `linear_input_payload_invalid` and leaves the corresponding
  `TrackerTask` fields as `None` — the issue is still ingested.
- **On write (`create_task`, `create_subtask`):** the adapter serialises
  any of `repo_url`, `repo_ref`, `workspace_key`, `input_payload` that
  are present back into the same block and appends it to the
  user-supplied description so a later poll round-trip can recover them.
- **Length guard:** if the resulting `description` exceeds
  `LINEAR_DESCRIPTION_WARN_THRESHOLD` characters (default 50 000), the
  adapter logs `linear_description_warn_threshold_exceeded` but still
  sends the mutation. Linear has been observed to fail silently on very
  large descriptions; the warning gives early diagnostics without false
  rejections on borderline cases.

The block is human-readable JSON on purpose: an operator inspecting an
issue in Linear can paste it into a JSON editor without bespoke tooling.

## Pagination And Sorting

`fetch_tasks` issues `query LinearFetchIssues(...)` with
`orderBy: createdAt` so newest issues come first. Without an explicit
order, a backlog of thousands of `unstarted`/`backlog` issues could push
fresh tickets past `LINEAR_MAX_PAGES`. `updatedAt` is intentionally
**not** used: any edit to an old ticket would float it back to the top
and create polling noise.

Per page the adapter requests `first = min(remaining, 250)` (Linear's
own page cap). The query loop stops when:

- `len(collected) >= query.limit`, or
- `pageInfo.hasNextPage == false`, or
- `pages_done >= LINEAR_MAX_PAGES`.

Hitting the page cap with more pages still available logs
`linear_fetch_max_pages_reached` so the operator can either raise the
cap or tighten the filters.

## Rate Limiting

Linear's documented limit is 5 000 GraphQL requests per hour per API
key. With `TRACKER_POLL_INTERVAL=30` Worker 1 alone makes ~120 calls per
hour, so the budget is comfortable even with delivery traffic from
Worker 3.

A rate-limit response can arrive in two shapes — both are mapped to
`LinearRateLimitError(RuntimeError)`:

- HTTP 429 from the transport layer.
- HTTP 200/400 with a GraphQL `errors[]` entry whose
  `extensions.code == "RATELIMITED"`.

The adapter does **not** sleep or retry inside a single call. Spreading
the recovery over the worker's normal poll interval keeps SLA reasoning
local to the worker loop.

## Worker Behaviour On Adapter Errors

`TrackerIntakeWorker.poll_once` (Worker 1) calls `tracker.fetch_tasks`
inside a single try/except (`src/backend/workers/tracker_intake.py`):
any exception is logged as `tracker_poll_failed` and re-raised. The
adapter therefore raises **narrow** error classes so the log is
informative:

- `LinearRateLimitError` — rate-limited, see above.
- `RuntimeError("LINEAR token env var X is empty")` — missing API key.
- `RuntimeError("Linear GraphQL HTTP <status> at <url>")` — transport
  failure.
- `RuntimeError("Linear GraphQL errors at <url>: ...")` — GraphQL
  `errors[]` (other than `RATELIMITED`).
- `RuntimeError("Linear GraphQL transport error at <url>: ...")` —
  `URLError` from `urllib`.

Restarting the loop is the orchestrator's responsibility, not the
adapter's. The next `TRACKER_POLL_INTERVAL` tick continues where the
previous one stopped.

Worker 3 calls (`add_comment`, `update_status`, `attach_links`) follow
the same pattern: errors propagate, and the deliver loop decides
retries.

## Idempotency

- `fetch_tasks` is idempotent by construction. Worker 1 deduplicates via
  `find_fetch_task_by_tracker_task` keyed on
  `(tracker_name, external_task_id)`.
- `attach_links` relies on Linear's idempotency by `(issueId, url)` — a
  repeat `attachmentCreate` for the same URL updates the existing
  attachment instead of producing a duplicate.
- `add_comment` is **not** idempotent. The deliver worker is responsible
  for deciding whether to retry.

## Security

- The API key value is never logged. Errors and `repr(LinearTracker)`
  intentionally omit it; only the **name** of the env var (e.g.
  `LINEAR_API_KEY`) appears in log lines and exception messages.
- The `Authorization` header value is never written to logs even when
  the GraphQL response is short-circuited into an error.

## Limitations And Out-Of-Scope

- **Custom fields**: require the Linear Plus plan. The MVP routes
  metadata through the JSON service block instead. Migrating to custom
  fields is a future task and does not require schema changes in
  `TrackerTask`.
- **Webhook ingestion**: out of scope. Loop 1 is poll-based; a webhook
  flow would need an HTTP endpoint and a separate worker.
- **Triage writes**: the adapter reads issues out of triage but never
  writes them back into a triage state via `update_status`.
- **Description size**: the adapter warns above
  `LINEAR_DESCRIPTION_WARN_THRESHOLD`; it does not split or compress
  descriptions.

## Source References

- GraphQL / auth / errors: <https://linear.app/developers/graphql>
- Pagination: <https://linear.app/developers/pagination>
- Filtering: <https://linear.app/developers/filtering>
- Rate limiting: <https://linear.app/developers/rate-limiting>
- Workflow statuses: <https://linear.app/docs/configuring-workflows>
- Attachments: <https://linear.app/developers/attachments>
