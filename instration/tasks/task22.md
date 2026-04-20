# Task 22

## Metadata

- ID: `task22`
- Title: Implement task repository and query helpers
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task15`, `task16`
- Next Tasks: `task23`, `task25`, `task26`, `task27`, `task28`, `task29`, `task30`, `task31`

## Goal

Create persistence helpers for worker-safe task access.

## Detailed Description

Implement repository helpers for creating tasks, loading chains by `root_id`, polling tasks by `task_type` and `status`, finding `execute` by `pr_external_id`, and recording token usage. Keep the API small and tailored to the MVP worker flows.

## Deliverables

- Task repository helpers
- Token usage persistence helper
- Query helpers for worker flows

## Context References

- `instration/project.md`
- `instration/tasks/task4.md`

## Review References

- `instration/tasks/task22_review1.md`

## Progress References

- `instration/tasks/task22_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
