# AGENTS

## Project Summary

This repository contains an MVP backend orchestrator written in Python with Flask and PostgreSQL. The system coordinates tracker tasks, coding execution, PR creation, PR feedback processing, and delivery of results back to the tracker.

## Repository Structure

- Root infrastructure files live in the repository root.
- Application code lives in `src/backend`.
- Durable system documentation lives in `docs`.
- Process rules, skills, and templates live in `instration`.
- Local developer or agent execution trails live in `worklog` and should stay gitignored.

## Python And Tooling

- Use Python 3.12.
- Manage dependencies with `uv`.
- Prefer running commands through `uv run`.

## Communication

- The main orchestrating agent must communicate with the user only in Russian.

## Development Rules

- Keep the architecture modular under `src/backend`.
- Build against the MVP scope defined in `docs/vision/system.md`, supported by the current contracts in `docs/` and `instration/project.md` during migration.
- Use the worklog workflow described in `docs/process/worklog.md` and the supporting rules in `instration/instruction.md`.
- The main orchestrating agent may directly edit only files inside `instration/`, `docs/`, `worklog/`, and `AGENTS.md`.
- All source code, configuration, and other repository changes outside `instration/`, `docs/`, and `worklog/` must be performed through `DEV`.
- Create or update the active worklog in `worklog/<username>/<worklog-id>/` before significant work.
- Record implementation progress and review history inside the active worklog.
- Update the relevant `docs/` pages before considering a worklog complete.
- Use the `DEV -> REVIEW -> DEV(commit)` loop for each atomic task.
- Do not create a commit before review approval.
- After `REVIEW` approval, `DEV` must create the commit automatically without asking the user for extra confirmation.
- Each atomic task should end with exactly one git commit.
- Use commit messages in the format `<worklog-id>/taskNN <short Russian action summary>`.
- Before committing code changes, `DEV` must run `make lint` and `make typecheck`, or explicitly document why they are not applicable.
- Keep tasks atomic and independently reviewable.

## Baseline Principles For Subagents

These cross-cutting rules apply to every subagent unless a role prompt explicitly overrides them. They are enforced through role artifacts, not through conversation with the user.

- Surface assumptions and ambiguities. Never pick silently between incompatible interpretations. An autonomous role must either emit `{status:"blocked", reason}` or record the assumption explicitly in its artifact (ADR Context/Assumptions, requirements Open questions, change summary, review notes, etc.).
- Prefer the simplest solution that satisfies the ACs. No speculative flexibility, configurability, extension points, or abstractions that are not required by an AC or ADR.
- Change only what the task requires. Inside touched files, do not reformat, rename, or refactor adjacent code. Unrelated dead code is mentioned, not removed.
- Defensive branches and error handling are added only for inputs or states required by an AC, an explicit contract, or a documented invariant. Validation at system boundaries (user input, external APIs, untrusted data) is not restricted by this rule.

## Quality Expectations

- Write tests for new functionality.
- Add or update tests together with implementation changes.
- Prefer small, reviewable changes.
- Keep history of follow-up work in child `pr_feedback` tasks.
- Keep durable facts, contracts, and rationale in `docs/`, not only in worklogs.

## Subagent Roles

- `DEV` is the implementation subagent. It may modify repository files, `docs/`, and the active local worklog.
- `REVIEW` is the review subagent running on `gpt-5.4`. It must stay read-only for source files and may only write numbered review files in the active worklog.
- `Triage` is the gate-keeper agent that runs as the first execute step for every new tracker intake. It is read-only with respect to the repository and the database; it may only write to its own `result_payload` (classification, estimate, routing, delivery, and the Handover Brief in metadata). It must never modify code, configuration, or shared state, and it never closes the tracker issue. The full contract lives in `docs/contracts/triage-routing.md` and the prompt lives in `prompts/agents/triage.md`.

## Implementation Notes

- Use `TrackerProtocol` and `ScmProtocol` boundaries.
- Start with `MockTracker` and `MockScm`.
- Keep the MVP database limited to `tasks` and `token_usage`.
- Use `instration/CONFIG_SETTINGS_SKILL.md` when adding or changing application settings.
- Use `instration/PRE_COMMIT_CHECKS_SKILL.md` before creating commits for code tasks.
