# Task 53

## Metadata

- ID: `task53`
- Title: Описать triage flow и маршрутизацию типов задач
- Status: `migrated`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task52`
- Next Tasks: `task54`, `task55`

## Goal

Зафиксировать целевой flow первичной оценки задачи из трекера и правила выбора дальнейшего сценария обработки.

## Detailed Description

Система больше не должна предполагать, что каждая новая задача из трекера сразу является задачей на кодовую реализацию. Для новых tracker tasks нужен обязательный первичный шаг triage, в котором оркестратор оценивает задачу, определяет возможность взять ее в работу, примерную сложность, story points и рекомендуемый дальнейший сценарий.

Нужно описать, какие входные сигналы используются для triage, какие исходы возможны, какие сценарии считаются минимально необходимыми для MVP и как маршрутизация соотносится с текущими worker stages `fetch/execute/deliver/pr_feedback`.

В рамках задачи нужно подготовить проектное описание без внедрения кода: taxonomy бизнес-типов задач, список outcomes triage, routing matrix и ограничения MVP. Отдельно нужно зафиксировать, где triage заканчивается ответом в tracker, а где порождает следующий execution step.

Legacy note: active continuation moved to the local worklog `worklog/denis/triage-routing/tasks/task01.md`.

## Deliverables

- Описание triage flow для новых задач из трекера
- Матрица маршрутизации `signal -> scenario -> next step`
- Список поддерживаемых бизнес-типов задач и исходов triage для MVP

## Context References

- `instration/project.md`
- `README.md`
- `src/backend/workers/tracker_intake.py`
- `src/backend/workers/execute_worker.py`
- `src/backend/workers/deliver_worker.py`

## Review References

- `instration/TASK_REVIEW_TEMPLATE.md`

## Progress References

- `instration/tasks/task53_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.

This legacy task file remains only as migration history. Continue active work in the worklog.
