# Config Settings Skill

## Purpose

Этот skill задает единый подход к работе с конфигами в проекте.

## Rules

- Все настройки читаются централизованно в одном файле: `src/backend/settings.py`.
- Не нужно добавлять избыточную предварительную валидацию всех настроек "на всякий случай".
- Если настройка требует проверки, проверка выполняется там, где настройка инициализирует конкретный ресурс или реально используется.
- В `settings.py` допустимы только простые операции:
  - чтение env-переменных;
  - задание значений по умолчанию;
  - простое приведение типов.
- Не добавляй отдельный сложный слой валидации конфигов без явной необходимости.

## Recommended Pattern

- Используй один `Settings` объект или одну функцию `get_settings()`.
- Новые параметры добавляй в `src/backend/settings.py`.
- Проверяй корректность параметров ближе к месту использования:
  - настройки БД — в инициализации БД;
  - интервалы polling — при запуске воркера;
  - пути к workspace — в сервисе или воркере, который работает с файловой системой.

## Examples

### Example 1: simple env mapping

```python
from dataclasses import dataclass
import os


@dataclass(slots=True)
class Settings:
    workspace_root: str
    tracker_poll_interval: int


def get_settings() -> Settings:
    return Settings(
        workspace_root=os.getenv("WORKSPACE_ROOT", "/workspace/repos"),
        tracker_poll_interval=int(os.getenv("TRACKER_POLL_INTERVAL", "30")),
    )
```

Здесь `settings.py` только читает значения и приводит `TRACKER_POLL_INTERVAL` к `int`.

### Example 2: validate at usage point

```python
from backend.settings import get_settings


def start_worker() -> None:
    settings = get_settings()
    if settings.tracker_poll_interval <= 0:
        raise ValueError("TRACKER_POLL_INTERVAL must be greater than 0")
```

Проверка делается в месте запуска воркера, а не как глобальная предварительная валидация всех настроек.

### Example 3: validate on initialization

```python
from sqlalchemy import create_engine

from backend.settings import get_settings


def build_engine():
    settings = get_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required")
    return create_engine(settings.database_url)
```

Проверка `database_url` живет рядом с инициализацией подключения к БД.

## When Adding New Settings

- Всегда сначала используй этот skill.
- Добавляй новый параметр в `src/backend/settings.py`.
- Не выноси валидацию в отдельный абстрактный слой, если параметр можно проверить прямо в месте использования.
- Если отклоняешься от этого skill, зафиксируй причину в задаче или review.
