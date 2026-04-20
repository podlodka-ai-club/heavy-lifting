from dataclasses import dataclass


@dataclass(slots=True)
class BaseModel:
    id: int | None = None
