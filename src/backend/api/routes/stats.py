from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, jsonify
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_session, get_session_factory
from backend.services.stats_service import StatsService

stats_blueprint = Blueprint("stats", __name__)


@stats_blueprint.get("/stats")
def get_stats():
    session_factory = cast(
        sessionmaker[Session],
        current_app.extensions.get("session_factory") or get_session_factory(),
    )
    session = create_session(session_factory=session_factory)
    try:
        payload = StatsService(session).build_stats()
    finally:
        session.close()

    return jsonify(payload)


__all__ = ["stats_blueprint"]
