# Task 26 Review 1

- Verdict: `changes_requested`

## Findings

1. `src/backend/workers/tracker_intake.py:109`
   Cursor advancement for SCM polling is derived from `find_latest_child_task()` ordered by local task `id`, not by the SCM cursor itself. That is only correct if every adapter always returns feedback in ascending cursor order. The `ScmReadPrFeedbackQuery` contract does not guarantee that ordering, so a real adapter that returns newest-first (or any non-ascending page) can permanently skip older comments once `since_cursor` jumps past them. Example: with limit 2, first page `[comment-5, comment-4]` creates two child tasks, the stored cursor becomes `comment-4`, and comments `comment-1..3` are never fetched because subsequent polls ask only for items newer than `comment-4`. For task26 the polling flow needs a cursor strategy that is correct independently of result ordering, plus a regression test for that case.

## Checks

- Reviewed `src/backend/workers/tracker_intake.py`, `src/backend/repositories/task_repository.py`, `tests/test_tracker_intake.py`, and `tests/test_task_repository.py` against `instration/tasks/task26.md`, `instration/project.md`, and `instration/tasks/task4.md`.
- Verified `execute` lookup by `pr_external_id`, child `pr_feedback` creation, inherited `root_id` resolution via `TaskRepository.create_task()`, and the current deduplication rule based on `(parent execute task, comment_id)`.
- Checked compatibility with follow-up worker flows: `pr_feedback` tasks keep branch/PR linkage and normalized `input_payload.pr_feedback`, which matches `src/backend/services/context_builder.py` expectations.

## Notes

- The current tests cover the happy path, parent/root linkage, repository helpers, and duplicate comment-id ingestion for a single parent task.
- Explicit gap: there is no test for multi-poll cursor progression with pagination or non-ascending SCM ordering, which is exactly where the current implementation becomes unsafe for future real SCM adapters.
