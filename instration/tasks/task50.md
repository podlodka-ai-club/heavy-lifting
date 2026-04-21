# Task 50

## Metadata

- ID: `task50`
- Title: Уточнить README для локального запуска и intake задачи
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task49`
- Next Tasks: `none`

## Goal

Сделать README более практичным: добавить минимальный env, пошаговый локальный запуск и готовый POST-запрос для постановки задачи в работу.

## Detailed Description

Нужно обновить `README.md` так, чтобы разработчик мог без чтения кода понять минимальный набор переменных окружения, накатить базу, запустить API и воркеры, а затем отправить задачу через `POST /tasks/intake`. Инструкции должны быть короткими, пошаговыми и пригодными для копирования в терминал.

## Deliverables

- Обновленный `README.md` с минимальным env
- Пошаговые команды запуска системы и bootstrap БД
- Готовый пример POST-запроса для intake задачи

## Context References

- `README.md`
- `src/backend/settings.py`
- `instration/tasks/task49.md`

## Review References

- `instration/tasks/task50_review1.md`

## Progress References

- `instration/tasks/task50_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.
