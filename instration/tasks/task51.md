# Task 51

## Metadata

- ID: `task51`
- Title: Добавить локальный demo pipeline для ручного прогона
- Status: `done`
- Priority: `high`
- Owner: `agent-programmer`
- Depends on: `task50`
- Next Tasks: `none`

## Goal

Дать разработчику способ локально прогнать весь pipeline intake в одном процессе с общим runtime state.

## Detailed Description

Сейчас `MockTracker` и `MockScm` хранят состояние в памяти процесса, поэтому раздельный запуск `api`, `worker1`, `worker2` и `worker3` не позволяет вручную прогнать полный pipeline. Нужно добавить минимальный локальный demo-режим, в котором API и три воркера используют один общий runtime container. Дополнительно нужно дать `worker2` реальный локальный workspace для `CliAgentRunner`, если в задаче передан путь к локальному репозиторию.

Решение должно быть минимальным и пригодным для ручной отладки: без замены mock-адаптеров на полноценные production integration, но с возможностью вручную отправить задачу через HTTP и довести ее до runner execution и delivery внутри одного процесса.

## Deliverables

- Локальный demo entrypoint для общего runtime API + workers
- Поддержка локального workspace path для mock SCM
- Тесты на demo flow / shared runtime behavior

## Context References

- `src/backend/api/app.py`
- `src/backend/composition.py`
- `src/backend/adapters/mock_tracker.py`
- `src/backend/adapters/mock_scm.py`
- `src/backend/workers/`

## Review References

- `instration/tasks/task51_review1.md`

## Progress References

- `instration/tasks/task51_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.
