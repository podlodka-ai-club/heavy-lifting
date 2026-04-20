from flask import Flask

from backend.composition import RuntimeContainer, init_app_container


def create_app(runtime: RuntimeContainer | None = None) -> Flask:
    app = Flask(__name__)
    init_app_container(app, runtime)
    return app
