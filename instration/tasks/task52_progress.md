# Task Progress

## Metadata

- Task ID: `task52`
- Status: `done`
- Updated At: `2026-04-22`

## Progress Log

### Entry 1

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Начата task52 после ручной проверки локального запуска. Следующий шаг — через DEV обновить `README.md` под реальный demo flow и синхронизировать `docker-compose.yml` с инструкцией про доступ к Postgres с хоста.

### Entry 2

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Обновлены `README.md` и `docker-compose.yml`. В README основной ручной сценарий переключен на `make demo`, отдельно описаны режимы с `local` runner и `CliAgentRunner`, а запуск `make api` + отдельных воркеров помечен как нерекомендуемый для полного mock flow. В `docker-compose.yml` добавлена публикация `5432:5432` для `postgres`.

### Entry 3

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: Выполнены минимальные проверки: `docker compose config` для валидации compose-файла и `uv run pytest tests/test_demo.py -k shared_http_intake_flow` как smoke-проверка demo flow.

### Entry 4

- Date: `2026-04-22`
- Status: `in_progress`
- Notes: После `task52_review1` исправлен `README.md`: у варианта demo с `CliAgentRunner` теперь явно указано, что он опирается на те же обязательные подготовительные шаги, что и вариант с `local` runner (`uv sync` и `docker compose up -d postgres`). Дополнительные runtime-проверки не запускались, так как правка только документирует уже существующий сценарий.

### Entry 5

- Date: `2026-04-22`
- Status: `done`
- Notes: Получен `approved` в `instration/tasks/task52_review2.md`. Перед финальным commit выполнены обязательные проверки `make lint` и `make typecheck`, обе завершились успешно. Подготовлены финальные task-артефакты для закрытия задачи.

## Completion Summary

- Changed Files:
  - `README.md`
  - `docker-compose.yml`
  - `instration/tasks/task52.md`
  - `instration/tasks/task52_progress.md`
  - `instration/tasks/task52_review1.md`
  - `instration/tasks/task52_review2.md`
  - `instration/tasks/task52_summary.md`
- Checks:
  - `docker compose config` — passed
  - `uv run pytest tests/test_demo.py -k shared_http_intake_flow` — passed
  - `make lint` — passed
  - `make typecheck` — passed
- Assumptions:
  - В `README.md` за основной ручной сценарий принят именно full mock flow через `make demo`, а не отладка отдельных процессов.
  - Для реального запуска `CliAgentRunner` достаточно явно указать `AGENT_RUNNER_ADAPTER=cli` и `OPENAI_API_KEY`, а остальные `CLI_AGENT_*` параметры оставить опциональными.
- Risks:
  - Публикация `5432:5432` конфликтует с уже занятым локальным портом Postgres, если он используется на машине разработчика.
  - `make demo` остается foreground-командой, поэтому пользователю все еще нужно держать отдельный терминал открытым во время ручного `curl`-сценария.
