# Task 54

## Metadata

- ID: `task54`
- Title: Спроектировать стандартизированный handoff contract между шагами pipeline
- Status: `migrated`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task53`
- Next Tasks: `task55`

## Goal

Определить единый контракт входных и выходных данных между шагами pipeline, чтобы результаты triage и execution можно было безопасно передавать дальше без парсинга свободного текста.

## Detailed Description

Текущие `context`, `input_payload` и `result_payload` уже существуют, но пока в основном ориентированы на coding flow и не разделяют явно бизнес-смысл шага, решение triage, routing metadata и delivery-ready output. Для поддержки исследований, оценок, clarification и других сценариев нужен формализованный handoff contract.

Нужно описать, какие данные считаются стабильным контекстом задачи, какие поля являются командой для текущего шага, а какие поля содержат структурированный результат для следующего шага. Отдельно нужно проработать, как `worker2` передает решение в `worker3`, чтобы доставка в tracker опиралась на machine-readable payload, а не на произвольный текст summary/details.

В рамках задачи нужно предложить schema shape для `context`, `input_payload` и `result_payload`, выделить обязательные и опциональные секции, определить versioning strategy и минимальный JSON contract для MVP. На текущем этапе задача включает фиксацию `input_payload v1` и `output_payload v1` в проектной спецификации, включая поля `action`, `constraints`, `handoff`, `expected_output`, `outcome`, `classification`, `estimate`, `routing`, `delivery` и `artifacts`.

Legacy note: active continuation moved to the local worklog `worklog/denis/triage-routing/tasks/task02.md`.

## Deliverables

- Проектный контракт для `context`, `input_payload` и `result_payload`
- Правила передачи данных между `triage`, `execution`, `deliver` и `pr_feedback`
- Набор обязательных machine-readable полей для routing и delivery

## Context References

- `instration/project.md`
- `src/backend/schemas.py`
- `src/backend/task_context.py`
- `src/backend/services/context_builder.py`
- `src/backend/workers/execute_worker.py`
- `src/backend/workers/deliver_worker.py`

## Review References

- `instration/TASK_REVIEW_TEMPLATE.md`

## Progress References

- `instration/tasks/task54_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.

This legacy task file remains only as migration history. Continue active work in the worklog.
