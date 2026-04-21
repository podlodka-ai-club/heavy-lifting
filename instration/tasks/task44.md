# Task 44

## Metadata

- ID: `task44`
- Title: Добавить API intake endpoint для запуска задач
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task30`
- Next Tasks: `task45`

## Goal

Разрешить постановку новой execution-задачи через HTTP API.

## Detailed Description

Нужно добавить write endpoint для ручной постановки задачи в orchestrator. На первом этапе endpoint должен принимать минимальный набор полей для запуска кодовой задачи по репозиторию и создавать задачу через `TrackerProtocol`, чтобы текущий `worker1` продолжил работать как единая intake-точка.

Пока поддерживается happy path с `MockTracker`. Нужно определить request/response contract, сохранить typed payload через существующие `TaskContext` и `TaskInputPayload`, покрыть endpoint тестами и не обходить tracker layer прямой записью во внутреннюю БД.

## Deliverables

- Новый `POST` endpoint для intake задач
- Typed request mapping в tracker payload
- Тесты на успешное создание и базовую валидацию запроса

## Context References

- `instration/project.md`
- `src/backend/api/app.py`
- `src/backend/protocols/tracker.py`
- `src/backend/adapters/mock_tracker.py`

## Review References

- `instration/tasks/task44_review1.md`

## Progress References

- `instration/tasks/task44_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
