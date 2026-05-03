# Triage And Routing

## Purpose

This page defines how the MVP triage step interprets a new tracker task and chooses the next business path.

It complements `docs/contracts/task-handoff.md`:

- this page defines triage signals, outcomes, and routing decisions;
- `docs/contracts/task-handoff.md` defines how those decisions are represented in `input_payload` and `result_payload`.

## Triage Responsibility

Triage is the mandatory first business step for every newly ingested tracker task.

In the MVP:

- `worker1` ingests the external task and creates the first executable task;
- `worker2` runs triage inside an `execute` task with `input_payload.action = triage`;
- triage decides whether the system should stop at a tracker reply or continue into another executable step.

Triage does not implement the task itself. It produces a business classification, an estimate, and a routing decision.

## MVP Business Task Kinds

The MVP supports these business task kinds:

- `research` - the system should inspect context and answer with findings or use research to prepare a later implementation step;
- `implementation` - the system should modify code, configuration, or repository state;
- `clarification` - the request is potentially valid, but required information is missing or ambiguous;
- `review_response` - a follow-up iteration driven by PR feedback rather than a new intake task;
- `rejected` - the request should not be taken into work in its current form.

For new tracker intake, triage normally classifies into `research`, `implementation`, `clarification`, or `rejected`. `review_response` is primarily produced by the PR feedback flow, not by first-intake triage.

## Triage Signals

Triage should rely on explicit signals rather than free-text intuition alone.

The MVP signal set is:

- `goal_defined` - the request states a concrete desired outcome;
- `repo_scope_present` - the repository or target code area is known when code work is requested;
- `acceptance_clear` - success conditions are explicit enough to evaluate completion;
- `code_change_requested` - the task explicitly asks for implementation work;
- `analysis_only_requested` - the task asks for investigation, explanation, or estimation without code changes;
- `missing_required_info` - a blocker exists because essential inputs are absent;
- `out_of_scope` - the request falls outside the MVP or current delivery boundaries;
- `unsafe_or_prohibited` - the requested action violates project rules or execution constraints.

Signals may be derived from tracker fields, normalized task metadata, or structured heuristics captured in `result_payload.classification.signals`.

Signal roles in the MVP are:

- `missing_required_info`, `out_of_scope`, and `unsafe_or_prohibited` can directly determine the routing outcome.
- `code_change_requested` and `analysis_only_requested` determine the primary work mode when no blocker wins first.
- `goal_defined`, `repo_scope_present`, and `acceptance_clear` are support signals: they raise confidence when present and may justify deriving `missing_required_info` when an implementation or research request is too underspecified to continue safely.

## Triage Outcomes

Triage must end in one of these routing outcomes:

- `route_to_research` - create a follow-up `execute` task with `input_payload.action = research`;
- `route_to_implementation` - create a follow-up `execute` task with `input_payload.action = implementation`;
- `reply_with_research_only` - create a downstream `deliver` task that returns findings without opening a longer execution branch;
- `reply_with_clarification` - create a downstream `deliver` task that asks the tracker for missing information;
- `reply_with_rejection` - create a downstream `deliver` task that explains why the task is not accepted;
- `reply_with_estimate_only` - create a downstream `deliver` task that returns an estimate or intake decision without further execution yet.

The "only estimate" scenario is a routing outcome, not a separate business task kind.

`reply_with_estimate_only` is used when the intake explicitly asks for estimation or take-in-work assessment, and triage has enough information to answer that question without launching research or implementation.

A legacy text heuristic (`_should_skip_scm_artifacts` matching `story point` together with `do not modify code` markers) remains in the worker for backwards compatibility but is deprecated. The current MVP runtime distinguishes triage and implementation through `input_payload.action` rather than free-text matching: `worker1` (`tracker_intake`) sets `action = "triage"` on the first execute task, and `worker2` routes that task into the dedicated triage path that never touches branches, commits, or PRs regardless of the description content.

The deprecated heuristic will be removed once all callers migrate to the `action`-based path; until then it is logged as a fallback but does not affect routing for tasks that already carry an explicit `action` value.

## Routing Matrix

The MVP routing matrix is:

| Primary signals                                                         | Classification   | Outcome                    | Next task            |
| ----------------------------------------------------------------------- | ---------------- | -------------------------- | -------------------- |
| `missing_required_info`                                                 | `clarification`  | `reply_with_clarification` | downstream `deliver` |
| `unsafe_or_prohibited` or `out_of_scope`                                | `rejected`       | `reply_with_rejection`     | downstream `deliver` |
| explicit estimate-only request and enough context to assess now         | `research`       | `reply_with_estimate_only` | downstream `deliver` |
| `analysis_only_requested` and enough context to answer now              | `research`       | `reply_with_research_only` | downstream `deliver` |
| `analysis_only_requested` and more investigation is needed              | `research`       | `route_to_research`        | follow-up `execute`  |
| `code_change_requested` and inputs are clear enough to proceed directly | `implementation` | `route_to_implementation`  | follow-up `execute`  |
| `code_change_requested` but extra investigation is needed before coding | `research`       | `route_to_research`        | follow-up `execute`  |

When multiple signals conflict, triage resolves them in this priority order:

1. rejection conditions;
2. clarification blockers;
3. research-only requests;
4. implementation requests.

Rejection wins over clarification when both apply. If a request is clearly prohibited or out of scope, triage should reject it rather than ask for more detail.

## Story Point Estimation

Triage produces an estimate as one of six allowed Story Point values: `1`, `2`, `3`, `5`, `8`, `13`. No other values are valid; the agent prompt forbids interpolation such as `4`, `6`, or `10`.

The Story Point value drives downstream routing and tracker writes:

| Story Points | State                                          | Routing                                   | Sibling impl-execute? | Tracker labels (added)        | `delivery.escalation_kind` |
| ------------ | ---------------------------------------------- | ----------------------------------------- | --------------------- | ----------------------------- | -------------------------- |
| 1            | Zero-shot, all context available               | `route_to_implementation`                 | yes                   | `sp:1`, `triage:ready`        | `null`                     |
| 2            | Local dependencies (1-2 files)                 | `route_to_implementation`                 | yes                   | `sp:2`, `triage:ready`        | `null`                     |
| 3            | Multiple modules, edge cases, dependency graph | `route_to_implementation`                 | yes                   | `sp:3`, `triage:ready`        | `null`                     |
| 5            | Information deficit                            | `reply_with_clarification` (RFI)          | no                    | `sp:5`, `triage:rfi`          | `rfi`                      |
| 8            | Macro-task / epic                              | reply with decomposition plan             | no                    | `sp:8`, `triage:split`        | `decomposition`            |
| 13           | Architectural ambiguity                        | hard block, escalate to system design     | no                    | `sp:13`, `triage:block`       | `system_design`            |

For Story Points `1`, `2`, or `3`, triage stores a Handover Brief in `result_payload.metadata.handover_brief` (full markdown) and copies the same text inline into the new sibling implementation task as `input_payload.handoff.brief_markdown`. The implementation worker reads this brief through `EffectiveTaskContext.handover_brief` (resolved primarily from the inline handoff, with a repository fallback to the originating triage task).

For Story Points `5`, `8`, or `13`, triage produces a tracker-facing markdown comment (`## RFI`, `## Decomposition`, or `## Needs System Design`) and stores it in `result_payload.delivery.comment_body`. No follow-up executable task is created for these escalations; the next triage cycle starts only when the tracker user edits the issue (detected through a content hash; see `## Re-Triage Protocol`).

The resulting executable tasks form a sibling structure under one `fetch` parent:

```
fetch
  |-- execute(action=triage, DONE)
  |     `-- deliver (tracker labels + comment, no status update)
  `-- execute(action=implementation, NEW)         <-- only for SP 1/2/3
        `-- deliver (PR summary, may update status to DONE)
```

The implementation execute is a sibling of triage (both have `parent_id = fetch.id`), not a child. This avoids implementation and its deliver picking up the triage result through `ContextBuilder._find_relevant_execute_for_current`.

## Tracker State Semantics

Triage never updates the tracker issue status itself. The triage `deliver` task sets `result_payload.delivery.tracker_status = null`, so `worker3` skips `update_status` and only calls `add_comment` and `update_estimate`. The tracker issue stays in its incoming state until a later step (typically the implementation `deliver`) explicitly closes it.

Special workflow states such as "Needs Decomposition" or "Needs System Design" are expressed through `delivery.tracker_labels` (`triage:split`, `triage:block`) and a tracker comment, not through new `TaskStatus` enum values. The internal `tasks.status` column remains in the base `{new, processing, done, failed}` set: a successful triage resolves to `DONE` regardless of the Story Point outcome, because the operation completed; the lack of follow-up implementation is encoded in the routing and delivery sections of the payload.

## Re-Triage Protocol

The orchestrator does not continue automatically after an SP `5/8/13` escalation: the tracker user must either edit the issue or reopen it for a fresh triage cycle to start. The protocol below is materialized in `tracker_intake._ingest_tracker_task` and is regression-tested end to end in `tests/test_retriage_pipeline_smoke.py` plus the unit suites `tests/test_tracker_intake_retriage.py` (user-edit detection) and `tests/test_tracker_intake_retriage_impl.py` (impl-state handling and reopen scenarios).

### User-edit detection

`compute_user_content_hash` (in `backend.services.user_content_hash`) builds a SHA-256 over `TrackerTask.context.title`, `description`, `acceptance_criteria`, and the subset of `references` whose `TaskLink.origin != "own_write"`. The hash deliberately excludes `TrackerTask.metadata` and own-write references, so our own `add_comment`, `update_estimate`, and `attach_links` operations can never invalidate the hash.

The first intake stores the initial hash in `fetch.context.metadata.last_triage_user_content_hash`. Subsequent intakes recompute the hash and compare with the stored value:

- equal hash → `content_changed = false`;
- different hash → `content_changed = true`. The orchestrator refreshes `fetch.context` (including references) wholesale to the latest tracker snapshot. The stored hash is bumped to the new value **only** when no triage execute is currently `PROCESSING`; otherwise the hash is left untouched so the user edit is not lost when the in-flight triage finishes.

### Reopen detection

A reopen is treated as an independent trigger that can fire even when the content hash has not changed:

- `tracker_task.status == NEW`;
- a DONE implementation execute exists (`done_impl`);
- the deliver task that owns the closing `update_status(DONE)` for that impl has itself reached `DONE` (`done_impl_delivered`);
- there is no other in-flight triage or impl;
- the reopen has not already been consumed for this specific `done_impl` (see consumed-marker below).

Without `done_impl_delivered`, the orchestrator would interpret the brief race window between `impl execute → DONE` and `deliver_impl → DONE` (during which Linear status is still in its initial `NEW`) as a reopen and create a phantom triage on every poll.

### Reopen-consumed marker

The first time a reopen creates a new triage, the orchestrator records `fetch.context.metadata.last_reopen_consumed_done_impl_id = done_impl.id` **before** creating that triage. On any subsequent poll where the reopen conditions still hold for the same `done_impl.id`, `is_reopen` evaluates to `false` and the intake is a no-op. A future, completed pipeline produces a different `done_impl.id`, which automatically reopens the gate for the next cycle.

This marker prevents a self-loop in the case of `reopen → triage SP=5 → no impl created → next poll → reopen still apparent → another triage → ...`.

### State matrix

When `content_changed` or `is_reopen` is true, the dispatch order inside `_handle_existing_fetch` is:

1. `processing_triage` exists → no-op (the in-flight triage will pick up the refreshed pending context on its next read; user edits during this window are not lost because the hash is left unchanged).
2. `pending_triage` exists → update the triage's `context` with the fresh snapshot; do not create a new execute.
3. `processing_impl` exists → no-op (in-flight; user edits go through PR feedback rather than re-triage).
4. `pending_impl` exists → mark the impl `FAILED` with `error = "superseded_by_user_edit_after_triage_<id>"` and `result_payload.metadata.superseded_reason = "user_edit"`, then create a new triage with the fresh snapshot. The user-edit takes priority over a still-untouched impl so the impl never starts on a stale Handover Brief.
5. `done_impl` exists and `is_reopen` is true → set the reopen-consumed marker, then create a new triage. Otherwise (edit-during-deliver-window or post-pipeline edit without reopen) → no triage is created; the snapshot/hash update alone is enough to capture the edit for the next reopen.
6. The last completed triage was an escalation (`escalation_kind in {rfi, decomposition, system_design}`) and no impl exists → create a new triage.
7. Otherwise (last triage was SP `1/2/3` but no impl exists; legitimately strange state) → no-op; the cluster is investigated through retro-feedback.

`pending_impl` is intentionally checked **before** `done_impl`: under reopen plus repeated edits a fresh `pending_impl` may coexist with an older `done_impl`, and the pending one must always supersede.

### Worker contract for adapters

Tracker adapters must mark every link they attach with `TaskLink.origin = "own_write"` (`MockTracker` sets it directly; `LinearTracker` round-trips it via the attachment `subtitle = "heavy-lifting:own-write"`). Failing to set `origin` correctly causes own-writes to be hashed as user content, which manifests as a re-triage loop on the next poll.

## Result Payload Expectations

The triage step must populate at least:

- `classification.task_kind`
- `classification.signals`
- `estimate.story_points` (one of `1/2/3/5/8/13`)
- `estimate.complexity`
- `estimate.can_take_in_work`
- `estimate.blocking_reasons`
- `routing.next_task_type`
- `routing.next_role`
- `routing.create_followup_task`
- `delivery.tracker_status` (always `null` for triage outcomes)
- `delivery.tracker_estimate` (the Story Point value)
- `delivery.tracker_labels` (`sp:N` plus one of `triage:ready/rfi/split/block`)
- `delivery.escalation_kind` (`null` for SP `1/2/3`; `rfi`/`decomposition`/`system_design` otherwise)
- `delivery.comment_body`

If triage stops at a tracker reply (SP `5/8/13`), `routing.next_task_type` should be `deliver`, `routing.next_role` should be `deliver`, and `routing.create_followup_task` should be `false`.

If triage routes to implementation (SP `1/2/3`), `routing.next_task_type` should be `execute`, `routing.next_role` should be `implementation`, `routing.create_followup_task` should be `true`, and `result_payload.metadata.handover_brief` should carry the full Handover Brief markdown.

If triage returns `reply_with_estimate_only`, `classification.task_kind` should remain `research` for MVP purposes because the system is still answering an analysis-style intake without entering a code-execution branch.

## MVP Limits

- Triage is not a product-prioritization engine.
- Triage does not split one intake task into multiple parallel execution branches.
- Triage does not make permanent roadmap decisions; it chooses the next operational step only.
- Triage does not bypass the structured contract by encoding decisions only in `summary` or `details`.
- Triage does not close the tracker issue; it never sets `tracker_status` and never calls `update_status`.
- Triage does not validate file paths or symbols mentioned in the Handover Brief; downstream implementation is responsible for repository-level checks.
