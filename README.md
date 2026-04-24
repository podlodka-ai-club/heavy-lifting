# Heavy Lifting

`Heavy Lifting` — MVP backend-оркестратора на Python, Flask и PostgreSQL для автоматизации работы с задачами, кодом и pull request.

## Что есть в MVP

- Flask API с ручной intake-точкой `POST /tasks/intake`;
- PostgreSQL с таблицами `tasks` и `token_usage`;
- три воркера для pipeline `API intake -> worker1 -> worker2 -> worker3`;
- протоколы `TrackerProtocol` и `ScmProtocol`;
- mock-адаптеры `MockTracker` и `MockScm` для локальной разработки;
- `CliAgentRunner` для запуска внешнего CLI-агента через `opencode run`.

### Роли воркеров

- `worker1` забирает задачи из tracker intake, создает `fetch` и дочерние `execute`, а также подхватывает PR feedback;
- `worker2` обрабатывает `execute` и `pr_feedback`, готовит workspace, запускает `CliAgentRunner` или локальный runner, считает токены и работает с SCM;
- `worker3` обрабатывает `deliver` и отправляет результат обратно в трекер.

## Runtime Flow

Текущий happy path первого этапа выглядит так:

1. Клиент отправляет задачу в `POST /tasks/intake`.
2. API валидирует `TrackerTaskCreatePayload` и создает запись во `TrackerProtocol`.
3. `worker1` забирает задачу из трекера и создает в БД `fetch` + `execute`.
4. `worker2` подготавливает workspace, вызывает runner и после успеха создает `deliver`.
5. `worker3` публикует итог в трекер, комментарии и ссылки на PR.

Полезные endpoints API:

- `GET /health`
- `GET /tasks`
- `GET /tasks/<id>`
- `GET /stats`
- `POST /tasks/intake`

## Структура репозитория

- `src/backend` — код приложения;
- `tests` — тесты;
- `docs/` — долговечная документация по системе и процессам;
- `docs/vision/system.md` — актуальное vision и границы MVP;
- `docs/process/worklog.md` — workflow локального worklog;
- `instration/project.md` — supporting scope и правила на время миграции процесса;
- `AGENTS.md` — правила работы агентов в этом репозитории.

## Быстрый старт локально

Рекомендуемый ручной сценарий для полного локального mock pipeline теперь такой: `make demo` поднимает HTTP API и все три воркера в одном процессе, поэтому `MockTracker` и `MockScm` действительно разделяют общее in-memory состояние.

### Вариант 1. Demo c `local` runner

```bash
uv sync
docker compose up -d postgres

export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting

make bootstrap-db
make demo
```

Это основной сценарий для ручной проверки полного mock flow без реального вызова модели.

### Вариант 2. Demo c реальным `CliAgentRunner`

Этот вариант использует те же подготовительные шаги, что и вариант 1: зависимости уже должны быть установлены через `uv sync`, а Postgres должен быть поднят командой `docker compose up -d postgres`.

```bash
export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting
export AGENT_RUNNER_ADAPTER=cli
export OPENAI_API_KEY=replace-me

make bootstrap-db
make demo
```

Этот режим нужен только если вы хотите, чтобы `worker2` вызывал внешний CLI-агент. Для обычной локальной demo-проверки достаточно `local` runner по умолчанию.

`make api` и отдельные `make worker1` / `make worker2` / `make worker3` теперь не рекомендуются для ручного полного mock flow: это разные процессы, а `MockTracker` и `MockScm` хранят состояние в памяти процесса. Эти команды оставлены для точечной отладки отдельных компонентов.

Поставить задачу в intake:

```bash
curl -X POST http://127.0.0.1:8000/tasks/intake \
  -H 'Content-Type: application/json' \
  -d '{
    "context": {
      "title": "Проверка локального intake",
      "description": "Убедиться, что API принимает задачу и воркеры могут забрать ее в pipeline.",
      "acceptance_criteria": [
        "API возвращает external_id",
        "Задача видна в локальном pipeline"
      ]
    },
    "repo_url": "https://example.com/org/repo.git",
    "repo_ref": "main",
    "workspace_key": "demo-intake-task",
    "input_payload": {
      "instructions": "Обнови README и верни краткий итог.",
      "base_branch": "main"
    }
  }'
```

Ожидаемый результат: `201 Created` и JSON с `external_id`. После этого `make demo` должен сам протащить задачу через `worker1 -> worker2 -> worker3`.

## Локальная установка через `uv`

Требования:

- Python `3.12`;
- установленный `uv`;
- Docker и Docker Compose для локального Postgres.

Базовая установка:

```bash
uv sync
```

Или через `Makefile`:

```bash
make init
```

`make init` делает две вещи:

- запускает `uv sync`;
- устанавливает git hook `githooks/pre-commit`.

## Установка git hooks

Если зависимости уже установлены, hook можно поставить отдельно:

```bash
make install-git-hooks
```

Hook копирует `githooks/pre-commit` в `.git/hooks/pre-commit` и перед коммитом запускает:

- `make lint`;
- `make typecheck`.

Для изменений только в `instration/` и `AGENTS.md` hook проверки пропускает.

## Локальный Postgres через Docker Compose

Поднять только базу:

```bash
docker compose up -d postgres
```

Параметры по умолчанию из `docker-compose.yml`:

- `POSTGRES_DB=heavy_lifting`
- `POSTGRES_USER=heavy_lifting`
- `POSTGRES_PASSWORD=heavy_lifting`
- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=5432`

После `docker compose up -d postgres` база доступна с хоста на `localhost:5432`.

Важно: после `docker compose up -d postgres` нужен явный шаг настройки env для приложения. По умолчанию `src/backend/settings.py` использует `POSTGRES_USER=postgres` и `POSTGRES_PASSWORD=postgres`, а контейнер Postgres из `docker-compose.yml` поднимается с `heavy_lifting/heavy_lifting`. Поэтому для локального запуска проще всего экспортировать `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting
```

Альтернатива — экспортировать совместимые `POSTGRES_*` переменные перед `make bootstrap-db`, `make api` и запуском воркеров:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=heavy_lifting
export POSTGRES_USER=heavy_lifting
export POSTGRES_PASSWORD=heavy_lifting
```

## Env для runtime и CliAgentRunner

### Обязательные переменные

Минимум для `make demo`, `make api` и воркеров:

- `DATABASE_URL` или полный набор `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

Для запуска реального `CliAgentRunner` вместо локального runner дополнительно нужны:

- `AGENT_RUNNER_ADAPTER=cli`;
- ключ в переменной, имя которой задается `CLI_AGENT_API_KEY_ENV_VAR`.

Минимум для доступа `CliAgentRunner` к модели:

- переменная с API key, имя которой задается `CLI_AGENT_API_KEY_ENV_VAR`;
- по умолчанию это `OPENAI_API_KEY`, поэтому чаще всего достаточно экспортировать именно ее;
- если вы переопределяете `CLI_AGENT_API_KEY_ENV_VAR`, нужно экспортировать ключ уже под новым именем.

Для OpenAI-compatible инстанса с нестандартным endpoint дополнительно нужен base URL:

- имя env задается `CLI_AGENT_BASE_URL_ENV_VAR`;
- по умолчанию это `OPENAI_BASE_URL`.

Пример минимального env для `CliAgentRunner`:

```bash
export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting
export AGENT_RUNNER_ADAPTER=cli
export OPENAI_API_KEY=replace-me
```

### Опциональные настройки runner-а

Настройки из `src/backend/settings.py` для `CliAgentRunner`:

- `CLI_AGENT_COMMAND` — бинарь CLI, по умолчанию `opencode`;
- `CLI_AGENT_SUBCOMMAND` — подкоманда, по умолчанию `run`;
- `CLI_AGENT_TIMEOUT_SECONDS` — timeout subprocess, по умолчанию `1800`;
- `CLI_AGENT_PROVIDER` — provider hint для сборки `--model provider/model`;
- `CLI_AGENT_MODEL` — model hint для `opencode run --model ...`;
- `CLI_AGENT_PROFILE` — сохраняется в metadata результата, но сейчас не мапится в CLI args;
- `CLI_AGENT_API_KEY_ENV_VAR` — имя env с API key, по умолчанию `OPENAI_API_KEY`;
- `CLI_AGENT_BASE_URL_ENV_VAR` — имя env с base URL, по умолчанию `OPENAI_BASE_URL`.

Пример расширенной настройки:

```bash
export AGENT_RUNNER_ADAPTER=cli
export CLI_AGENT_COMMAND=opencode
export CLI_AGENT_SUBCOMMAND=run
export CLI_AGENT_TIMEOUT_SECONDS=1800
export CLI_AGENT_PROVIDER=openai
export CLI_AGENT_MODEL=gpt-5.4
export OPENAI_API_KEY=replace-me
```

## Подготовка базы данных

Перед первым запуском `make demo`, API или воркеров настройте env и подготовьте схему MVP:

```bash
make bootstrap-db
```

Эквивалентная команда через `uv`:

```bash
uv run heavy-lifting-bootstrap-db
```

Команда:

- создает только таблицы `tasks` и `token_usage`;
- безопасна для повторного запуска;
- поддерживает разовый override подключения.

Пример для разового bootstrap в SQLite:

```bash
uv run heavy-lifting-bootstrap-db --database-url sqlite+pysqlite:///./dev.db
```

`make init-db` — алиас для `make bootstrap-db`.

## Запуск API и воркеров

Перед запуском убедитесь, что база поднята, env настроен и схема создана.

Для ручного полного локального pipeline используйте `make demo`:

```bash
make demo
```

Команда запускает Flask API и фоновые worker threads в одном процессе.

API:

```bash
make api
```

Отдельные воркеры запускаются в разных терминалах:

```bash
make worker1
make worker2
make worker3
```

Эти команды используют `uv run` и текущие настройки окружения.

Для полного mock flow этот режим не рекомендуется, потому что in-memory состояние mock-адаптеров не разделяется между процессами. Он подходит для локальной отладки конкретного сервиса или воркера.

## Локальный happy path для `POST /tasks/intake`

Для ручной проверки используйте блок `Быстрый старт локально` выше: он уже содержит минимальный env, bootstrap БД, запуск `make demo` и копируемый `curl`.

## Проверки качества

```bash
make test
make lint
make typecheck
```

Команды соответствуют текущему `Makefile`:

- `make test` -> `uv run pytest`
- `make lint` -> `uv run ruff check src/backend tests`
- `make typecheck` -> `uv run mypy src/backend`

## Как воспроизвести полный flow локально

Для текущего MVP самый надежный локальный сценарий полного flow — прогнать интеграционный тест, потому что `MockTracker` и `MockScm` хранят состояние в памяти процесса.

Основной happy path `POST /tasks/intake -> worker1 -> worker2 -> worker3`:

```bash
uv run pytest tests/test_orchestration_e2e.py -k http_intake_flow_runs_workers_end_to_end
```

Сценарий с PR feedback:

```bash
uv run pytest tests/test_orchestration_e2e.py -k pr_feedback
```

Эти тесты подтверждают, что локальный mock flow:

- принимает задачу через `POST /tasks/intake` и прогоняет ее через `worker1`, `worker2` и `worker3`;
- создает `fetch`, `execute`, `deliver` и `pr_feedback` задачи;
- использует один и тот же branch/PR для follow-up итерации;
- сохраняет `token_usage`;
- возвращает результат обратно в `MockTracker`.

Если нужен именно контейнерный запуск, в `docker-compose.yml` уже описаны сервисы `api`, `worker1`, `worker2` и `worker3`, но для локальной разработки документация в этом README ориентирована на запуск через `uv` и `make`.

## Workflow через worklog

Основной процесс теперь описан в `docs/process/worklog.md` и `docs/vision/system.md`.

Короткая версия:

1. Прочитать `docs/vision/system.md`, чтобы свериться с целью системы, MVP scope и ключевыми сценариями.
2. Создать или обновить локальный worklog в `worklog/<username>/<worklog-id>/` до начала значимой работы.
3. Держать в worklog `context.md`, атомарные task-файлы, progress, review и summary по текущей задаче.
4. Выполнять цикл `DEV -> REVIEW -> DEV(commit)` для каждого атомарного изменения.
5. Перед завершением worklog обновить релевантные страницы в `docs/`, если появились новые долговечные знания.
6. Делать commit в формате `<worklog-id>/taskNN <короткое русское действие>` после review approval.

`instration/project.md`, `instration/instruction.md` и другие файлы в `instration/` остаются supporting-артефактами процесса, но shared task registry в репозитории больше не считается основным рабочим механизмом.
