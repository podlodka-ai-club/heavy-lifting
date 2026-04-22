# Task Review

## Metadata

- Task ID: `task52`
- Review Round: `1`
- Reviewer: `REVIEW`
- Review Date: `2026-04-22`
- Status: `changes_requested`

## Scope Reviewed

Проверены `instration/tasks/task52.md`, `instration/tasks/task52_progress.md`, `README.md` и `docker-compose.yml` на соответствие задаче, корректность локального demo flow, синхронизацию инструкции про `localhost:5432` с compose-конфигурацией и достаточность выполненных проверок.

## Findings

- `README.md:65` вводит в заблуждение во втором варианте demo c `CliAgentRunner`: блок выглядит как самостоятельный сценарий, но в нем не повторены или явно не унаследованы обязательные шаги `uv sync` и `docker compose up -d postgres`. Для задачи про воспроизводимый локальный flow это создает риск, что пользователь запустит `make demo` без поднятой БД и получит нерабочий сценарий.

## Risks

- После текущего README пользователь может трактовать вариант 2 как полный пошаговый рецепт и пропустить старт Postgres, хотя сама задача как раз должна убрать такие расхождения между документацией и реальным запуском.

## Required Changes

- Сделать в `README.md` явным, что вариант 2 опирается на базовую подготовку из варианта 1, либо повторить в нем обязательные шаги `uv sync` и `docker compose up -d postgres`.

## Final Decision

- `changes_requested`

## Notes

- `docker-compose.yml:8` корректно синхронизирован с инструкцией про доступ к Postgres через `localhost:5432`.
- Проверки из progress-файла для этой задачи выглядят достаточными: `docker compose config` валидирует compose, а smoke-тест demo flow подтверждает основной сценарий.

## Follow-Up

- После правки README нужен следующий review round в `instration/tasks/task52_review2.md`.
