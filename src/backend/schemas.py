from dataclasses import dataclass


@dataclass(slots=True)
class BasePayload:
    name: str
