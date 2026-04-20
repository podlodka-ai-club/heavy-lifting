# Review 1

- verdict: `changes_requested`

## Findings

1. `src/backend/schemas.py:28`, `src/backend/schemas.py:36`, `src/backend/schemas.py:45`, `src/backend/schemas.py:68`

   Поля `metadata` объявлены как `dict[str, Any]`, поэтому схемы принимают произвольные Python-объекты, которые не гарантированно сериализуются в JSON для сохранения в `tasks.context`, `tasks.input_payload` и `tasks.result_payload`. Для MVP это ломает требование "suitable for JSON storage": модель можно успешно провалидировать, но затем получить невалидный для БД payload. Нужен явный JSON-совместимый тип (например, рекурсивный `JsonValue`) и тест, который подтверждает отказ на не-JSON-значениях.

## Notes

- По остальному объему задача выглядит хорошо: константы вынесены в `src/backend/task_constants.py` и переиспользуются в `src/backend/models.py`, enum-значения соответствуют `instration/project.md`, а целевые тесты `uv run pytest tests/test_models.py tests/test_schemas.py` проходят.
