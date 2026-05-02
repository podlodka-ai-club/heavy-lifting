# Event Ingestion

## Purpose

This page defines how follow-up events enter the MVP orchestrator after the initial task intake.

It complements:

- `docs/contracts/triage-routing.md` for first-intake routing;
- `docs/contracts/task-handoff.md` for how normalized follow-up work is represented in tasks and payloads.

## Scope

Event ingestion covers signals that arrive after or alongside the original task intake and may require a new internal reaction.

For the MVP, the orchestrator distinguishes two entry categories:

- `new_task_intake` - a brand-new tracker task that starts with triage;
- `followup_event` - a tracker or SCM event that attaches to an existing task thread or creates a child follow-up task.

The key rule is that follow-up events must not be confused with first-time intake.

## MVP Event Taxonomy

The MVP supports these normalized follow-up event kinds:

- `tracker_comment` - a new comment on an existing tracker task;
- `tracker_status_change` - a relevant tracker-side status change on an existing task;
- `pr_comment` - a review or discussion comment attached to an open PR;
- `pr_review_requested_changes` - a PR review that requests changes;
- `pr_review_approved` - a PR review that approves the change set;
- `pr_state_change` - a PR state transition such as closed or merged.

Not every event kind must produce a new executable task. Some events may be recorded and ignored for routing if they do not require action in the MVP.

## Event Recording Rule

In the MVP, "recorded" follow-up events do not require a separate general-purpose event store.

Instead, the orchestrator records only the minimum durable facts needed for deterministic behavior:

- deduplication identity needed to avoid creating the same child task twice;
- linkage from the normalized event to the owning task thread or PR thread;
- any task-record metadata update that affects orchestration state;
- child task creation when the event is actionable.

If an event does not create a child task and does not change orchestration state, it may be dropped after deduplication.

This means the MVP contract supports two observable outcomes for a follow-up event:

- `metadata_only` - update task-thread metadata and create no child task;
- `create_child_task` - create a new `execute`, `pr_feedback`, or `tracker_feedback` child task.

## Normalized Event Envelope

Before routing, external events should be normalized into one envelope shape:

- `schema_version`
- `event_source` - `tracker` or `scm`
- `event_kind` - normalized kind from the MVP taxonomy
- `external_event_id` - source-native stable identifier when available
- `external_parent_id` - tracker task id or PR id the event belongs to
- `occurred_at`
- `author`
- `title` - optional short label
- `body` - optional event text
- `metadata` - source-specific non-routing details

Normalization removes source-specific naming differences before deduplication and routing.

## Source-Specific Normalization Rules

### Tracker Events

- A new tracker task remains `new_task_intake`, not `tracker_comment`.
- A tracker comment on an existing task becomes `tracker_comment`.
- For the current MVP slice, `worker1` polls tracker comments only for estimate-only `execute` threads that already resolved without SCM artifacts.
- The tracker read contract is `TrackerReadCommentsQuery(external_task_id, since_cursor, page_cursor, limit) -> TrackerReadCommentsResult(items, next_page_cursor, latest_cursor)`.
- `latest_cursor` is persisted on the owning execute task as `context.metadata.tracker_comment_cursor` so repeated polls stay idempotent.
- System-authored tracker comments created by the orchestrator carry `metadata.source = heavy_lifting` and must be ignored during polling.
- A tracker status update becomes `tracker_status_change` only if the change matters to orchestration decisions.
- Tracker attachments or formatting-only edits may be stored as metadata and ignored for routing in the MVP.

### SCM Events

- PR discussion comments normalize to `pr_comment`.
- Review objects requesting changes normalize to `pr_review_requested_changes`.
- Review objects approving the PR normalize to `pr_review_approved`.
- PR close or merge transitions normalize to `pr_state_change`.

If an SCM platform emits several representations of the same review action, the orchestrator should normalize them into one canonical event before deduplication.

#### GitHub adapter mapping

The `SCM_ADAPTER=github` adapter merges three GitHub endpoints when answering `read_pr_feedback`:

| Source                       | Endpoint                                 | `comment_id`          | `metadata.event_kind`         |
| ---------------------------- | ---------------------------------------- | --------------------- | ----------------------------- |
| issue                        | `GET /repos/{o}/{r}/issues/{n}/comments` | `issue-<id>`          | `pr_comment`                  |
| review_comment               | `GET /repos/{o}/{r}/pulls/{n}/comments`  | `review_comment-<id>` | `pr_comment`                  |
| review (`APPROVED`)          | `GET /repos/{o}/{r}/pulls/{n}/reviews`   | `review-<id>`         | `pr_review_approved`          |
| review (`CHANGES_REQUESTED`) | same                                     | `review-<id>`         | `pr_review_requested_changes` |
| review (`COMMENTED`)         | same                                     | `review-<id>`         | `pr_comment`                  |

Empty review bodies are normalized to `(approved without comment)` or `(changes requested without comment)` so `PrFeedbackPayload.body` stays non-empty. The original GitHub `state` is preserved in `metadata.review_state`.

#### Composite cursors and skip-free pagination

Each feedback item carries a composite cursor `<iso_updated_at>|<source>|<numeric_id>`. Sorting and `since_cursor` filtering use the tuple `(updated_at, source, numeric_id)`, so equal-timestamp comments are neither dropped nor duplicated.

`next_page_cursor` is encoded as `issue@<page>@<offset>:review_comment@<page>@<offset>:review@<page>@<offset>`, where `<page>` is GitHub's 1-based pagination index, `<offset>` is the count of items already returned from that page, and `*` marks an exhausted source. A repeated call with the same `next_page_cursor` is idempotent — leftover items are returned, none are skipped, none are duplicated.

`reviews` does not support a `since` query parameter; the adapter applies `since_cursor` filtering client-side. On large PRs (hundreds of reviews) this is an O(n) scan — known limitation.

#### `pr_metadata` recovery

`ScmReadPrFeedbackQuery` carries `repo_url`, `workspace_key`, and `branch_name` from the owning execute task so the adapter can target the right repo even before workspace caches warm up. The adapter restores `ScmPullRequestMetadata` from a base64url footer that `create_pull_request` embeds at the bottom of the PR body:

```
<!-- heavy-lifting:pr-metadata:v1 <BASE64URL_NO_PADDING(json)> -->
```

If the footer is missing (legacy PR, edited body, fork mismatch), each feedback item is returned with sentinel `pr_metadata.metadata = {"_hl_unresolved": true}`. `tracker_intake._ingest_pr_feedback` then rebuilds `pr_metadata` from the matching execute task before persisting the child PR_FEEDBACK task. Long-term we should persist `pr_metadata` directly on `tasks` so this fallback is unnecessary.

#### Durable workspace identity after workspace sync

After Worker 2 calls `ensure_workspace`, the resolved `repo_url` (which may have come from `GITHUB_DEFAULT_REPO_URL` rather than the task) is written back to the `tasks` row via `TaskRepository.update_task_workspace_context`. For normal `execute` flows that arrived without `workspace_key`, Worker 2 first generates a deterministic fallback from the tracker lineage and persists it on the execute task before workspace sync. Subsequent polling cycles and child tasks see the same durable `repo_url` and `workspace_key`.

## Deduplication Rules

Event ingestion must be idempotent. Repeated polling must not create duplicate follow-up tasks.

The preferred deduplication key is:

- `(event_source, external_event_id)` when the source provides a stable event id.

Fallback deduplication should use a composite key built from:

- `event_source`
- `event_kind`
- `external_parent_id`
- `author`
- `occurred_at`

If a source updates an existing comment in place, the MVP should treat it as the same logical event unless the integration explicitly supports edit-version handling later.

## Routing Rules

After normalization and deduplication, the event router decides whether to record only, create a child task, or trigger delivery behavior.

### Tracker Comment

- If the comment adds clarification to a task that is waiting on missing information, record it and create a follow-up `execute` task with `input_payload.action = triage` so the task can be re-assessed.
- If the comment arrives on an estimate-only execute thread, record it and create exactly one `tracker_feedback` child task per new actionable comment id. The child input payload carries the explicit tracker comment payload (`external_task_id`, `comment_id`, `author`, `body`, `url`, `metadata`) so the follow-up reply can stay in the same tracker thread.
- If the comment arrives on an active research or implementation thread and requests additional work that should change execution behavior, record it and create a follow-up `execute` task only when the current thread is explicitly designed to accept that tracker-driven follow-up in the MVP. Otherwise, treat it as `metadata_only` and leave it for human handling.
- If the comment arrives after a rejection or after terminal delivery, treat it as a new human signal on the existing external task and do not reopen the thread automatically in the MVP.
- If the comment is informational and does not change routing, treat it as `metadata_only`.

### Tracker Status Change

- If the status change materially affects whether work should continue, treat it as `metadata_only` on the owning task thread.
- `tracker_status_change` does not create a child task by itself in the MVP.
- A later worker step may read that task-thread metadata and decide how to continue, but the event-ingestion layer itself does not translate tracker status changes into executable work.

### PR Comment Or Requested Changes

- `pr_comment` and `pr_review_requested_changes` may create a child `pr_feedback` task when they require implementation follow-up.
- The child task should reuse the original branch and PR thread and set `input_payload.action = respond_pr`.
- Feedback-only events that do not require action may be recorded without spawning a new task.

### PR Approved Or PR State Change

- `pr_review_approved` is normally treated as `metadata_only` and does not create a new child task by itself in the MVP.
- `pr_state_change` may update orchestration state as `metadata_only`, but it does not automatically create a new implementation task unless a later rule requires that behavior.

## Task Creation Rules

The MVP follow-up task creation rules are:

- brand-new tracker tasks create a new thread that starts at triage;
- clarification-bearing tracker comments may create a new `execute` task for re-triage;
- estimate-only tracker follow-up comments may create a `tracker_feedback` child task that replies back into the same tracker thread without SCM side effects;
- other tracker comments are `metadata_only` unless a later MVP rule explicitly promotes them into actionable follow-up work;
- tracker status changes are `metadata_only` in the MVP;
- actionable PR feedback may create a new `pr_feedback` child task;
- PR approvals and PR state changes are `metadata_only` unless a later rule explicitly changes that behavior;
- delivery tasks are still created only from upstream `result_payload.delivery`, not directly from raw external events.

This keeps event ingestion separate from the worker handoff contract: external events first become normalized facts, then routing decides whether to create a task.

## Responsibility Split

### MVP Recommendation

In the MVP, keep periodic event polling inside the current ingestion layer owned by `worker1`, but separate the responsibilities logically:

- intake responsibility - fetch new tracker tasks and create first-step triage work;
- monitor responsibility - poll tracker follow-up comments and SCM follow-up events, normalize them, deduplicate them, and create child tasks when needed.

This means the MVP can stay on one worker process while preserving a future boundary for a dedicated monitor worker.

### Future Evolution

If event volume or latency needs grow, the monitor responsibility can move into a dedicated worker without changing the durable event taxonomy or follow-up routing rules.

## Monitoring Rules

The monitor path should guarantee:

- repeated polls are safe because deduplication is idempotent;
- follow-up events are linked to the correct task thread or PR thread;
- actionable PR feedback becomes `pr_feedback` work rather than a new top-level intake task;
- actionable estimate-only tracker comments become `tracker_feedback` work rather than a new top-level intake task;
- tracker comments that unblock clarification return to triage instead of bypassing the routing model.

## MVP Limits

- The MVP does not require real-time webhooks.
- The MVP does not require a separate persisted event store beyond what is needed to prevent duplicate task creation.
- The MVP does not require automatic business handling for every tracker or PR event type.
- The MVP does not reopen closed implementation threads automatically from arbitrary follow-up chatter.
