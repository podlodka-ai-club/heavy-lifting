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
- `instration/project.md` — актуальный scope MVP;
- `instration/instruction.md` — workflow по task-файлам;
- `instration/tasks/` — атомарные задачи, progress, review и summary;
- `AGENTS.md` — правила работы агентов в этом репозитории.

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

Важно: после `docker compose up -d postgres` нужен явный шаг настройки env для приложения. По умолчанию `src/backend/settings.py` использует `POSTGRES_USER=postgres` и `POSTGRES_PASSWORD=postgres`, а контейнер Postgres из `docker-compose.yml` поднимается с `heavy_lifting/heavy_lifting`.

Самый простой вариант — экспортировать `DATABASE_URL`:

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

Минимум для локального запуска приложения:

- `DATABASE_URL` или полный набор `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`;
- при запуске реального CLI runner: `AGENT_RUNNER_ADAPTER=cli`.

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

Перед первым запуском API и воркеров сначала настройте env как описано выше, затем подготовьте схему MVP:

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

API:

```bash
make api
```

Воркеры запускаются в отдельных терминалах:

```bash
make worker1
make worker2
make worker3
```

Эти команды используют `uv run` и текущие настройки окружения.

## Локальный happy path для `POST /tasks/intake`

### 1. Подготовить env и БД

```bash
export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting
export AGENT_RUNNER_ADAPTER=cli
export OPENAI_API_KEY=replace-me
make bootstrap-db
```

### 2. Поднять API

```bash
make api
```

### 3. Отправить задачу в intake

```bash
curl -X POST http://127.0.0.1:8000/tasks/intake \
  -H 'Content-Type: application/json' \
  -d '{
    "context": {
      "title": "Обновить README под новый flow",
      "description": "Проверка локального intake happy path",
      "acceptance_criteria": ["README отражает новый pipeline"]
    },
    "repo_url": "https://example.com/org/repo.git",
    "repo_ref": "main",
    "workspace_key": "demo-readme-task",
    "input_payload": {
      "instructions": "Обнови документацию и верни краткий итог.",
      "base_branch": "main"
    }
  }'
```

Ожидаемый результат первого этапа: API вернет `201` и JSON вида `{"external_id":"..."}`.

### 4. Запустить pipeline воркеров

```bash
make worker1
make worker2
make worker3
```

Важно: текущие `MockTracker` и `MockScm` хранят состояние в памяти процесса. Поэтому отдельные процессы `make api` и `make worker1` не разделяют tracker state между собой. Из-за этого для локальной проверки полного pipeline на mock-адаптерах надежнее использовать интеграционный тест ниже.

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

## Workflow по task-файлам

Рабочий процесс описан в `instration/instruction.md` и `AGENTS.md`.

Короткая версия:

1. Прочитать `instration/project.md`.
2. Создать или обновить `instration/tasks/taskN.md` и `instration/tasks/taskN_progress.md` до начала значимой работы.
3. Выполнить атомарную задачу и писать ход работы только в `instration/tasks/taskN_progress.md`.
4. Передать результат в `REVIEW` и сохранить вывод в `instration/tasks/taskN_reviewK.md`.
5. Если review принят, завершить задачу коммитом в формате `taskN <короткое русское действие>`.
6. Сохранить короткий итог в `instration/tasks/taskN_summary.md`.

Обязательный цикл для атомарной задачи:

```text
DEV -> REVIEW -> DEV(commit)
```

Дополнительные правила:

- не делать commit до review approval;
- один atomic task = один commit;
- перед коммитом кодовых изменений запускать `make lint` и `make typecheck`;
- историю follow-up итераций хранить в дочерних `pr_feedback` задачах.
