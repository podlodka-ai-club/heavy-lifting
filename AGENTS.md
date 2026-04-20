# AGENTS

## Project Summary

This repository contains an MVP backend orchestrator written in Python with Flask and PostgreSQL. The system coordinates tracker tasks, coding execution, PR creation, PR feedback processing, and delivery of results back to the tracker.

## Repository Structure

- Root infrastructure files live in the repository root.
- Application code lives in `src/backend`.
- Task and process documentation lives in `instration`.

## Python And Tooling

- Use Python 3.12.
- Manage dependencies with `uv`.
- Prefer running commands through `uv run`.

## Development Rules

- Keep the architecture modular under `src/backend`.
- Build against the MVP scope defined in `instration/project.md`.
- Use the task workflow described in `instration/instruction.md`.
- Create or update task files in `instration/tasks` before and after significant work.
- Keep tasks atomic and independently reviewable.

## Quality Expectations

- Write tests for new functionality.
- Add or update tests together with implementation changes.
- Prefer small, reviewable changes.
- Keep history of follow-up work in child `pr_feedback` tasks.

## Implementation Notes

- Use `TrackerProtocol` and `ScmProtocol` boundaries.
- Start with `MockTracker` and `MockScm`.
- Keep the MVP database limited to `tasks` and `token_usage`.
