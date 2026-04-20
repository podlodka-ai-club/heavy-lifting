# Task 24

## Metadata

- ID: `task24`
- Title: Implement agent runner abstraction
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task23`
- Next Tasks: `task27`

## Goal

Create the execution boundary for running the coding agent.

## Detailed Description

Add a small agent runner abstraction that `Worker 2` can call for `execute` and `pr_feedback` tasks. For MVP it may be a mock or placeholder runner, but it must return a normalized execution result including token usage and summary metadata.

## Deliverables

- Agent runner interface or service
- Normalized execution result contract
- MVP implementation suitable for local flows

## Context References

- `instration/project.md`
- `instration/tasks/task4.md`

## Review References

- `instration/tasks/task24_review1.md`

## Progress References

- `instration/tasks/task24_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
