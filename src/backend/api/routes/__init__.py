from flask import Flask

from backend.api.routes.health import health_blueprint
from backend.api.routes.openapi import openapi_blueprint
from backend.api.routes.prompts import prompts_blueprint
from backend.api.routes.retro import retro_blueprint
from backend.api.routes.settings import settings_blueprint
from backend.api.routes.stats import stats_blueprint
from backend.api.routes.tasks import tasks_blueprint


def register_routes(app: Flask) -> None:
    app.register_blueprint(health_blueprint)
    app.register_blueprint(openapi_blueprint)
    app.register_blueprint(prompts_blueprint)
    app.register_blueprint(retro_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(stats_blueprint)
    app.register_blueprint(tasks_blueprint)


__all__ = ["register_routes"]
