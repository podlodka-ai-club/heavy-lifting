# Task Review

## Metadata

- Task ID: `task13`
- Review Round: `2`
- Reviewer: `REVIEW`
- Review Date: `2026-04-20`
- Status: `changes_requested`

## Scope Reviewed

Проверены `instration/tasks/task13.md`, `instration/tasks/task13_progress.md`, `instration/project.md`, текущий diff и итоговое состояние `src/backend/models.py`, `tests/test_models.py`, `pyproject.toml`.

## Findings

- `instration/tasks/task13.md:7` и `instration/tasks/task13.md:42` все еще фиксируют задачу как `blocked` и утверждают, что финальный commit заблокирован из-за `pyproject.toml`, хотя в `instration/tasks/task13_progress.md:21`-`instration/tasks/task13_progress.md:23` уже отражено устранение блокера и успешный прогон `make lint`, `make typecheck` и `uv run pytest tests/test_models.py tests/test_db.py`. Это делает итоговое состояние task13 неконсистентным и не позволяет считать задачу корректно завершенной на уровне task-артефактов.

## Final Decision

- `changes_requested`

## Notes

Кодовая часть task13 выглядит корректной: модель `tasks`, enum-значения, индексы и тесты соответствуют MVP-спецификации, а исправление зависимости в `pyproject.toml` больше не блокирует pre-commit проверки. Требуется только синхронизировать финальный статус и результат в `instration/tasks/task13.md` с фактическим состоянием задачи.
