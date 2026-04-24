# Worklog Workflow

## Purpose

The worklog is local short-term memory for a single implementation thread. It captures task-specific context, progress notes, review history, and completion notes that are useful during execution but should not become the main long-term knowledge base of the repository.

Durable facts, contracts, and decisions belong in `docs/`. A worklog is complete only when the relevant durable documentation has been updated.

## Location And Ownership

Each active effort lives under:

```text
worklog/<username>/<worklog-id>/
```

- `<username>` identifies the local contributor or agent owner.
- `<worklog-id>` identifies the broader feature, task, or delivery thread.
- The directory is local execution state and should stay gitignored.

## Recommended Structure

```text
worklog/<username>/<worklog-id>/
  context.md
  tasks/
    task01.md
    task01_progress.md
    task01_review1.md
    task01_summary.md
```

Additional files are allowed when they improve clarity, but the worklog should stay lightweight and focused on the current thread.

## Core Files

### `context.md`

Use `context.md` for the stable short-term frame of the worklog:

- task intent and scope;
- key inputs or links;
- assumptions and open questions;
- constraints that matter across multiple atomic tasks.

### Atomic task files

Create one task file per atomic unit of work under `tasks/`, such as `tasks/task01.md`, `tasks/task02.md`, and so on.

Each task file should state:

- the goal of the atomic change;
- expected acceptance notes or review focus;
- any important constraints for that slice of work.

### Progress files

Track execution notes in matching progress files such as `tasks/task01_progress.md`.

Progress notes should capture:

- meaningful implementation steps;
- notable decisions or assumptions made during execution;
- checks that were run or intentionally skipped.

Do not use progress files as a substitute for durable design documentation.

### Review files

Store review output in numbered files such as `tasks/task01_review1.md`, `tasks/task01_review2.md`, and so on.

These files preserve the `DEV -> REVIEW -> DEV` loop for the atomic task and make it clear which follow-up changes were driven by review.

### Summary files

Close each atomic task with a summary file such as `tasks/task01_summary.md`.

The summary should record:

- what changed;
- what checks were run;
- which `docs/` pages were updated;
- any remaining follow-up items that did not fit into the current atomic task.

## Workflow Rules

1. Create or update the active worklog before significant implementation work starts.
2. Keep one numbered worklog task per atomic, independently reviewable change.
3. Run the `DEV -> REVIEW -> DEV(commit)` loop for each atomic task.
4. Do not treat the worklog as done until the relevant `docs/` pages have been updated.
5. Keep durable knowledge in `docs/`, not only in local execution notes.

## Commit Format

Each atomic task ends with exactly one commit using this format:

```text
<worklog-id>/taskNN <short Russian action summary>
```

Examples:

```text
task56/task01 описать стартовую структуру docs
task56/task02 уточнить workflow обработки pr feedback
```

## Practical Guidance

- Keep worklog files concise and readable.
- Prefer appending short factual notes over rewriting history.
- If a task reveals a durable product or process decision, update `docs/` in the same task.
- If a review requests follow-up changes, record the review artifact in the worklog before creating the final commit.
