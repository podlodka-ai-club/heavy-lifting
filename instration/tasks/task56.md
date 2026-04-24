# Task 56

## Metadata

- ID: `task56`
- Title: Добавить архитектурную схему из Excalidraw
- Status: `done`
- Priority: `medium`
- Owner: `agent-programmer`
- Depends on: `task55`
- Next Tasks: `none`

## Goal

Сохранить в репозитории важную архитектурную информацию из Excalidraw-схемы и связать ее с текущей MVP-спецификацией.

## Detailed Description

Нужно извлечь архитектурную схему из Excalidraw room, описать бизнес-процесс, технические runtime loops, роли агентов, handoff между агентами, observability/statistics и backlog notes.

Документ должен отделять фактический MVP scope от идей будущего расширения. Нельзя превращать все роли и блоки со схемы в обязательный текущий scope без отдельной задачи.

Acceptance criteria:

- В `instration/` есть отдельный markdown-документ по архитектурной схеме.
- Документ содержит source link на Excalidraw.
- Документ описывает business process и technical runtime отдельно.
- Документ содержит mapping к текущей MVP-архитектуре.
- `instration/project.md` ссылается на новый архитектурный документ.

## Deliverables

- `instration/architecture_scheme.md`
- Обновление `instration/project.md`
- Task progress, review и summary файлы для `task56`

## Context References

- `https://excalidraw.com/#room=7ae73c4cdabd554ffdc9,uxtWZeYav-Yd2Mi_cFOidA`
- `instration/project.md`
- `instration/hacker_sprint_1.md`

## Review References

- `instration/tasks/task56_review1.md`

## Progress References

- `instration/tasks/task56_progress.md`

## Result

Keep the task definition stable. Put execution progress, completion notes, changed files, and test results into the matching progress file.

