# Task 49

## Metadata

- ID: `task49`
- Title: Обновить документацию под API intake и CliAgentRunner
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task48`
- Next Tasks: `none`

## Goal

Отразить новый runtime flow в developer documentation и локальном run guide.

## Detailed Description

После внедрения API intake и `CliAgentRunner` нужно обновить `README.md` и связанные task/process docs так, чтобы разработчик мог локально поднять API, передать задачу через HTTP, запустить трехворкерный pipeline и понять, какие env settings нужны для доступа к модели и `opencode run`.

Документация должна явно разделять обязательные env-переменные, опциональные настройки runner-а и ожидаемый happy path первого этапа.

## Deliverables

- Обновленный `README.md` с flow API -> workers -> CLI execution
- Документированные env settings для `CliAgentRunner`
- Проверенные команды локального запуска для нового сценария

## Context References

- `README.md`
- `src/backend/settings.py`
- `instration/tasks/task34.md`

## Review References

- `instration/tasks/task49_review1.md`

## Progress References

- `instration/tasks/task49_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
