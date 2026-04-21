# Heavy Lifting

`Heavy Lifting` — MVP backend-оркестратора на Python, Flask и PostgreSQL для автоматизации работы с задачами, кодом и pull request.

## Что есть в MVP

- Flask API;
- PostgreSQL с таблицами `tasks` и `token_usage`;
- три воркера для этапов `fetch -> execute -> deliver`;
- протоколы `TrackerProtocol` и `ScmProtocol`;
- mock-адаптеры `MockTracker` и `MockScm` для локальной разработки.

### Роли воркеров

- `worker1` забирает задачи из трекера и PR feedback;
- `worker2` выполняет `execute` и `pr_feedback`, считает токены, работает с mock SCM;
- `worker3` доставляет результат обратно в трекер.

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

Эти команды используют `uv run` и текущие настройки окружения. Flask API сейчас регистрирует endpoint `GET /stats`.

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

## Как воспроизвести mock-based orchestration flow локально

Для текущего MVP самый надежный локальный сценарий — прогнать интеграционный тест, потому что `MockTracker` и `MockScm` хранят состояние в памяти процесса.

Основной happy path `fetch -> execute -> deliver`:

```bash
uv run pytest tests/test_orchestration_e2e.py -k fetch_execute_deliver
```

Сценарий с PR feedback:

```bash
uv run pytest tests/test_orchestration_e2e.py -k pr_feedback
```

Эти тесты подтверждают, что локальный mock flow:

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
