# Task 54

## Metadata

- ID: `task54`
- Title: Подготовить OpenAPI схему для REST API
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task52`
- Next Tasks: `COM-58`, `COM-60`

## Goal

Настроить генерацию OpenAPI схемы на стороне Flask API, чтобы фронтенд можно было генерировать и синхронизировать с фактическими REST-контрактами приложения.

## Detailed Description

Текущий API предоставляет health, stats и task endpoints, но не публикует машинно-читаемую OpenAPI схему. Нужно добавить endpoint со схемой без изменения существующих контрактов.

Схема должна описывать доступные REST endpoints, базовые ответы, payload для `POST /tasks/intake` и переиспользуемые компоненты из существующих Pydantic-схем там, где они уже являются источником контракта.

## Deliverables

- Endpoint `GET /openapi.json`
- Генерация схемы из кода приложения
- Тесты для проверки наличия ключевых paths/components
- Документация для получения схемы

## Context References

- `src/backend/api/app.py`
- `src/backend/api/routes`
- `src/backend/schemas.py`
- `README.md`

## Progress References

- `instration/tasks/task54_progress.md`

## Review References

- `instration/tasks/task54_review1.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.
