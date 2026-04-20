from dataclasses import dataclass


@dataclass(slots=True)
class ContextBuilder:
    name: str = "context-builder"
