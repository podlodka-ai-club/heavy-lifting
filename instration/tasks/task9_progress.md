# Task Progress

## Metadata

- Task ID: `task9`
- Status: `done`
- Updated At: `2026-04-20`

## Progress Log

### Entry 1

- Date: `2026-04-20`
- Status: `in_progress`
- Notes: Начата задача по добавлению корневого `Makefile`. Подготовлен запуск `DEV` для создания файла и настройки команд локальной разработки.

### Entry 2

- Date: `2026-04-20`
- Status: `review`
- Notes: Создан корневой `Makefile` с командами для `uv sync`, запуска Flask API, одноразового запуска `worker1`/`worker2`/`worker3`, а также для `ruff`, `mypy`, `pytest` и честного placeholder-таргета `bootstrap-db`/`init-db` до появления реальной инициализации базы.

### Entry 3

- Date: `2026-04-20`
- Status: `review`
- Notes: После прогона проверок доработан таргет `lint`: теперь он учитывает текущее состояние репозитория и не падает из-за отсутствующего каталога `tests`. Повторно подтверждены `make lint`, `make typecheck`, запуск трех воркеров, placeholder bootstrap и импорт Flask-приложения; `uv run pytest` завершается без тестов и с предупреждением о пустом `testpaths`.

## Completion Summary

- Что сделано: Добавлен корневой `Makefile` с практичными таргетами для локальной разработки MVP: установка зависимостей через `uv sync`, запуск API через Flask CLI, запуск трех воркеров через `uv run python -c`, проверки `lint`, `typecheck`, `test`, а также placeholder для bootstrap/init базы с явным сообщением о том, что реализация будет добавлена позже. Таргет `lint` дополнительно адаптирован под текущее состояние репозитория без каталога `tests`.
- Измененные файлы: `/home/denis/projects/heavy_lifting/Makefile`, `/home/denis/projects/heavy_lifting/instration/tasks/task9_progress.md`.
- Проверки: Запущены `make lint`, `make typecheck`, `make worker1`, `make worker2`, `make worker3`, `make bootstrap-db`, `uv run python -c "from backend.api.app import create_app; app = create_app(); print(app.name)"`, `uv run pytest`.
- Итоговый статус: `done`.
