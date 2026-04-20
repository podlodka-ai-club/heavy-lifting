# Task 21

## Metadata

- ID: `task21`
- Title: Wire adapter factories and service initialization
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task19`, `task20`
- Next Tasks: `task25`, `task26`, `task28`, `task29`

## Goal

Create a simple initialization layer for selecting the active adapters.

## Detailed Description

Add a lightweight composition layer that instantiates the configured tracker and SCM adapters for API and worker processes. For MVP this should default to `MockTracker` and `MockScm`, but the structure should make future real adapters easy to plug in.

## Deliverables

- Adapter factory or composition module
- Default wiring for mock implementations
- Shared initialization path for workers and API

## Context References

- `instration/project.md`
- `instration/tasks/task3.md`

## Review References

- `instration/tasks/task21_review1.md`

## Progress References

- `instration/tasks/task21_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
