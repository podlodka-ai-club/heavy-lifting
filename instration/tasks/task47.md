# Task 47

## Metadata

- ID: `task47`
- Title: Разделить prepare и execute стадии в worker2
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task46`
- Next Tasks: `task48`

## Goal

Сделать workflow worker2 явным: сначала подготовка окружения, затем запуск execution runner.

## Detailed Description

Сейчас `ExecuteWorker` выполняет prepare, runner execution и SCM finalization в одном линейном блоке. Нужно переразложить его на явные стадии внутри текущей трехворкерной схемы: подготовка workspace/branch/runtime metadata и отдельный шаг запуска `CliAgentRunner`. При этом не нужно добавлять четвертый воркер и по возможности не нужно добавлять новый `TaskType` на первом этапе.

Задача должна сохранить текущие инварианты по `pr_feedback`, reuse branch/PR и созданию deliver task для worker3.

## Deliverables

- Обновленный `ExecuteWorker` с явным prepare/execute flow
- Сохранение SCM/PR поведения для `execute` и `pr_feedback`
- Тесты на happy path и failure path обновленного worker2

## Context References

- `src/backend/workers/execute_worker.py`
- `tests/test_execute_worker.py`
- `tests/test_orchestration_e2e.py`

## Review References

- `instration/tasks/task47_review1.md`

## Progress References

- `instration/tasks/task47_progress.md`

## Result

Completed. Implementation, review approval, and final task closure are recorded in the matching progress, review, and summary files.
