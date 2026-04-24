from flask import Blueprint, jsonify

from backend.api.openapi import build_openapi_schema

openapi_blueprint = Blueprint("openapi", __name__)


@openapi_blueprint.get("/openapi.json")
def get_openapi_schema():
    return jsonify(build_openapi_schema())


__all__ = ["openapi_blueprint"]
