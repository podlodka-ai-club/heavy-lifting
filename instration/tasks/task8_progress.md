# Task Progress

## Metadata

- Task ID: `task8`
- Status: `done`
- Updated At: `2026-04-20`

## Progress Log

### Entry 1

- Date: `2026-04-20`
- Status: `in_progress`
- Notes: Начата задача по настройке `pyproject.toml` и зависимостей через `uv`. Подготовлен запуск `DEV` для внесения изменений вне `instration/`.

### Entry 2

- Date: `2026-04-20`
- Status: `in_progress`
- Notes: Создан корневой `pyproject.toml` с метаданными проекта, зависимостями для MVP и базовой конфигурацией `uv`, `pytest`, `ruff` и `mypy` для локальной разработки.

### Entry 3

- Date: `2026-04-20`
- Status: `review`
- Notes: Выполнен `uv sync`, сгенерирован `uv.lock`, успешно пройдены `uv run ruff check src/backend`, `uv run mypy src/backend` и базовая проверка импорта Flask-приложения через `uv run python`.

### Entry 4

- Date: `2026-04-20`
- Status: `review`
- Notes: Выполнен cleanup артефактов после проверок: удалены каталоги `__pycache__` из `src/backend` и `src/backend/api`.

### Entry 5

- Date: `2026-04-20`
- Status: `done`
- Notes: После review повторно удалены `__pycache__`, появившиеся из-за прогонов проверок. Задача закрыта с решением `approved_with_comments`.

## Completion Summary

- Что сделано: Создан корневой `pyproject.toml`, проект настроен на Python `3.12`, добавлены runtime-зависимости (`flask`, `sqlalchemy`, `psycopg[binary]`, `pydantic`) и dev-зависимости (`pytest`, `ruff`, `mypy`), добавлены базовые tool-конфиги для `uv sync`, `uv run`, линтера, типизации и тестов. После синхронизации зависимостей зафиксирован `uv.lock`.
- Измененные файлы: `/home/denis/projects/heavy_lifting/pyproject.toml`, `/home/denis/projects/heavy_lifting/uv.lock`, `/home/denis/projects/heavy_lifting/instration/tasks/task8_progress.md`.
- Проверки: Запущены `uv sync`, `uv run ruff check src/backend`, `uv run mypy src/backend`, `uv run python -c "from backend.api.app import create_app; app = create_app(); print(app.name)"`.
- Итоговый статус: `done`.
