from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_session, get_session_factory
from backend.models import RevenueConfidence, RevenueSource, TaskRevenue
from backend.services.economics_service import (
    Bucket,
    EconomicsService,
    RevenueUpsert,
    parse_datetime,
    parse_money,
    resolve_period,
)

economics_blueprint = Blueprint("economics", __name__)

_BUCKETS = {"day", "week", "month"}
_MANUAL_REVENUE_SOURCES = {RevenueSource.EXPERT.value, RevenueSource.EXTERNAL.value}


@economics_blueprint.get("/economics")
def get_economics():
    bucket = request.args.get("bucket", "day")
    if bucket not in _BUCKETS:
        return jsonify({"error": "bucket must be one of: day, week, month"}), 400

    try:
        from_value = parse_datetime(request.args.get("from"), "from")
        to_value = parse_datetime(request.args.get("to"), "to")
        resolve_period(from_value=from_value, to_value=to_value)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    session = _build_session()
    try:
        payload = EconomicsService(session).build_snapshot(
            from_value=from_value,
            to_value=to_value,
            bucket=cast(Bucket, bucket),
        )
    finally:
        session.close()

    return jsonify(payload)


@economics_blueprint.post("/economics/mock-revenue")
def generate_mock_revenue():
    payload_data = request.get_json(silent=True)
    if payload_data is None:
        payload_data = {}
    if not isinstance(payload_data, dict):
        return jsonify({"error": "Invalid mock revenue payload"}), 400

    try:
        min_usd = parse_money(payload_data.get("min_usd", "100"), "min_usd")
        max_usd = parse_money(payload_data.get("max_usd", "2500"), "max_usd")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if max_usd < min_usd:
        return jsonify({"error": "max_usd must be greater than or equal to min_usd"}), 400

    seed = payload_data.get("seed", "heavy-lifting-economics-v1")
    overwrite = payload_data.get("overwrite", False)
    if not isinstance(seed, str) or seed == "":
        return jsonify({"error": "seed must be a non-empty string"}), 400
    if not isinstance(overwrite, bool):
        return jsonify({"error": "overwrite must be a boolean"}), 400

    session = _build_session()
    try:
        payload = EconomicsService(session).generate_mock_revenue(
            min_usd=min_usd,
            max_usd=max_usd,
            seed=seed,
            overwrite=overwrite,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return jsonify(payload)


@economics_blueprint.put("/economics/revenue/<int:root_task_id>")
def upsert_revenue(root_task_id: int):
    payload_data = request.get_json(silent=True)
    if not isinstance(payload_data, dict):
        return jsonify({"error": "Invalid revenue payload"}), 400

    try:
        amount_usd = parse_money(payload_data.get("amount_usd"), "amount_usd")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    source_value = payload_data.get("source")
    if source_value not in _MANUAL_REVENUE_SOURCES:
        return jsonify({"error": "source must be one of: expert, external"}), 400

    confidence_value = payload_data.get("confidence")
    if confidence_value not in {item.value for item in RevenueConfidence}:
        return jsonify({"error": "confidence must be one of: estimated, actual"}), 400

    metadata_payload = payload_data.get("metadata")
    if metadata_payload is not None and not isinstance(metadata_payload, dict):
        return jsonify({"error": "metadata must be an object"}), 400

    session = _build_session()
    try:
        revenue = EconomicsService(session).upsert_revenue(
            root_task_id,
            RevenueUpsert(
                amount_usd=amount_usd,
                source=RevenueSource(source_value),
                confidence=RevenueConfidence(confidence_value),
                metadata_payload=metadata_payload,
            ),
        )
        if revenue is None:
            return jsonify({"error": f"Root task {root_task_id} not found"}), 404

        session.commit()
        payload = {"revenue": _serialize_revenue(revenue)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return jsonify(payload)


def _build_session() -> Session:
    session_factory = cast(
        sessionmaker[Session],
        current_app.extensions.get("session_factory") or get_session_factory(),
    )
    return create_session(session_factory=session_factory)


def _serialize_revenue(revenue: TaskRevenue) -> dict[str, Any]:
    return {
        "id": revenue.id,
        "root_task_id": revenue.root_task_id,
        "amount_usd": _format_decimal(revenue.amount_usd),
        "source": revenue.source.value,
        "confidence": revenue.confidence.value,
        "metadata": revenue.metadata_payload,
        "created_at": revenue.created_at.isoformat(),
        "updated_at": revenue.updated_at.isoformat(),
    }


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


__all__ = ["economics_blueprint"]
