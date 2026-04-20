# Task 13

## Metadata

- ID: `task13`
- Title: Define SQLAlchemy model for `tasks`
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task12`
- Next Tasks: `task14`, `task15`

## Goal

Implement the primary persistence model for orchestration tasks.

## Detailed Description

Create the `tasks` SQLAlchemy model with all MVP fields required for task relationships, context sharing, payload storage, PR linkage, status tracking, and timestamps. Add indexes that support worker polling and lookup by parent or PR identifier.

## Deliverables

- `tasks` ORM model
- Required enums or constants for persisted values
- Core indexes for task queries

## Context References

- `instration/project.md`
- `instration/tasks/task2.md`

## Review References

- `instration/tasks/task13_review1.md`

## Progress References

- `instration/tasks/task13_progress.md`

## Result

Completed. The `tasks` ORM model, supporting enums, indexes, and tests are implemented and verified.
