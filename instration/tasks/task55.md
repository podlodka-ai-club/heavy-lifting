# Task 55

## Metadata

- ID: `task55`
- Title: Описать event ingestion для комментариев в tracker и PR
- Status: `migrated`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task53`, `task54`
- Next Tasks: `none`

## Goal

Спроектировать единый подход к периодическому сбору новых событий из tracker и SCM без смешивания intake новых задач с follow-up событиями.

## Detailed Description

Помимо новых задач, система должна реагировать на дополнительные события: комментарии в tracker, PR feedback, изменения статуса и другие follow-up сигналы. Сейчас polling PR feedback уже встроен в `worker1`, но в дальнейшем это может потребовать отдельного worker-а или выделенного monitor flow.

Нужно описать, какие события считаются входом в оркестратор, как они нормализуются, в какие internal tasks преобразуются и как исключаются дубликаты. Отдельно нужно проработать, нужно ли в MVP выносить polling comments/PR feedback в отдельный worker или пока достаточно оставить это в ingestion worker с явным разделением ролей.

В рамках задачи нужно подготовить проектное решение без кода: event taxonomy, deduplication keys, mapping событий в internal tasks и рекомендуемое разбиение ответственности по worker-ам.

Legacy note: active continuation moved to the local worklog `worklog/denis/triage-routing/tasks/task03.md`.

## Deliverables

- Описание event taxonomy для tracker и SCM
- Правила нормализации и deduplication для follow-up событий
- Рекомендация по выделению отдельного monitor worker или сохранению логики в текущем ingestion worker

## Context References

- `instration/project.md`
- `src/backend/workers/tracker_intake.py`
- `src/backend/protocols/tracker.py`
- `src/backend/protocols/scm.py`

## Review References

- `instration/TASK_REVIEW_TEMPLATE.md`

## Progress References

- `instration/tasks/task55_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.

This legacy task file remains only as migration history. Continue active work in the worklog.
