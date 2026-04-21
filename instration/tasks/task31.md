# Task 31

## Metadata

- ID: `task31`
- Title: Implement stats endpoint and logging setup
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task29`, `task22`, `task27`, `task28`
- Next Tasks: `task32`, `task33`

## Goal

Expose MVP metrics and structured logs for local orchestration runs.

## Detailed Description

Add `GET /stats` with basic aggregates for tasks, token usage, and cost, using the current MVP database state. Configure shared logging for the Flask app and worker entrypoints so local orchestration runs can be debugged and reviewed consistently, and cover the new API surface with tests.

## Deliverables

- `GET /stats`
- Logging configuration
- Shared logger initialization for processes

## Context References

- `instration/project.md`
- `instration/tasks/task5.md`

## Review References

- `instration/tasks/task31_review1.md`

## Progress References

- `instration/tasks/task31_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
