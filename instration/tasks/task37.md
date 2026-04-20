# Task 37

## Metadata

- ID: `task37`
- Title: Зафиксировать автоматический коммит после review approval
- Status: `done`
- Priority: `medium`
- Owner: `agent-orchestrator`
- Depends on: `task35`
- Next Tasks: `task9`

## Goal

Уточнить правила процесса так, чтобы после approval от `REVIEW` коммит создавался автоматически без дополнительного запроса пользователю.

## Detailed Description

Нужно обновить правила в `AGENTS.md` и `instration/instruction.md`, чтобы было явно зафиксировано: после завершения атомарной задачи и approval от `REVIEW` сабагент `DEV` обязан создать коммит сам, без дополнительного вопроса пользователю. Также нужно синхронизировать правило в конфигурации сабагента `DEV`.

## Deliverables

- Обновленный `AGENTS.md`
- Обновленный `instration/instruction.md`
- Обновленная конфигурация `DEV`

## Context References

- `instration/instruction.md`
- `AGENTS.md`

## Review References

- `instration/tasks/task37_review1.md`

## Progress References

- `instration/tasks/task37_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
