# Task 23

## Metadata

- ID: `task23`
- Title: Implement effective context builder and token cost service
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task16`, `task22`
- Next Tasks: `task24`, `task25`, `task26`, `task27`, `task28`

## Goal

Build the core support services for task execution.

## Detailed Description

Implement the service that reconstructs the effective context from the task chain and a service that converts token usage into estimated cost. The context builder must support `execute`, `deliver`, and `pr_feedback` flows.

## Deliverables

- Effective context builder
- Token cost calculation service
- Shared helpers used by workers

## Context References

- `instration/project.md`
- `instration/tasks/task4.md`

## Review References

- `instration/tasks/task23_review1.md`
- `instration/tasks/task23_review2.md`

## Progress References

- `instration/tasks/task23_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
