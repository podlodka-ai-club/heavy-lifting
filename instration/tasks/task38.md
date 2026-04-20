# Task 38

## Metadata

- ID: `task38`
- Title: Описать skill для работы с конфигами
- Status: `done`
- Priority: `medium`
- Owner: `agent-orchestrator`
- Depends on: `task10`
- Next Tasks: `task11`

## Goal

Зафиксировать единый skill по работе с конфигами и использовать его при добавлении новых параметров.

## Detailed Description

Нужно описать проектный skill для конфигов: все настройки читаются централизованно в одном `settings.py`, без избыточной предварительной валидации. Если проверка нужна, она выполняется в точке инициализации или использования. В skill нужно добавить несколько примеров и сослаться на него в правилах, чтобы при добавлении новых параметров использовался именно этот подход.

## Deliverables

- Документ со skill по конфигам
- Обновленные правила с ссылкой на skill
- Явная отсылка к skill для будущих изменений настроек

## Context References

- `instration/tasks/task11.md`
- `AGENTS.md`

## Review References

- `instration/tasks/task38_review1.md`

## Progress References

- `instration/tasks/task38_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
