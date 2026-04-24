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

For durable event-ingestion taxonomy, normalization, and monitor-boundary rules, see `docs/contracts/event-ingestion.md`.

### Worker 2

- processes `execute` and `pr_feedback` tasks;
- runs triage, research, implementation, and PR response business actions through the step contract;
- syncs repository state from git;
- runs the coding agent;
- stores execution results;
- stores token usage and cost;
- creates or updates PRs when code changes exist;
- creates child `deliver` tasks whenever an upstream result contains tracker-ready `delivery` instructions.

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

- The durable triage signal set, supported outcomes, and routing matrix live in `docs/contracts/triage-routing.md`.
- Every new tracker task must first go through a triage step before implementation work starts.
- `worker1` ingests a new tracker task and creates the first executable step for triage.
- The triage business step runs inside an `execute` task handled by `worker2`.
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

## Context And Payload Contract

The durable v1 handoff contract for `context`, `input_payload`, and `result_payload` now lives in `docs/contracts/task-handoff.md`.

`instration/project.md` keeps only the migration-era summary:

- `context` stores stable task facts and source information.
- `input_payload` is the command for the current pipeline step.
- `result_payload` is the structured result of the current step and the handoff to the next step.
- Business-step actions map to pipeline task types as documented in `docs/contracts/task-handoff.md`.
- Routing and delivery decisions must rely on machine-readable fields.
- All new payload shapes must include `schema_version`.

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
