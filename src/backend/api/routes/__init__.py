from flask import Flask

from backend.api.routes.stats import stats_blueprint


def register_routes(app: Flask) -> None:
    app.register_blueprint(stats_blueprint)


__all__ = ["register_routes"]
