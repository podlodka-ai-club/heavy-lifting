# OpenCode Subagents

This directory defines the two subagent roles used in the project workflow.

- `DEV.md` - implementation subagent based on `codex`
- `REVIEW.md` - review subagent based on `gpt-5.4`

Workflow per atomic task:

1. `DEV` implements the task and updates `taskN_progress.md`.
2. `REVIEW` writes `taskN_reviewK.md`.
3. If review requests changes, `DEV` fixes them and review runs again.
4. If review approves, `DEV` creates exactly one commit for the task.
