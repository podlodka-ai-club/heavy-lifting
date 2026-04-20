# Task 10

## Metadata

- ID: `task10`
- Title: Add container runtime files for API, workers, and Postgres
- Status: `todo`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task8`
- Next Tasks: `task11`

## Goal

Define the containerized runtime for the MVP stack.

## Detailed Description

Create `Dockerfile` and `docker-compose.yml` for the API service, three worker services, and PostgreSQL. Make sure the setup is consistent with `uv`, `src/backend`, and a shared workspace volume for repository synchronization.

## Deliverables

- Root `Dockerfile`
- Root `docker-compose.yml`
- Service definitions for API, workers, and Postgres
- Shared workspace volume definition

## Context References

- `instration/project.md`
- `instration/tasks/task1.md`

## Review References

- `instration/tasks/task10_review1.md`

## Progress References

- `instration/tasks/task10_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
