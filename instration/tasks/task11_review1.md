# Task Review

## Metadata

- Task ID: `task11`
- Review Round: `1`
- Reviewer: `REVIEW`
- Review Date: `2026-04-20`
- Status: `changes_requested`

## Scope Reviewed

Проверены `instration/tasks/task11.md`, `instration/tasks/task11_progress.md`, `instration/CONFIG_SETTINGS_SKILL.md`, `src/backend/settings.py`, `src/backend/config.py`, `tests/test_settings.py`, `instration/TASK_REVIEW_TEMPLATE.md`, а также совместимость нового `DATABASE_URL` с текущим стеком зависимостей и Docker Compose окружением.

## Findings

- `src/backend/settings.py:17` оставляет явный `DATABASE_URL` без нормализации, а в `docker-compose.yml` по умолчанию задан `postgresql://...`. В проекте установлен только `psycopg` 3 (`pyproject.toml:14`), поэтому SQLAlchemy пытается загрузить `psycopg2` и падает уже на `create_engine('postgresql://...')` с `ModuleNotFoundError: No module named 'psycopg2'`. Это нарушает цель задачи про конфигурацию, пригодную для Docker Compose.

## Risks

- Сервисы, запущенные через текущее compose-окружение, не смогут инициализировать подключение к PostgreSQL, даже если `settings.py` и его тесты проходят локально.

## Required Changes

- Привести формат `DATABASE_URL` к совместимому с установленным драйвером `psycopg` во всем конфигурационном слое для Docker Compose сценария: либо нормализовать `postgresql://` -> `postgresql+psycopg://` в `src/backend/settings.py`, либо синхронно изменить источник значения так, чтобы compose и tests покрывали рабочий URL для SQLAlchemy.
- Добавить проверку, которая фиксирует этот сценарий и не дает снова принять несовместимый `DATABASE_URL` из окружения Docker Compose.

## Final Decision

- `changes_requested`

## Notes

Проверка `uv run pytest tests/test_settings.py` проходит, но она пока не покрывает главный интеграционный путь с compose-переменной `DATABASE_URL`.

## Follow-Up

- Если исправления будут внесены, создать следующий review-файл как `task11_review2.md`.
