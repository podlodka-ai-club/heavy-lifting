# Task 39

## Metadata

- ID: `task39`
- Title: Описать skill предкоммитных проверок и правило запуска линтеров
- Status: `done`
- Priority: `medium`
- Owner: `agent-orchestrator`
- Depends on: `task9`
- Next Tasks: `task11`

## Goal

Зафиксировать единый skill и правила, по которым перед коммитом запускаются линтеры и проверка типов.

## Detailed Description

Нужно описать отдельный skill для предкоммитных проверок. Для текущего проекта перед коммитом кодовых задач должны выполняться `make lint` и `make typecheck`. Если проверка неприменима или не запускалась, это должно быть явно отражено в `taskN_progress.md`. Также нужно обновить правила проекта и конфигурацию `DEV`, чтобы это поведение было обязательным.

## Deliverables

- Документ со skill предкоммитных проверок
- Обновленные правила проекта
- Обновленная конфигурация `DEV`

## Context References

- `instration/tasks/task9.md`
- `AGENTS.md`

## Review References

- `instration/tasks/task39_review1.md`

## Progress References

- `instration/tasks/task39_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
