# Review 1

- Verdict: `changes_requested`

## Findings

1. `pr_feedback` branch reuse реализован некорректно. В `src/backend/workers/execute_worker.py:182` worker для любого flow безусловно вызывает `scm.create_branch(...)`, включая `pr_feedback`. По требованиям task27 и `instration/project.md:157` feedback-задачи должны переиспользовать существующую ветку/PR, а не заново создавать ветку от base ref. На `MockScm` это проходит, потому что адаптер молча перезаписывает запись ветки, но для реального SCM это типично приведет либо к ошибке "branch already exists", либо к потере ожидаемого branch state. Нужна отдельная логика sync/checkout существующей ветки для `pr_feedback`, плюс тест, который ловит попытку повторного create на уже существующей ветке.

## Checks

- Сверил реализацию с `instration/tasks/task27.md` и `instration/project.md`.
- Проверил orchestration `execute`/`pr_feedback`, восстановление context, persistence result payload/token usage, создание PR и child `deliver`.
- Прогнал `uv run pytest tests/test_execute_worker.py tests/test_composition.py` — все 12 тестов проходят.

## Notes

- Остальная схема выглядит согласованной: poll обрабатывает `execute` и `pr_feedback`, context собирается через `ContextBuilder`, result/token usage сохраняются, `execute` создает `deliver`, а `pr_feedback` обновляет parent `execute` metadata и не создает лишний `deliver`.
- Но до исправления branch reuse решение нельзя считать готовым для следующих worker tasks и реального SCM-адаптера.
