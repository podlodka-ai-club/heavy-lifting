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

For the current mock-only estimate-selection flow, the tracker task metadata may also carry:

- `metadata.estimate.story_points`
- `metadata.estimate.can_take_in_work`
- `metadata.selection.taken_in_work`

Those fields are tracker-side selection hints only. They do not replace the worker handoff contract and are used only to decide whether the orchestrator should create a new executable tracker subtask.

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
- Follow-up iteration history lives in child tasks, not as an ever-growing transcript inside `context`.

## Input Payload V1

`input_payload` is the current-step command. It tells the worker or agent what to do now, under which constraints, and what kind of structured output is required.

### Top-Level Fields

- `schema_version` - contract version, initial value `1`
- `action` - current step action such as `triage`, `research`, `implementation`, `respond_pr`, or `deliver`
- `role` - current step role; may refine `action`, for example `estimate_reply`
- `instructions` - short step-specific instruction
- `constraints` - execution constraints for the step
- `handoff` - structured information from the previous step
- `expected_output` - required result sections
- `base_branch` - optional base branch for code flows
- `branch_name` - optional branch name for implementation or PR response flows
- `commit_message_hint` - optional commit message hint for code flows
- `pr_feedback` - structured PR feedback input for review-response steps
- `metadata` - non-critical extensions that do not change routing semantics

`input_payload` must not duplicate the original problem statement when it already exists in `context`.

### Constraints Fields

`constraints` should support at least:

- `may_touch_repo`
- `may_create_pr`
- `must_run_checks`
- `timebox_minutes`
- `requires_human_approval`

### Handoff Fields

`handoff` should support at least:

- `from_task_id`
- `from_role`
- `reason`
- `decision_ref`

### Expected Output Fields

`expected_output` should identify which result sections are required, for example:

- `classification`
- `estimate`
- `routing`
- `delivery`
- `artifacts`

## Result Payload V1

`result_payload` is the structured outcome of the current step and the input to downstream orchestration decisions.

### Top-Level Fields

- `schema_version` - contract version, initial value `1`
- `outcome` - current step result such as `completed`, `routed`, `needs_clarification`, `blocked`, `failed`
- `summary` - short human-readable result summary
- `details` - optional longer explanation
- `classification` - machine-readable business task classification
- `estimate` - story points, complexity, and take-in-work decision
- `routing` - next-step instructions for the orchestrator
- `delivery` - tracker-ready status and comment instructions for delivery
- `artifacts` - branch, commit, PR, or other generated execution artifacts
- `token_usage` - model usage records when an agent call occurs
- `metadata` - secondary diagnostics and implementation-specific extensions

### Section Rules

`classification` should support at least:

- `task_kind`
- `confidence`
- `signals`

The MVP business kinds are:

- `research`
- `implementation`
- `clarification`
- `review_response`
- `rejected`

`estimate` should support at least:

- `story_points`
- `complexity`
- `can_take_in_work`
- `blocking_reasons`

`routing` should support at least:

- `next_task_type`
- `next_role`
- `create_followup_task`
- `requires_human_approval`

`delivery` should support at least:

- `tracker_status`
- `comment_body`
- `links`

`artifacts` should support at least:

- `branch_name`
- `commit_sha`
- `pr_url`

## Worker Handoff Rules

## Action To Pipeline Mapping

Business-step `action` values describe what the current step is trying to do. Pipeline `task_type` values describe where that step runs in the worker pipeline.

The MVP mapping is:

- `triage` runs inside an `execute` task owned by `worker2`
- `research` runs inside an `execute` task owned by `worker2`
- `implementation` runs inside an `execute` task owned by `worker2`
- `respond_pr` runs inside a `pr_feedback` task owned by `worker2`
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

- A new tracker task enters the system with `input_payload.action = triage`.
- Triage classifies the business task, estimates whether it can be taken into work, and decides the next executable path.
- Triage runs as an `execute` task and may either finish with delivery-only output or route to a follow-up `execute` task for research or implementation.

For the mock-only backlog-selection branch, the system may first choose one already estimated parent task and create a tracker subtask that carries the original context, repository coordinates, and executable `input_payload`. That subtask then enters the same `fetch -> execute -> deliver` pipeline as any other tracker intake.

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

### PR Feedback

- A PR feedback step uses `input_payload.action = respond_pr`.
- It runs as a `pr_feedback` task.
- Feedback-specific data belongs in `input_payload.pr_feedback`.
- The task reuses the same branch and PR thread while preserving follow-up history through child tasks.

### Delivery

- A delivery step uses `input_payload.action = deliver` when an explicit deliver task is created.
- It runs as a `deliver` task owned by `worker3`.
- The delivery worker reads tracker instructions from upstream `result_payload.delivery` rather than from `summary` or `details`.
- Delivery may attach links from `result_payload.artifacts` when present.
- If the upstream execute result is estimate-only, delivery sends the estimate text from `tracker_comment` and attaches no SCM links.

## Scenario Summary

- New tracker intake starts at triage.
- Triage decides whether the next step is delivery-only, research, implementation, or rejection.
- Research and implementation both return machine-readable `routing` and `delivery` sections.
- PR feedback follows the same contract with a different `action` and feedback-specific input.
- Delivery is always driven by structured `delivery` data.
