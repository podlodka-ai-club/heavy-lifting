# Task Handoff Contract

## Purpose

This page defines the MVP v1 contract for the data that moves between orchestrator stages.

The contract separates three concerns:

- `context` stores stable task facts and source material.
- `input_payload` is the command for the current step.
- `result_payload` is the structured result of the current step and the machine-readable handoff to the next one.

## Design Principles

- Routing and delivery decisions must rely on structured fields, not free-text parsing.
- Stable task facts belong in `context`, not repeated in every step payload.
- Step-specific instructions belong in `input_payload`.
- Downstream workers consume `result_payload` from the upstream step instead of inferring intent from logs.
- All payload shapes use `schema_version` so the contract can evolve safely.
- Lineage stays in the task chain and task record fields; large histories must not be copied into every payload.

## Task Record Versus Payloads

The task record carries orchestration metadata such as `task_type`, `status`, repository coordinates, branch state, PR identifiers, and parent-child lineage.

The payload contract complements the task record:

- `context` carries stable business facts and source references.
- `input_payload` carries the current-step command.
- `result_payload` carries machine-readable outcome, routing, delivery instructions, and generated artifacts.

Repository coordinates such as `repo_url`, `repo_ref`, and `workspace_key` remain task-record fields and may be copied into payload metadata only when prompt assembly needs them.

For estimate-selection flows, the tracker task metadata may also carry:

- `metadata.estimate.story_points`
- `metadata.estimate.can_take_in_work`
- `metadata.selection.taken_in_work`

Those fields are tracker-side selection hints only. They do not replace the worker handoff contract and are used only to decide whether the orchestrator should create a new executable tracker subtask. Real tracker adapters may persist and restore them through tracker-specific storage, but downstream workers must consume them only through `TrackerTask.metadata`.

When the orchestrator creates a child subtask from a selected estimated parent, it must also call the tracker claim boundary for that parent so `metadata.selection.taken_in_work` becomes `true` in the real tracker record. This claim happens after successful child creation, while the child keeps its own copied `selection` metadata such as `selected_from_parent_external_id` for lineage.

## Context V1

`context` is stable across the life of a business task thread unless new durable source facts arrive.

It should contain:

- `schema_version`
- `source` - tracker and upstream origin metadata
- `task` - original title, description, acceptance criteria, and references
- `repo` - optional repository hints needed for execution preparation
- `business_context` - optional product/domain facts needed across multiple steps

`context` must not contain step-local commands such as "create a PR now" or "reply with estimate only". Those belong in `input_payload`.

### Context Source Rules

- `fetch.context` stores the normalized tracker task context.
- `execute.context` reuses the stable context prepared earlier for coding work.
- `pr_feedback` tasks inherit the main thread context and add feedback-specific command data through `input_payload`.
- `tracker_feedback` tasks inherit the estimate-only execute context and add tracker-comment-specific command data through `input_payload`.
- Follow-up iteration history lives in child tasks, not as an ever-growing transcript inside `context`.

## Input Payload V1

`input_payload` is the current-step command. It tells the worker or agent what to do now, under which constraints, and what kind of structured output is required.

The contract is materialised in `backend.schemas.TaskInputPayload` as a `pydantic` model with `extra="forbid"`.

### Top-Level Fields

- `schema_version` - contract version, integer; default `1`
- `action` - current step action; one of `triage`, `research`, `implementation`, `respond_pr`, `deliver`, or `null`
- `role` - current step role; may refine `action`, for example `estimate_reply`
- `instructions` - short step-specific instruction
- `constraints` - execution constraints for the step (free `JsonObject`; structured fields will be added when a consumer requires them)
- `handoff` - structured information from the previous step (`TaskHandoffPayload`)
- `expected_output` - required result sections
- `base_branch` - optional base branch for code flows
- `branch_name` - optional branch name for implementation or PR response flows
- `commit_message_hint` - optional commit message hint for code flows
- `pr_feedback` - structured PR feedback input for review-response steps (`PrFeedbackPayload`)
- `tracker_feedback` - structured tracker comment input for tracker-thread follow-up steps
- `metadata` - non-critical extensions that do not change routing semantics

`input_payload` must not duplicate the original problem statement when it already exists in `context`.

### Constraints Fields

`constraints` is currently a free `JsonObject` placeholder; concrete keys will be added when a worker actually consumes them. The keys reserved for future use are:

- `may_touch_repo`
- `may_create_pr`
- `must_run_checks`
- `timebox_minutes`
- `requires_human_approval`

### Handoff Fields

`handoff` is materialised in `backend.schemas.TaskHandoffPayload`:

- `from_task_id` (required)
- `from_role` (required)
- `reason`
- `decision_ref`
- `brief_markdown` - serialized Handover Brief; populated for SP `1/2/3` triage outcomes so the receiving implementation execute can read it inline through `EffectiveTaskContext.handover_brief` without an extra repository lookup

### Expected Output Fields

`expected_output` should identify which result sections are required, for example:

- `classification`
- `estimate`
- `routing`
- `delivery`
- `artifacts`

## Result Payload V1

`result_payload` is the structured outcome of the current step and the input to downstream orchestration decisions.

The contract is materialised in `backend.schemas.TaskResultPayload`. Existing top-level fields `branch_name`, `commit_sha`, `pr_url`, `tracker_comment`, and `links` remain on the payload alongside the new structured sections; readers will migrate to `artifacts` and `delivery` in a follow-up task.

### Top-Level Fields

- `schema_version` - contract version, integer; default `1`
- `outcome` - current step result; one of `completed`, `routed`, `needs_clarification`, `blocked`, `failed`, or `null`
- `summary` - short human-readable result summary (required)
- `details` - optional longer explanation
- `classification` - machine-readable business task classification (`TaskClassificationPayload`)
- `estimate` - story points, complexity, and take-in-work decision (`TaskEstimatePayload`)
- `routing` - next-step instructions for the orchestrator (`TaskRoutingPayload`)
- `delivery` - tracker-ready status and comment instructions for delivery (`TaskDeliveryPayload`)
- `artifacts` - branch, commit, PR, or other generated execution artifacts (`TaskArtifactsPayload`)
- `token_usage` - model usage records when an agent call occurs
- `metadata` - secondary diagnostics and implementation-specific extensions

### Section Rules

`classification` (`TaskClassificationPayload`):

- `task_kind` - one of `research`, `implementation`, `clarification`, `review_response`, `rejected`
- `confidence`
- `signals`

`estimate` (`TaskEstimatePayload`):

- `story_points` - one of `1`, `2`, `3`, `5`, `8`, `13`
- `complexity` - one of `trivial`, `low`, `medium`, `high`, `epic`, `architectural`
- `can_take_in_work`
- `blocking_reasons`

`routing` (`TaskRoutingPayload`):

- `next_task_type` - one of `execute`, `deliver`, `pr_feedback`, or `null`
- `next_role` - one of `triage`, `research`, `implementation`, `deliver`, `respond_pr`, or `null`
- `create_followup_task`
- `requires_human_approval`

`delivery` (`TaskDeliveryPayload`):

- `tracker_status` - base `TaskStatus` value or `null`; must be `null` for triage outcomes so the tracker issue stays in its incoming state
- `tracker_estimate` - integer Story Point value (`1/2/3/5/8/13`) when the upstream step set an estimate
- `tracker_labels` - tracker labels to apply, for example `sp:2` plus `triage:ready`
- `escalation_kind` - one of `rfi`, `decomposition`, `system_design`, or `null`; populated by triage for SP `5/8/13`
- `comment_body`
- `links`

`artifacts` (`TaskArtifactsPayload`):

- `branch_name`
- `commit_sha`
- `pr_url`

## Triage Section Rules

Triage is the first execute step for a new tracker intake. Its `result_payload` shape is fixed by `docs/contracts/triage-routing.md`:

- `outcome` is `routed` for SP `1/2/3`, `needs_clarification` for SP `5`, and `blocked` for SP `8/13`.
- `routing.create_followup_task` is `true` only for SP `1/2/3`; the followup is a sibling implementation execute under the same `fetch` parent.
- `delivery.tracker_status` is always `null`. The triage `deliver` task only writes labels and a comment; closing the tracker issue is the responsibility of a later step.
- `metadata.handover_brief` carries the full Handover Brief markdown for SP `1/2/3`. The same text is also copied inline into `input_payload.handoff.brief_markdown` of the new sibling implementation execute, so the implementation worker can read it through `EffectiveTaskContext.handover_brief` without a separate repository lookup.

Example for a SP=2 triage outcome (abbreviated):

```json
{
  "schema_version": 1,
  "outcome": "routed",
  "summary": "Triage завершён: SP=2, routed to implementer.",
  "classification": {"task_kind": "implementation", "signals": []},
  "estimate": {"story_points": 2, "complexity": "low", "can_take_in_work": true, "blocking_reasons": []},
  "routing": {"next_task_type": "execute", "next_role": "implementation", "create_followup_task": true, "requires_human_approval": false},
  "delivery": {
    "tracker_status": null,
    "tracker_estimate": 2,
    "tracker_labels": ["sp:2", "triage:ready"],
    "escalation_kind": null,
    "comment_body": "Triage SP=2: Brief сохранён, передано в работу.",
    "links": []
  },
  "metadata": {"handover_brief": "## Agent Handover Brief\n..."}
}
```

## Worker Handoff Rules

## Action To Pipeline Mapping

Business-step `action` values describe what the current step is trying to do. Pipeline `task_type` values describe where that step runs in the worker pipeline.

The MVP mapping is:

- `triage` runs inside an `execute` task owned by `worker2`
- `research` runs inside an `execute` task owned by `worker2`
- `implementation` runs inside an `execute` task owned by `worker2`
- `respond_pr` runs inside a `pr_feedback` task owned by `worker2`
- `reply_tracker` runs inside a `tracker_feedback` task owned by `worker2`
- `deliver` runs inside a `deliver` task owned by `worker3`

`fetch` remains an ingestion stage owned by `worker1`. It prepares normalized task records and creates the next executable task, but it does not replace the business-step `action` contract.

### Delivery Task Creation Rule

Whenever an upstream step emits a `result_payload.delivery` section that should be sent to the tracker, the orchestrator creates a downstream `deliver` task for `worker3`.

That rule applies to:

- triage outcomes that end with tracker reply only
- research outcomes that need tracker-visible results
- implementation outcomes after execution completes
- PR feedback outcomes that must be reported back upstream

### Triage

- A new tracker task enters the system with `input_payload.action = triage`. `worker1` (`tracker_intake`) sets this default on the first execute task it creates.
- Triage classifies the business task, estimates Story Points (one of `1/2/3/5/8/13`), and decides the next executable path.
- Triage runs as an `execute` task. For SP `1/2/3` it creates a sibling implementation execute under the same `fetch` parent with `input_payload.action = "implementation"` and `input_payload.handoff.brief_markdown` populated with the Handover Brief. For SP `5/8/13` it stops at the triage `deliver` task and waits for a tracker user edit to start a new triage cycle.
- Triage never sets `delivery.tracker_status`; the tracker issue keeps its incoming status until a later step explicitly closes it.

For the backlog-selection branch, the system may first choose one already estimated parent task and create a tracker subtask that carries the original context, repository coordinates, executable `input_payload`, and selection metadata. That subtask then enters the same `fetch -> execute -> deliver` pipeline as any other tracker intake.

### Research

- A research step uses `input_payload.action = research`.
- It runs as an `execute` task.
- It may produce clarification or implementation routing, but it must still emit delivery instructions for tracker visibility when the tracker should receive the outcome.

### Implementation

- An implementation step uses `input_payload.action = implementation`.
- It runs as an `execute` task.
- It must populate `artifacts` when code changes, commits, branches, or PRs are produced.
- If execution succeeds, routing should allow downstream delivery without parsing free text.

For the current estimate-only MVP branch, `worker2` may also complete an `execute` task without SCM artifacts. In that case the execute result keeps the tracker-facing estimate text in `tracker_comment`, leaves branch and PR fields empty, marks `metadata.delivery_mode = estimate_only`, and still creates a downstream `deliver` task.

Before handoff to `worker3`, estimate-only execute output is normalized into a stable estimate contract under `result_payload.metadata.estimate` with at least:

- `story_points: int`
- `can_take_in_work: bool` (product rule: `story_points <= 2` is `true`, otherwise `false`)
- `rationale: str`

`worker2` prefers already structured estimate metadata when present, but must still derive the same contract from legacy free-text estimate outputs (for example `2 story points\nReason: ...`).

For new top-level tracker intake (`TrackerTask.parent_external_id` is empty), `worker1` now persists an explicit execute-mode flag in `input_payload.metadata.estimate_only = true`. `worker2` and the CLI runtime contract must prefer this explicit flag over free-text heuristics when deciding estimate-only behavior. Tracker subtasks (for example selected small estimated child tasks) are ingested without that forced flag and continue through normal SCM-backed execution unless another explicit signal is present.

When estimate-only agent output is split across multiple text fields, `worker2` normalizes the final `tracker_comment` by merging `metadata.stdout_preview`, `tracker_comment`, and `details` in that order. The merged comment must preserve an already complete message, append missing rationale when only the estimate is present in the first field, and avoid duplicating the same estimate or reason twice.

Tracker-thread follow-up for estimate-only work uses the same delivery-only pattern. `worker1` creates a `tracker_feedback` child with `input_payload.tracker_feedback`, `worker2` replies without branch/commit/push/PR side effects, and `worker3` posts the follow-up comment back into the same tracker thread. The reply result keeps `metadata.flow_type = tracker_feedback`, `metadata.pr_action = skipped`, and updates the owning execute result metadata with the last tracker feedback id.

### PR Feedback

- A PR feedback step uses `input_payload.action = respond_pr`.
- It runs as a `pr_feedback` task.
- Feedback-specific data belongs in `input_payload.pr_feedback`.
- The task reuses the same branch and PR thread while preserving follow-up history through child tasks.

### Tracker Feedback

- A tracker follow-up step uses `input_payload.action = reply_tracker` when an explicit business action is modeled.
- It runs as a `tracker_feedback` task.
- Feedback-specific data belongs in `input_payload.tracker_feedback`.
- The task reuses the same tracker thread, skips SCM side effects, and creates a downstream `deliver` task under the feedback child so the reply is posted back to the same external task.

### Delivery

- A delivery step uses `input_payload.action = deliver` when an explicit deliver task is created.
- It runs as a `deliver` task owned by `worker3`.
- The delivery worker reads tracker instructions from upstream `result_payload.delivery` rather than from `summary` or `details`.
- Delivery may attach links from `result_payload.artifacts` when present.
- If the upstream execute result is estimate-only, delivery sends a normalized tracker comment format that explicitly includes story points, take-in-work decision, and rationale; then it persists the same structured estimate back to tracker metadata (`metadata.estimate`) through the tracker boundary while preserving existing `metadata.selection`.

## Scenario Summary

- New tracker intake starts at triage.
- Triage decides whether the next step is delivery-only, research, implementation, or rejection.
- Research and implementation both return machine-readable `routing` and `delivery` sections.
- PR feedback follows the same contract with a different `action` and feedback-specific input.
- Estimate-only tracker follow-up uses the same contract with `tracker_feedback` input and tracker-thread-only delivery.
- Delivery is always driven by structured `delivery` data.

## Manual Operator Comment API

The authenticated operator API also allows a direct manual tracker comment without creating a new orchestration task.

- `POST /tasks/{task_id}/tracker-comments` accepts a minimal JSON body with `body` text.
- The path `task_id` is always a local orchestration task id, not a tracker id.
- The API resolves the tracker destination from the existing task thread using the same tracker-id precedence as delivery flows: current execute/deliver tracker parent, then execute ancestor tracker parent, then fetch/root tracker external id.
- The API calls `TrackerProtocol.add_comment` directly and stores only minimal provenance metadata such as the local task id, root task id, and `source = api_manual_comment`.
