# Task 48

## Metadata

- ID: `task48`
- Title: Добавить end-to-end сценарий API intake до CLI execution
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task47`
- Next Tasks: `task49`

## Goal

Подтвердить сквозной happy path от HTTP intake до выполнения runner-а и доставки результата.

## Detailed Description

Нужно покрыть тестом новый рабочий путь: задача создается через API, `worker1` забирает ее из tracker adapter, `worker2` подготавливает окружение и запускает CLI runner, `worker3` доставляет результат обратно в tracker. Для теста допускается использовать controllable/fake CLI runner behavior без реального сетевого доступа к модели, но orchestration chain должна быть максимально близка к реальному runtime flow.

## Deliverables

- Новый e2e тест для API -> worker1 -> worker2 -> worker3
- Проверки состояния задач, tracker update и execution result metadata

## Context References

- `tests/test_orchestration_e2e.py`
- `tests/test_api_stats.py`
- `src/backend/workers/tracker_intake.py`
- `src/backend/workers/execute_worker.py`
- `src/backend/workers/deliver_worker.py`

## Review References

- `instration/tasks/task48_review1.md`

## Progress References

- `instration/tasks/task48_progress.md`

## Result

Implemented and approved. See progress and summary artifacts for completion details.
