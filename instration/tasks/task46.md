# Task 46

## Metadata

- ID: `task46`
- Title: Реализовать CliAgentRunner для opencode run
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task45`
- Next Tasks: `task47`

## Goal

Запускать реальный CLI-агент вместо локальной заглушки runner-а.

## Detailed Description

Нужно реализовать `CliAgentRunner`, который собирает команду для `opencode run`, запускает ее в подготовленном workspace и преобразует результат subprocess в нормализованный `TaskResultPayload`. На первом этапе достаточно happy path и предсказуемого failure path с сохранением `command`, `exit_code`, `stdout/stderr` preview и runner metadata.

Секреты доступа к модели должны читаться только из env процесса воркера. В payload задачи нельзя передавать API keys. Для prompt input нужно использовать уже собранный `EffectiveTaskContext` и `workspace_path`.

## Deliverables

- Реализация `CliAgentRunner`
- Подключение runner-а в composition через adapter name `cli`
- Тесты на command building и result normalization

## Context References

- `src/backend/services/agent_runner.py`
- `src/backend/protocols/agent_runner.py`
- `src/backend/task_context.py`
- `src/backend/services/context_builder.py`

## Review References

- `instration/tasks/task46_review1.md`
- `instration/tasks/task46_review2.md`

## Progress References

- `instration/tasks/task46_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
