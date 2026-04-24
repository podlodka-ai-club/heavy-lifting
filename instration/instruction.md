# Instruction Workflow

## Purpose

This directory stores process rules, project templates, migration-era specifications, and reusable skills. Durable system documentation now lives in `docs/`, while local execution trails live in gitignored `worklog/` directories.

## Files

- `instration/project.md` - migration-era project specification and implementation contracts still in use.
- `instration/TASK_TEMPLATE.md` - template for atomic task files inside a local worklog.
- `instration/TASK_PROGRESS_TEMPLATE.md` - template for atomic task progress inside a local worklog.
- `instration/TASK_SUMMARY_TEMPLATE.md` - template for atomic task summaries inside a local worklog.
- `instration/TASK_CONTEXT_TEMPLATE.md` - optional supplemental context template for a worklog task.
- `instration/TASK_REVIEW_TEMPLATE.md` - template for task review results inside a local worklog.
- `instration/WORKLOG_CONTEXT_TEMPLATE.md` - template for top-level feature or initiative context in a worklog.
- `instration/WORKLOG_STATUS_TEMPLATE.md` - template for the quick recovery status file in a worklog.
- `instration/CONFIG_SETTINGS_SKILL.md` - skill for adding and using application settings.
- `instration/PRE_COMMIT_CHECKS_SKILL.md` - skill for mandatory pre-commit checks.
- `instration/RUNTIME_SCENARIO_RUNNER_SUBAGENT.md` - reusable contract for a subagent that runs real end-to-end pipeline scenarios and reports the results.
- `instration/tasks/` - legacy shared task history kept for migration and audit; do not use it as the primary workflow for new feature work.

## Worklog Lifecycle

1. Read `docs/vision/system.md`, the relevant `docs/` pages, and `instration/project.md` when migration details are still needed.
2. Create a local worklog directory `worklog/<username>/<worklog-id>/` before significant work.
3. Create `context.md` in that worklog from `instration/WORKLOG_CONTEXT_TEMPLATE.md` and describe the feature, scope, constraints, and target docs updates.
4. Create `status.md` from `instration/WORKLOG_STATUS_TEMPLATE.md` and keep it updated with the active task and immediate next action.
5. Break the work into atomic task files under `worklog/<username>/<worklog-id>/tasks/` using `instration/TASK_TEMPLATE.md` and `instration/TASK_PROGRESS_TEMPLATE.md`.
6. If an atomic task needs more detail, create a supplemental task context document from `instration/TASK_CONTEXT_TEMPLATE.md`.
7. Assign the atomic task to `DEV`, implement it, and record progress only in the matching file under `worklog/<username>/<worklog-id>/tasks/`.
8. After implementation, run `REVIEW` and store the output in `taskNN_review1.md` or the next numbered review file inside `worklog/<username>/<worklog-id>/tasks/`.
9. If review requests changes, send the task back to `DEV`, apply fixes, update the progress file, and run the next review round.
10. If review is approved, `DEV` must create the git commit for this atomic task automatically using the required message format.
11. Use one atomic task per commit.
12. Create `taskNN_summary.md` inside `worklog/<username>/<worklog-id>/tasks/` with a short summary of what was done, what docs changed, and what comes next.
13. Before closing the worklog, update the relevant `docs/` pages so durable knowledge is not trapped in the local worklog.

## Rules

- Each worklog and each atomic task must have a clear status.
- Each active worklog should have a `status.md` that identifies the current atomic task and immediate next action. Use `Active Task: none` only for an explicit handoff state between atomic tasks.
- Each atomic task must have a detailed description before implementation starts.
- Progress notes, changed files, and test results belong in `taskNN_progress.md`, not in `taskNN.md`.
- Review notes belong in numbered files such as `taskNN_review1.md`, `taskNN_review2.md`, and so on.
- `DEV` may change project files, `docs/`, and the active local worklog.
- `REVIEW` may not change project source files and may only write review results to `taskNN_reviewK.md` in the active worklog.
- Durable facts about how the system works or why it changed must be moved to `docs/` before closing the worklog.
- Do not create a commit before review approval.
- After review approval, do not ask the user whether to commit; `DEV` must create the commit as the final step of the atomic task.
- Each atomic task must end with exactly one commit.
- Commit messages must start with `<worklog-id>/taskNN` and then a short Russian action summary, for example: `triage-routing/task01 описать контракт payload`.
- Before committing code changes, follow `instration/PRE_COMMIT_CHECKS_SKILL.md`.
- `Context` documents contain any supplemental information, assumptions, references, or constraints.
- `Review` documents contain findings, risks, and the review decision.
- Keep one atomic task per file.
- Prefer atomic tasks that can be completed and reviewed independently.
- When adding or changing config parameters, follow `instration/CONFIG_SETTINGS_SKILL.md`.
- `worklog/` is local short-term memory and should stay gitignored.

## Legacy Task Migration

- Unfinished items in `instration/tasks/` must be resumed through an active local worklog, not continued in place.
- When migrating such an item, create the corresponding local worklog task, carry forward any still-relevant progress, and update the legacy file status to indicate that it now serves as migration history only.
- Legacy task files may point to the active local worklog path for operator convenience on the same machine.

## Suggested Naming

- Worklog root: `worklog/<username>/<worklog-id>/`
- Worklog context: `worklog/<username>/<worklog-id>/context.md`
- Worklog status: `worklog/<username>/<worklog-id>/status.md`
- Atomic tasks: `worklog/<username>/<worklog-id>/tasks/task01.md`, `task02.md`, ...
- Progress files: `worklog/<username>/<worklog-id>/tasks/task01_progress.md`
- Summary files: `worklog/<username>/<worklog-id>/tasks/task01_summary.md`
- Context files: `worklog/<username>/<worklog-id>/tasks/task01_context.md`
- Review files: `worklog/<username>/<worklog-id>/tasks/task01_review1.md`, `task01_review2.md`, ...

## Sequencing

- High-level tasks may point to the next planning stage.
- Atomic tasks must include `Next Tasks` in metadata so the implementation order is explicit.
- If a task unlocks more than one follow-up task, list all relevant next tasks.

## Commit Format

- Format: `<worklog-id>/taskNN <short Russian action summary>`
- Start with the exact worklog and atomic task identifier, for example `triage-routing/task01`.
- Then use a short Russian verb phrase such as `добавить`, `изменить`, `удалить`, `доработать`, `исправить`, `настроить`, `описать`.
- Keep the message concise and directly tied to the completed atomic task.
- Examples:
  - `triage-routing/task01 описать контракт payload`
  - `demo-flow/task02 доработать запуск через make demo`
  - `pr-feedback/task03 исправить обработку комментариев`

## Subagents

### DEV

- Implements the atomic task.
- May edit source files, tests, configs, durable docs, and the active local worklog.
- Must update the active worklog progress file during and after execution.
- Creates the commit only after review approval.

### REVIEW

- Reviews the result of `DEV` using the task definition, progress file, review history, and code diff.
- Must not edit project source files.
- May only create or update numbered review files inside the active local worklog.
- Returns either approval or requested changes.
