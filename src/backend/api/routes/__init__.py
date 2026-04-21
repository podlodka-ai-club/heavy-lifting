from flask import Flask

from backend.api.routes.health import health_blueprint
from backend.api.routes.stats import stats_blueprint
from backend.api.routes.tasks import tasks_blueprint


def register_routes(app: Flask) -> None:
    app.register_blueprint(health_blueprint)
    app.register_blueprint(stats_blueprint)
    app.register_blueprint(tasks_blueprint)


__all__ = ["register_routes"]
