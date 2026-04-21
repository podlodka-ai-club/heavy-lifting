# Task 28

## Metadata

- ID: `task28`
- Title: Implement `Worker 3` delivery flow back to tracker
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task21`, `task22`, `task23`, `task27`
- Next Tasks: `task31`

## Goal

Implement the final delivery worker for tracker synchronization and close the MVP end-to-end task lifecycle.

## Detailed Description

Build the `Worker 3` polling loop that processes `deliver` tasks, loads the parent execution result, sends the final outcome back to the tracker, updates the tracker task status, and attaches the PR link when available. Cover both plain execution delivery and execution results that include PR metadata, and persist worker outcomes in repository task state with tests.

## Deliverables

- `Worker 3` polling loop
- Tracker delivery flow
- Status update and PR link attachment flow

## Context References

- `instration/project.md`
- `instration/tasks/task4.md`

## Review References

- `instration/tasks/task28_review1.md`

## Progress References

- `instration/tasks/task28_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
