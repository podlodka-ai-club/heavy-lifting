# Task 45

## Metadata

- ID: `task45`
- Title: Добавить настройки и контракт CliAgentRunner
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task44`
- Next Tasks: `task46`

## Goal

Подготовить typed configuration и runner contract для запуска внешнего CLI-агента.

## Detailed Description

Нужно расширить `src/backend/settings.py` и связанные контракты так, чтобы orchestrator мог запускать CLI-агент через настройки окружения, не передавая секреты в task payload. На этом этапе нужно определить минимальный набор env-based настроек для `CliAgentRunner`: бинарь, subcommand, timeout, provider/model hints и доступ к OpenAI-compatible API через переменные окружения процесса.

Нужно сохранить централизованную модель настроек из `CONFIG_SETTINGS_SKILL.md`, не добавлять лишний validation layer и определить, какие данные runner обязан вернуть в нормализованном `TaskResultPayload`.

## Deliverables

- Новые поля в `Settings` для CLI runner
- Обновленный adapter wiring contract для выбора `cli` runner
- Тесты на settings/composition contract

## Context References

- `instration/CONFIG_SETTINGS_SKILL.md`
- `src/backend/settings.py`
- `src/backend/composition.py`
- `src/backend/protocols/agent_runner.py`

## Review References

- `instration/tasks/task45_review1.md`

## Progress References

- `instration/tasks/task45_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
