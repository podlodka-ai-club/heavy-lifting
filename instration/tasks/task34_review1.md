# Task 34 Review 1

## Metadata

- Task ID: `task34`
- Review Round: `1`
- Reviewer: `REVIEW`
- Review Date: `2026-04-21`

## Verdict

- `request changes`

## Findings

- Blocking: `README.md:84`-`README.md:96` и `README.md:118`-`README.md:136` описывают локальный запуск так, как будто после `docker compose up -d postgres` можно сразу делать `make bootstrap-db`, `make api` и `make worker1..3`. Это не соответствует реальному состоянию репозитория: без `DATABASE_URL` приложение собирает подключение из `POSTGRES_*`, а значения по умолчанию в `src/backend/settings.py:57` и `src/backend/settings.py:58` — `postgres/postgres`, тогда как `docker-compose.yml:5`-`docker-compose.yml:7` поднимает БД с `heavy_lifting/heavy_lifting`. В текущем виде local run guide пропускает обязательный шаг экспорта `POSTGRES_USER`/`POSTGRES_PASSWORD` либо `DATABASE_URL`, поэтому инструкция недостоверна и блокирует первый успешный запуск.

## Notes

- В остальном diff соответствует цели task34: README стал заметно полезнее, команды из `Makefile` и сервисы из `docker-compose.yml` отражены корректно.
- Workflow `DEV -> REVIEW -> DEV(commit)` в `README.md` описан достаточно явно.
