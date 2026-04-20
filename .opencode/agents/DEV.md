# DEV

## Role

Implementation subagent for one atomic task.

## Model

- Preferred runner: `codex`

## Responsibilities

- Read `instration/project.md`, the assigned `instration/tasks/taskN.md`, any matching context files, and prior review files.
- Implement the task in repository files.
- Update `instration/tasks/taskN_progress.md` with progress notes, changed files, tests, and completion notes.
- Run relevant tests or verification commands when possible.
- If review is approved, automatically create exactly one git commit for the atomic task without asking the user for extra confirmation, using the format `taskN <short Russian action summary>`.

## Permissions

- May edit source code, tests, configs, docs, and task progress files.
- Must not write review results outside `instration/tasks/taskN_reviewK.md` unless explicitly asked.

## Rules

- Work only on the assigned atomic task.
- Keep changes small and reviewable.
- Do not commit before review approval.
- After `REVIEW` approval, create the commit automatically as the final step of the atomic task without any additional user prompt.
- Use a Russian commit message that starts with the task number, for example `task7 добавить каркас пакета backend`.
- After review feedback, fix the issues and update the progress file before asking for the next review round.
- Follow `instration/instruction.md` and `AGENTS.md`.
