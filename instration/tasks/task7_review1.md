# Task Review

## Metadata

- Task ID: `task7`
- Review Round: `1`
- Reviewer: `REVIEW`
- Review Date: `2026-04-20`
- Status: `changes_requested`

## Scope Reviewed

Reviewed `instration/tasks/task7.md`, `instration/tasks/task7_progress.md`, `instration/TASK_REVIEW_TEMPLATE.md`, and the newly added package skeleton under `src/backend`.

## Findings

- The base package structure under `src/backend` is present and includes package markers plus placeholder modules for config, API, protocols, services, workers, db, models, and schemas.
- `src/backend/adapters` currently contains only `__init__.py`, so the task does not yet provide a minimal module layout for adapter implementations even though adapters are explicitly part of the requested skeleton.

## Risks

- Leaving adapters without placeholder modules weakens the intended boundary-driven layout and makes the initial package skeleton incomplete for the next tasks that are expected to implement `MockTracker` and `MockScm`.

## Required Changes

- Add minimal placeholder adapter modules under `src/backend/adapters` for the future SCM and tracker implementations so the adapter layer is represented in the initial skeleton.

## Final Decision

- `changes_requested`

## Notes

The current structure is close to complete, but the adapter layer needs at least placeholder modules to match the task goal and project guidance.

## Follow-Up

- After fixes are applied, create the next review file as `task7_review2.md`.
