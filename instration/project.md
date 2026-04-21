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
