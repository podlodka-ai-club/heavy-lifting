# Task 30

## Metadata

- ID: `task30`
- Title: Implement task inspection API endpoints
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task29`, `task22`
- Next Tasks: `task31`

## Goal

Expose task state through the Flask API.

## Detailed Description

Add `GET /tasks` and `GET /tasks/<id>` endpoints that return task information from the database, including parent and root task linkage needed to inspect orchestration chains.

## Deliverables

- `GET /tasks`
- `GET /tasks/<id>`
- API response serialization for tasks

## Context References

- `instration/project.md`
- `instration/tasks/task5.md`

## Review References

- `instration/tasks/task30_review1.md`

## Progress References

- `instration/tasks/task30_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
