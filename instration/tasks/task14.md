# Task 14

## Metadata

- ID: `task14`
- Title: Define SQLAlchemy model for `token_usage`
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task12`
- Next Tasks: `task15`

## Goal

Implement the persistence model for token accounting.

## Detailed Description

Create the `token_usage` SQLAlchemy model linked to `tasks`. Include fields required for provider, model, token counts, estimated flag, cost, and timestamps so the API can aggregate spending and usage by task chain later.

## Deliverables

- `token_usage` ORM model
- Relationship to `tasks`
- Indexes or constraints needed for MVP analytics

## Context References

- `instration/project.md`
- `instration/tasks/task2.md`

## Review References

- `instration/tasks/task14_review1.md`

## Progress References

- `instration/tasks/task14_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
