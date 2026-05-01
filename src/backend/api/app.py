from flask import Flask
from sqlalchemy.orm import Session, sessionmaker

from backend.api.auth import register_basic_auth_guard
from backend.api.routes import register_routes
from backend.composition import RuntimeContainer, init_app_container
from backend.db import get_session_factory
from backend.logging_setup import configure_flask_logging


def create_app(
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> Flask:
    app = Flask(__name__)
    active_runtime = init_app_container(app, runtime)
    app.extensions["session_factory"] = session_factory or get_session_factory()
    configure_flask_logging(
        app,
        app_name=active_runtime.settings.app_name,
        component="api",
    )
    register_basic_auth_guard(app, active_runtime.settings)
    register_routes(app)
    return app
