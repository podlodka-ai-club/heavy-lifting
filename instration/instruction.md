# Instruction Workflow

## Purpose

This directory stores the project specification, task definitions, extra task context, and review results.

## Files

- `instration/project.md` - current project technical specification and scope.
- `instration/TASK_TEMPLATE.md` - template for implementation tasks.
- `instration/TASK_CONTEXT_TEMPLATE.md` - template for extra task context.
- `instration/TASK_REVIEW_TEMPLATE.md` - template for task review results.
- `instration/tasks/taskN.md` - concrete tasks created from the task template.

## Task Lifecycle

1. Read `instration/project.md` before creating or starting a task.
2. Create a task file in `instration/tasks/` from `instration/TASK_TEMPLATE.md`.
3. Fill in `Status` and `Detailed Description` before work starts.
4. If the task needs extra information, create a matching context document from `instration/TASK_CONTEXT_TEMPLATE.md`.
5. Implement the task.
6. After completion, update the task file `Result` section with a short summary of what was done.
7. Run review and store the output in a document based on `instration/TASK_REVIEW_TEMPLATE.md`.
8. Update task status to reflect the current state, for example: `todo`, `in_progress`, `done`, `blocked`, `reviewed`.

## Rules

- Each task must have a clear status.
- Each task must have a detailed description before implementation starts.
- The `Result` section must be updated after implementation.
- `Context` documents contain any supplemental information, assumptions, references, or constraints.
- `Review` documents contain findings, risks, and the review decision.
- Keep one task per file.
- Prefer atomic tasks that can be completed and reviewed independently.

## Suggested Naming

- Tasks: `instration/tasks/task1.md`, `instration/tasks/task2.md`, ...
- Context files: `instration/tasks/task1_context.md`
- Review files: `instration/tasks/task1_review.md`
