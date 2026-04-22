# Task Progress

## Metadata

- Task ID: `task51`
- Status: `done`
- Updated At: `2026-04-22`

## Progress Log

### Entry 1

- Date: `2026-04-21`
- Status: `in_progress`
- Notes: Начата task51 для локального ручного прогона pipeline. Следующий шаг — реализовать минимальный demo-режим с общим runtime container для API и воркеров и поддержкой локального workspace path для runner execution.

### Entry 2

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Добавлен модуль `src/backend/demo.py` с demo-сборкой на одном shared `RuntimeContainer` и одном `session_factory`: API создается через `create_app`, worker1/worker2/worker3 собираются через существующие `build_*_worker`, а entrypoint запускает Flask server и три воркера в одном процессе. В `pyproject.toml` добавлен script `heavy-lifting-demo`, в `Makefile` — target `demo`.

### Entry 3

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Обновлен `src/backend/adapters/mock_scm.py`: `ensure_workspace` теперь использует реальный локальный путь, если `repo_url` указывает на существующую директорию или `file://` URI на локальную директорию; иначе сохраняется прежний mock path `/tmp/mock-scm/<workspace_key>`. Это позволяет `CliAgentRunner` работать в реальном каталоге репозитория без внедрения полноценного git adapter.

### Entry 4

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Добавлены тесты `tests/test_demo.py` и расширены `tests/test_scm_protocol.py`: покрыты shared demo assembly, smoke intake flow через shared runtime и локальный workspace path для plain path и `file://`. Запущено: `uv run pytest tests/test_demo.py tests/test_scm_protocol.py tests/test_orchestration_e2e.py` — `14 passed`.

### Entry 5

- Date: `2026-04-22`
- Status: `done`
- Notes: После `approved` review обновлены финальные task-артефакты, повторно выполнены обязательные проверки `make lint` и `make typecheck`, затем подготовлен финальный commit для task51 с review-артефактом.

## Completion Summary

- Изменения:
  - Добавлен demo entrypoint для локального запуска API и трех воркеров в одном процессе с общим runtime/state.
  - `MockScm.ensure_workspace` научен возвращать реальный локальный workspace path для существующих локальных репозиториев.
  - Добавлены тесты на demo assembly/smoke flow и локальный workspace behavior.
- Проверки:
  - `uv run pytest tests/test_demo.py tests/test_scm_protocol.py tests/test_orchestration_e2e.py` -> `14 passed`.
- Assumptions:
  - Для task51 достаточно shared runtime и thread-based demo orchestration без отдельного supervisor/restart механизма.
  - Для локального repo path достаточно поддержать существующие директории и `file://` URI; clone/fetch/push остаются mock-операциями.
- Risks:
  - Demo entrypoint не инициализирует схему БД автоматически; перед ручным запуском база должна быть подготовлена отдельно.
  - Worker threads в demo-режиме запускаются как daemon threads и рассчитаны на локальный manual/demo сценарий, а не на production lifecycle management.
