from flask import Blueprint, jsonify

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/health")
def get_health():
    return jsonify({"status": "ok"})


__all__ = ["health_blueprint"]
