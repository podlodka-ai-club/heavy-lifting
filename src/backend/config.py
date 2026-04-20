from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    app_name: str = "backend"


def get_settings() -> Settings:
    return Settings()
