# Task 27

## Metadata

- ID: `task27`
- Title: Implement `Worker 2` execution and PR update flow
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task20`, `task22`, `task23`, `task24`, `task25`, `task26`
- Next Tasks: `task28`, `task31`

## Goal

Implement the worker that executes coding tasks and updates PR state.

## Detailed Description

Build the `Worker 2` flow for both `execute` and `pr_feedback` tasks. It must sync repository state, run the agent, persist results, store token usage, create or update PRs, reuse the existing branch for feedback tasks, and create child `deliver` tasks after successful `execute`.

## Deliverables

- `Worker 2` polling loop
- `execute` processing flow
- `pr_feedback` processing flow
- Token usage persistence integration
- PR create or update integration

## Context References

- `instration/project.md`
- `instration/tasks/task4.md`

## Review References

- `instration/tasks/task27_review1.md`

## Progress References

- `instration/tasks/task27_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
