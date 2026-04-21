# Task Progress

## Metadata

- Task ID: `task50`
- Status: `done`
- Updated At: `2026-04-21`

## Progress Log

### Entry 1

- Date: `2026-04-21`
- Status: `in_progress`
- Notes: Начата task50 по уточнению `README.md`. Следующий шаг — передать в DEV правки документации с минимальным env, пошаговым запуском и копируемым примером `POST /tasks/intake`.

### Entry 2

- Date: `2026-04-21`
- Status: `in_progress`
- Notes: Обновлен `README.md`: добавлен короткий блок `Быстрый старт локально` с копируемой последовательностью `uv sync` -> `docker compose up -d postgres` -> `export DATABASE_URL=...` -> `make bootstrap-db` -> `make api` и отдельными командами для `make worker1`, `make worker2`, `make worker3`, а также примером `curl` для `POST /tasks/intake`. Сокращено дублирование в разделе про локальный happy path и уточнено, что для базового локального запуска достаточно `DATABASE_URL`, а `AGENT_RUNNER_ADAPTER=cli` и ключ нужны только для реального CLI runner.

### Entry 3

- Date: `2026-04-21`
- Status: `in_progress`
- Notes: Проверка для docs-задачи: `python3 -c "from pathlib import Path; text = Path('README.md').read_text(); required = ['uv sync', 'docker compose up -d postgres', 'export DATABASE_URL=postgresql://heavy_lifting:heavy_lifting@localhost:5432/heavy_lifting', 'make bootstrap-db', 'make api', 'make worker1', 'make worker2', 'make worker3', 'curl -X POST http://127.0.0.1:8000/tasks/intake']; missing = [item for item in required if item not in text]; print('README commands check: OK' if not missing else 'Missing: ' + ', '.join(missing))"` -> `README commands check: OK`.

### Entry 4

- Date: `2026-04-21`
- Status: `done`
- Notes: После `approved` в `instration/tasks/task50_review1.md` задача переведена в `done`, подготовлен итоговый summary-артефакт, выполнены обязательные проверки `make lint` и `make typecheck`, затем создан финальный commit `task50 уточнить запуск в README`.

## Completion Summary

- Изменены файлы: `README.md`, `instration/tasks/task50_progress.md`.
- Assumptions: для минимального локального старта достаточно `DATABASE_URL`, потому что `src/backend/settings.py` собирает подключение из `POSTGRES_*`, но дефолтные `POSTGRES_USER/POSTGRES_PASSWORD` не совпадают с `docker-compose.yml`; для практического README безопаснее рекомендовать один копируемый `DATABASE_URL`.
- Риски для review: пример `POST /tasks/intake` описывает постановку задачи в API, но из-за in-memory состояния `MockTracker` и `MockScm` отдельные процессы API и воркеров не дают надежной проверки полного end-to-end pipeline; README теперь явно указывает на это ограничение и направляет к интеграционному тесту для полного flow.
