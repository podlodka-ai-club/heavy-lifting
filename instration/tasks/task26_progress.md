# Task Progress

## Metadata

- Task ID: `task26`
- Status: `done`
- Updated At: 2026-04-21

## Progress Log

- 2026-04-21: Task started. Reviewing current Worker 1 intake flow, SCM feedback contracts, and repository helpers to add PR feedback polling, execute-task mapping, and child `pr_feedback` creation with deduplication.
- 2026-04-21: Extended `backend.workers.tracker_intake.TrackerIntakeWorker` so Worker 1 now polls both tracker tasks and SCM PR feedback. Added `poll_tracker_once()` / `poll_pr_feedback_once()` split for narrower tests and local runs, while `poll_once()` returns a combined intake report.
- 2026-04-21: Chose MVP PR feedback polling strategy per known local `execute` task with `pr_external_id`. For each execute task with an attached PR, Worker 1 asks SCM only for newer feedback items using the last ingested child feedback `comment_id` as `since_cursor`, then remaps every returned item back to the authoritative `execute` task via repository lookup by `pr_external_id`.
- 2026-04-21: Chose MVP deduplication by storing SCM `comment_id` in child `pr_feedback.external_task_id` and skipping creation when the same `(parent execute task, comment_id)` already exists. New child tasks inherit local repo/branch/PR linkage from the mapped execute task and store normalized `input_payload.pr_feedback` for Worker 2 context reconstruction.
- 2026-04-21: Added repository helpers for execute-task PR scans, child lookup by external id, and latest-child lookup; added regression tests for PR feedback intake, deduplication, build wiring, and the new repository queries.
- 2026-04-21: Verification passed with `uv run pytest tests/test_tracker_intake.py tests/test_task_repository.py tests/test_composition.py`, `make lint`, and `make typecheck`.
- 2026-04-21: Review found that deriving `since_cursor` from the latest local `pr_feedback` child by local `Task.id` is unsafe when SCM returns non-ascending pages. Reworked Worker 1 polling to use SCM-provided pagination state plus a persisted execute-task feedback cursor in `context.metadata`, so cursor advancement now depends on the SCM scan result instead of local insertion order.
- 2026-04-21: Added a regression test covering multi-page PR feedback polling with non-ascending page item order and verified that all comments are ingested before the stored SCM cursor advances.
- 2026-04-21: Review 2 found schema-level contract coverage lagging behind the updated SCM feedback query shape. Synced `tests/test_schemas.py` with the new `ScmReadPrFeedbackQuery.page_cursor` default so contract tests now match the runtime schema.
- 2026-04-21: `REVIEW` approved task26 in `instration/tasks/task26_review3.md` with no blocking findings.
- 2026-04-21: Ran final required checks `make lint`, `make typecheck`, and `uv run pytest tests/test_tracker_intake.py tests/test_scm_protocol.py tests/test_schemas.py tests/test_task_repository.py`; prepared the completion commit `task26 завершить intake PR feedback`.

## Completion Summary

- Changed files:
  - `instration/tasks/task26.md`
  - `src/backend/repositories/task_repository.py`
  - `src/backend/protocols/scm.py`
  - `src/backend/adapters/mock_scm.py`
  - `src/backend/schemas.py`
  - `src/backend/workers/tracker_intake.py`
  - `tests/test_task_repository.py`
  - `tests/test_schemas.py`
  - `tests/test_scm_protocol.py`
  - `tests/test_tracker_intake.py`
  - `instration/tasks/task26_progress.md`
  - `instration/tasks/task26_summary.md`
- Result: Worker 1 PR feedback intake flow is implemented, review-approved, verified with final checks, and ready to be committed as the atomic task26 completion.
