# Task 52

## Metadata

- ID: `task52`
- Title: Уточнить локальный запуск demo pipeline и доступ к Postgres
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task51`
- Next Tasks: `none`

## Goal

Синхронизировать локальную документацию и compose-конфигурацию с фактическим сценарием ручного запуска demo pipeline.

## Detailed Description

После ручной проверки выяснилось, что `docker-compose.yml` не публикует порт Postgres на хост, а `README.md` рекомендует использовать `localhost:5432`. Дополнительно в документации нужно сделать явным новый способ локального прогона через `make demo`, а также различие между demo-запуском с `local` runner и реальным `CliAgentRunner`.

Нужно минимально обновить документацию и инфраструктурную конфигурацию так, чтобы шаги из README можно было реально повторить на локальной машине.

## Deliverables

- Обновленный `README.md` с фактическим demo flow
- Обновленный `docker-compose.yml` с доступом к Postgres с хоста
- Проверенные команды локального запуска

## Context References

- `README.md`
- `docker-compose.yml`
- `src/backend/demo.py`
- `instration/tasks/task51.md`

## Review References

- `instration/tasks/task52_review1.md`
- `instration/tasks/task52_review2.md`

## Progress References

- `instration/tasks/task52_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.
