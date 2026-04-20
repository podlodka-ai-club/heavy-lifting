# Task 20

## Metadata

- ID: `task20`
- Title: Implement `MockScm`
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task18`
- Next Tasks: `task21`, `task27`

## Goal

Provide a working mock implementation of SCM and PR operations.

## Detailed Description

Implement `MockScm` with support for workspace initialization, branch creation, commit and push stubs, PR creation, and PR feedback retrieval. The implementation should preserve enough metadata to let `Worker 1` map PR comments back to `execute` tasks.

## Deliverables

- `MockScm` adapter
- Mock PR creation flow
- Mock PR feedback retrieval flow

## Context References

- `instration/project.md`
- `instration/tasks/task3.md`

## Review References

- `instration/tasks/task20_review1.md`

## Progress References

- `instration/tasks/task20_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
