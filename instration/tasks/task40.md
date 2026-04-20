# Task 40

## Metadata

- ID: `task40`
- Title: Добавить make init и make clean
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task9`
- Next Tasks: `task11`

## Goal

Добавить удобные команды для первичной инициализации окружения и очистки временных артефактов.

## Detailed Description

Нужно расширить корневой `Makefile` двумя таргетами:

- `make init` — подготовка локального окружения без лишней магии;
- `make clean` — удаление безопасно пересоздаваемых локальных артефактов разработки.

`make init` должен как минимум устанавливать зависимости через `uv sync`. `make clean` должен очищать кэши и временные артефакты Python-инструментов и сборки, но не удалять lock-файлы, репозиторные данные или что-то потенциально ценное.

## Deliverables

- Обновленный `Makefile`
- Таргет `init`
- Таргет `clean`

## Context References

- `instration/tasks/task9.md`
- `instration/PRE_COMMIT_CHECKS_SKILL.md`

## Review References

- `instration/tasks/task40_review1.md`

## Progress References

- `instration/tasks/task40_progress.md`

## Result

Definition only. Track implementation progress and completion details in the matching progress file.
