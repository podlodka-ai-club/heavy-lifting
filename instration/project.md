# Project Specification

## Overview

Build an MVP orchestrator on Python and Flask with PostgreSQL, three workers, and a modular architecture inside `src/backend`.

The system should:

- accept manual task intake through the API;
- fetch tasks from a tracker;
- prepare and execute coding tasks through an agent workflow;
- sync repositories from git when code work is required;
- create or update branches and pull requests through an SCM adapter;
- collect PR comments and transform them into child tasks for follow-up work;
- deliver results back to the tracker;
- calculate token usage and cost.

## Technical Constraints

- Dependency management via `uv`.
- Root files: `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `Makefile`.
- Application code is stored in `src/backend`.
- Flask is used for the API.
- PostgreSQL is used for persistence.
- Only two database tables are used in MVP: `tasks` and `token_usage`.

## Protocols

### TrackerProtocol

Must support:

- fetching tasks;
- creating tasks;
- creating subtasks;
- adding comments;
- updating task status;
- attaching links.

### ScmProtocol

Must support:

- ensuring local workspace from git;
- creating branches;
- committing changes;
- pushing branches;
- creating pull requests;
- reading PR feedback.

## MVP Adapters

- `MockTracker`
- `MockScm`

## Workers

### Worker 1

- fetches tasks from the tracker;
- creates `fetch` tasks and child `execute` tasks;
- polls PR comments from SCM;
- maps PR feedback to the correct `execute` task;
- creates child `pr_feedback` tasks.

### Worker 2

- processes `execute` and `pr_feedback` tasks;
- syncs repository state from git;
- runs the coding agent;
- stores execution results;
- stores token usage and cost;
- creates or updates PRs when code changes exist;
- creates child `deliver` tasks after successful `execute`.

### Worker 3

- processes `deliver` tasks;
- sends result back to the tracker;
- updates tracker task status;
- posts comments and PR links to the tracker.

## Task Types

- `fetch`
- `execute`
- `deliver`
- `pr_feedback`

Task types describe pipeline stages, not the business meaning of the task. Business routing must be expressed through `role`, `input_payload`, and `result_payload`.

## Business Task Kinds

The MVP must support at least these business task kinds:

- `research`
- `implementation`
- `clarification`
- `review_response`
- `rejected`

The business kind is identified during triage and stored in `result_payload.classification.task_kind`.

## Triage And Routing Rules

- Every new tracker task must first go through a triage step before implementation work starts.
- `worker1` ingests a new tracker task and creates the first executable step for triage.
- Triage determines whether the task can be taken into work, estimates complexity and story points, and chooses the next scenario.
- Triage may finish with a tracker reply only, or route the task into a follow-up execution step such as research or implementation.
- PR feedback remains a separate flow source, but uses the same payload handoff principles.

## Task Statuses

- `new`
- `processing`
- `done`
- `failed`

## Task Model

The `tasks` table must contain at least:

- `id`
- `root_id`
- `parent_id`
- `task_type`
- `status`
- `tracker_name`
- `external_task_id`
- `external_parent_id`
- `repo_url`
- `repo_ref`
- `workspace_key`
- `branch_name`
- `pr_external_id`
- `pr_url`
- `role`
- `context`
- `input_payload`
- `result_payload`
- `error`
- `attempt`
- `created_at`
- `updated_at`

## Token Usage Model

The `token_usage` table must contain at least:

- `id`
- `task_id`
- `model`
- `provider`
- `input_tokens`
- `output_tokens`
- `cached_tokens`
- `estimated`
- `cost_usd`
- `created_at`

## Context Rules

- `fetch.context` stores the base task context from the tracker.
- `execute.context` stores the main execution context for coding work.
- `pr_feedback` stores feedback-specific input, but inherits context through the task chain.
- History of follow-up iterations is stored in child `pr_feedback` tasks, not overwritten in `execute`.

Additional context rules:

- `context` stores stable task facts and source information, not step-specific commands.
- `context` should contain the original title, description, acceptance criteria, references, and source metadata from the tracker.
- Repository coordinates such as `repo_url`, `repo_ref`, and `workspace_key` stay in the task record and may be copied into context metadata only when needed for prompt assembly.
- Large step history must not be copied into every payload; lineage is reconstructed from the task chain.

## Payload Contract Principles

- `input_payload` is the command for the current pipeline step.
- `result_payload` is the structured result of the current step and the handoff to the next step.
- Human-readable text in `summary` and `details` is useful for logs and comments, but routing decisions must rely on machine-readable fields.
- `worker3` must read tracker delivery instructions from `result_payload.delivery` rather than parse `summary` or `details`.
- All new payload shapes must include `schema_version` for forward-compatible evolution.

## Input Payload V1

`input_payload` version 1 must support these top-level fields:

- `schema_version` - payload contract version, initial value `1`
- `action` - current step action such as `triage`, `research`, `implementation`, `respond_pr`, or `deliver`
- `role` - current step role; may match `action` or refine it, for example `estimate_reply`
- `instructions` - short step-specific instruction for the worker or agent
- `constraints` - execution constraints for the current step
- `handoff` - structured information passed from the previous step
- `expected_output` - list or object describing which sections the result must contain
- `base_branch` - optional branch base for implementation flows
- `branch_name` - optional branch name for implementation or PR response flows
- `commit_message_hint` - optional commit message hint for code flows
- `pr_feedback` - structured PR feedback input for review response steps
- `metadata` - non-critical extensions that do not change core routing semantics

`input_payload` must not duplicate the original task problem statement when that data is already present in `context`.

## Input Payload Constraints V1

`constraints` should support at least these flags when relevant:

- `may_touch_repo`
- `may_create_pr`
- `must_run_checks`
- `timebox_minutes`
- `requires_human_approval`

`handoff` should support at least these fields when relevant:

- `from_task_id`
- `from_role`
- `reason`
- `decision_ref`

`expected_output` should identify required result sections, for example:

- `classification`
- `estimate`
- `routing`
- `delivery`
- `artifacts`

## Result Payload V1

`result_payload` version 1 remains the stored output payload and must support these top-level fields:

- `schema_version` - payload contract version, initial value `1`
- `outcome` - current step result such as `completed`, `routed`, `needs_clarification`, `blocked`, `failed`
- `summary` - short human-readable result summary
- `details` - optional longer explanation
- `classification` - machine-readable business task classification
- `estimate` - story points, complexity, and take-in-work decision
- `routing` - next-step instructions for the orchestrator
- `delivery` - tracker-ready status and comment instructions for `worker3`
- `artifacts` - branch, commit, PR, or other generated execution artifacts
- `token_usage` - model usage records when an agent call occurs
- `metadata` - secondary diagnostics and implementation-specific extensions

## Result Payload Section Rules V1

`classification` should support at least:

- `task_kind`
- `confidence`
- `signals`

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

## Payload Scenarios V1

- A new tracker task starts with `input_payload.action = triage`.
- A research step uses `input_payload.action = research` and must produce routing plus delivery data.
- An implementation step uses `input_payload.action = implementation` and must populate execution artifacts when code changes exist.
- A PR feedback step uses `input_payload.action = respond_pr` and requires `input_payload.pr_feedback`.
- A delivery step reads `result_payload.delivery` from the relevant upstream execution result instead of inferring tracker actions from free text.

## API Endpoints

- `GET /health`
- `GET /tasks`
- `GET /tasks/<id>`
- `GET /stats`
- `POST /tasks/intake`

## Success Criteria

- a manually submitted task can pass through `POST /tasks/intake -> worker1 -> worker2 -> worker3`;
- a tracker task passes through `fetch -> execute -> deliver`;
- code tasks can produce a PR;
- PR comments become child `pr_feedback` tasks;
- `pr_feedback` tasks reuse the same branch and PR;
- token usage and cost are visible through the API;
- the architecture is ready for replacing mock adapters with real ones later.
