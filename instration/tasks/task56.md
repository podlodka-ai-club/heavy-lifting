# Task 56

## Metadata

- ID: `task56`
- Title: Перевести process-документацию на модель `docs` и `worklog`
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task54`, `task55`
- Next Tasks: `none`

## Goal

Зафиксировать новую модель проектной документации, в которой долговечные знания о системе живут в `docs/`, а кратковременная память разработчика или агента ведется в локальном `worklog/`.

## Detailed Description

Текущий процесс завязан на `instration/tasks/` как на постоянное место для task-артефактов. Для параллельной работы нескольких разработчиков или агентов это создает лишний шум в репозитории и смешивает долговечные факты о системе с локальным execution trail. Нужно перейти на новую модель:

- глобальное направление системы, архитектурные факты, контракты и process-правила фиксируются в `docs/`;
- локальный контекст по конкретной фиче ведется в `worklog/<username>/<worklog-id>/`;
- shared task registry в репозитории больше не используется как основной process-механизм;
- завершение worklog требует актуализации соответствующих документов в `docs/`.

В рамках задачи нужно создать стартовую структуру `docs/`, описать vision, roadmap и worklog-процесс, обновить общие правила в `AGENTS.md`, `instration/instruction.md` и связанных шаблонах, а также исключить `worklog/` из git.

## Deliverables

- Новая структура `docs/` с базовыми документами по vision и process
- Обновленные process-правила в `AGENTS.md` и `instration/`
- Игнорирование локального `worklog/` в git
- Обновленный README с новой моделью работы

## Context References

- `AGENTS.md`
- `README.md`
- `instration/instruction.md`
- `instration/TASK_TEMPLATE.md`
- `instration/project.md`

## Review References

- `instration/TASK_REVIEW_TEMPLATE.md`

## Progress References

- `instration/tasks/task56_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.
