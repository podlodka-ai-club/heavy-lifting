# Task 41

## Metadata

- ID: `task41`
- Title: Добавить установку git hooks и pre-commit проверку
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task39`, `task40`
- Next Tasks: `task11`

## Goal

Добавить версионируемый `pre-commit` hook и установку git hooks через `make init`.

## Detailed Description

Нужно добавить в репозиторий версионируемый `pre-commit` hook, который автоматически запускает `make lint` и `make typecheck` перед коммитом кодовых задач. Также нужно добавить установку hook в `.git/hooks` через отдельный таргет и встроить ее в `make init`. Для документационных задач hook может пропускать проверки, если staged changes затрагивают только `instration/` и `AGENTS.md`.

## Deliverables

- Версионируемый `pre-commit` hook
- Таргет для установки git hooks
- Обновленный `make init`

## Context References

- `instration/PRE_COMMIT_CHECKS_SKILL.md`
- `instration/tasks/task40.md`

## Review References

- `instration/tasks/task41_review1.md`

## Progress References

- `instration/tasks/task41_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
