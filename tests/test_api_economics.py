from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, RevenueConfidence, RevenueSource, TaskRevenue
from backend.repositories.task_repository import (
    TaskCreateParams,
    TaskRepository,
    TokenUsageCreateParams,
)
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_get_economics_returns_empty_snapshot(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)
    before_request = datetime.now(UTC)

    response = app.test_client().get("/economics")
    after_request = datetime.now(UTC)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["generated_at"]
    assert payload["period"]["bucket"] == "day"
    period_from = datetime.fromisoformat(payload["period"]["from"])
    period_to = datetime.fromisoformat(payload["period"]["to"])
    assert before_request <= period_to <= after_request
    assert period_to - period_from == timedelta(days=30)
    assert payload["totals"] == {
        "closed_roots_count": 0,
        "monetized_roots_count": 0,
        "missing_revenue_count": 0,
        "revenue_usd": "0.000000",
        "token_cost_usd": "0.000000",
        "profit_usd": "0.000000",
    }
    assert payload["series"] == []
    assert payload["roots"] == []
    assert payload["data_gaps"] == [
        "infra_cost",
        "runner_hours",
        "external_accounting_import",
        "retry_waste",
    ]


def test_get_economics_completes_partial_period_bounds(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/economics?to=2026-04-30T00:00:00%2B00:00")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["period"] == {
        "from": "2026-03-31T00:00:00+00:00",
        "to": "2026-04-30T00:00:00+00:00",
        "bucket": "day",
    }


def test_get_economics_reports_closed_roots_revenue_costs_and_missing_revenue(
    session_factory,
) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        monetized_root = _create_closed_chain(
            repository,
            external_task_id="TASK-10",
            closed_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
        )
        feedback = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=monetized_root["execute_id"],
                status=TaskStatus.DONE,
            )
        )
        repository.record_token_usage(
            task_id=monetized_root["execute_id"],
            usage=TokenUsageCreateParams(
                model="gpt-5.4",
                provider="openai",
                cost_usd=Decimal("3.250000"),
            ),
        )
        repository.record_token_usage(
            task_id=feedback.id,
            usage=TokenUsageCreateParams(
                model="gpt-5.4",
                provider="openai",
                cost_usd=Decimal("1.500000"),
            ),
        )
        session.add(
            TaskRevenue(
                root_task_id=monetized_root["root_id"],
                amount_usd=Decimal("1500.000000"),
                source=RevenueSource.EXPERT,
                confidence=RevenueConfidence.ACTUAL,
                metadata_payload={"invoice": "INV-10"},
            )
        )

        missing_root = _create_closed_chain(
            repository,
            external_task_id="TASK-11",
            closed_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        )
        repository.record_token_usage(
            task_id=missing_root["deliver_id"],
            usage=TokenUsageCreateParams(
                model="gpt-5.4-mini",
                provider="openai",
                cost_usd=Decimal("0.250000"),
            ),
        )

        open_root = _create_open_chain(repository, external_task_id="TASK-OPEN")

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get(
        "/economics?bucket=day&from=2026-04-01T00:00:00%2B00:00&to=2026-04-30T00:00:00%2B00:00"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["totals"] == {
        "closed_roots_count": 2,
        "monetized_roots_count": 1,
        "missing_revenue_count": 1,
        "revenue_usd": "1500.000000",
        "token_cost_usd": "5.000000",
        "profit_usd": "1495.000000",
    }
    assert payload["series"] == [
        {
            "bucket": "2026-04-28",
            "closed_roots_count": 1,
            "monetized_roots_count": 1,
            "missing_revenue_count": 0,
            "revenue_usd": "1500.000000",
            "token_cost_usd": "4.750000",
            "profit_usd": "1495.250000",
        },
        {
            "bucket": "2026-04-29",
            "closed_roots_count": 1,
            "monetized_roots_count": 0,
            "missing_revenue_count": 1,
            "revenue_usd": "0.000000",
            "token_cost_usd": "0.250000",
            "profit_usd": "-0.250000",
        },
    ]
    assert payload["roots"] == [
        {
            "root_task_id": monetized_root["root_id"],
            "external_task_id": "TASK-10",
            "tracker_name": "mock",
            "closed_at": "2026-04-28T10:00:00+00:00",
            "revenue_usd": "1500.000000",
            "token_cost_usd": "4.750000",
            "profit_usd": "1495.250000",
            "revenue_source": "expert",
            "revenue_confidence": "actual",
        },
        {
            "root_task_id": missing_root["root_id"],
            "external_task_id": "TASK-11",
            "tracker_name": "mock",
            "closed_at": "2026-04-29T12:00:00+00:00",
            "revenue_usd": None,
            "token_cost_usd": "0.250000",
            "profit_usd": None,
            "revenue_source": None,
            "revenue_confidence": None,
        },
    ]
    assert open_root["root_id"] not in [root["root_task_id"] for root in payload["roots"]]


def test_get_economics_uses_first_successful_deliver_as_closed_at(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        root = _create_closed_chain(
            repository,
            external_task_id="TASK-MULTI-DELIVER",
            closed_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        )
        earlier_deliver = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=root["execute_id"],
                status=TaskStatus.DONE,
            )
        )
        earlier_deliver.updated_at = datetime(2026, 4, 28, 8, 30, tzinfo=UTC)

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get(
        "/economics?from=2026-04-01T00:00:00%2B00:00&to=2026-04-30T00:00:00%2B00:00"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["roots"][0]["closed_at"] == "2026-04-28T08:30:00+00:00"
    assert payload["series"][0]["bucket"] == "2026-04-28"


def test_post_mock_revenue_is_deterministic_and_idempotent(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        first_root = _create_closed_chain(
            repository,
            external_task_id="TASK-20",
            closed_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
        )
        second_root = _create_closed_chain(
            repository,
            external_task_id="TASK-21",
            closed_at=datetime(2026, 4, 28, 11, 0, tzinfo=UTC),
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    client = app.test_client()

    first_response = client.post(
        "/economics/mock-revenue",
        json={"min_usd": "10", "max_usd": "20", "seed": "seed-1"},
    )
    snapshot_response = client.get(
        "/economics?from=2026-04-01T00:00:00%2B00:00&to=2026-04-30T00:00:00%2B00:00"
    )
    second_response = client.post(
        "/economics/mock-revenue",
        json={"min_usd": "10", "max_usd": "20", "seed": "seed-1"},
    )
    second_snapshot_response = client.get(
        "/economics?from=2026-04-01T00:00:00%2B00:00&to=2026-04-30T00:00:00%2B00:00"
    )

    assert first_response.status_code == 200
    assert first_response.get_json() == {
        "created_count": 2,
        "updated_count": 0,
        "created_root_task_ids": [first_root["root_id"], second_root["root_id"]],
        "updated_root_task_ids": [],
    }
    assert second_response.status_code == 200
    assert second_response.get_json() == {
        "created_count": 0,
        "updated_count": 0,
        "created_root_task_ids": [],
        "updated_root_task_ids": [],
    }
    assert snapshot_response.get_json()["roots"] == second_snapshot_response.get_json()["roots"]
    assert all(root["revenue_source"] == "mock" for root in snapshot_response.get_json()["roots"])
    assert all(
        root["revenue_confidence"] == "estimated" for root in snapshot_response.get_json()["roots"]
    )


def test_put_revenue_upserts_manual_revenue(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        root = _create_closed_chain(
            repository,
            external_task_id="TASK-30",
            closed_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().put(
        f"/economics/revenue/{root['root_id']}",
        json={
            "amount_usd": "1250.50",
            "source": "external",
            "confidence": "actual",
            "metadata": {"invoice_id": "INV-30"},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["revenue"] == {
        "id": 1,
        "root_task_id": root["root_id"],
        "amount_usd": "1250.500000",
        "source": "external",
        "confidence": "actual",
        "metadata": {"invoice_id": "INV-30"},
        "created_at": response.get_json()["revenue"]["created_at"],
        "updated_at": response.get_json()["revenue"]["updated_at"],
    }

    snapshot = app.test_client().get(
        "/economics?from=2026-04-01T00:00:00%2B00:00&to=2026-04-30T00:00:00%2B00:00"
    ).get_json()

    assert snapshot["roots"][0]["revenue_usd"] == "1250.500000"
    assert snapshot["roots"][0]["revenue_source"] == "external"
    assert snapshot["roots"][0]["revenue_confidence"] == "actual"


def test_put_revenue_validates_manual_payload(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    bad_amount = app.test_client().put(
        "/economics/revenue/1",
        json={"amount_usd": "-1", "source": "expert", "confidence": "estimated"},
    )
    bad_source = app.test_client().put(
        "/economics/revenue/1",
        json={"amount_usd": "1", "source": "mock", "confidence": "estimated"},
    )
    missing_root = app.test_client().put(
        "/economics/revenue/999",
        json={"amount_usd": "1", "source": "expert", "confidence": "estimated"},
    )

    assert bad_amount.status_code == 400
    assert bad_source.status_code == 400
    assert missing_root.status_code == 404


def _create_closed_chain(
    repository: TaskRepository,
    *,
    external_task_id: str,
    closed_at: datetime,
) -> dict[str, int]:
    fetch = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.FETCH,
            status=TaskStatus.DONE,
            tracker_name="mock",
            external_task_id=external_task_id,
        )
    )
    execute = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
        )
    )
    deliver = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.DELIVER,
            parent_id=execute.id,
            status=TaskStatus.DONE,
        )
    )
    deliver.updated_at = closed_at
    return {"root_id": fetch.id, "execute_id": execute.id, "deliver_id": deliver.id}


def _create_open_chain(repository: TaskRepository, *, external_task_id: str) -> dict[str, int]:
    fetch = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.FETCH,
            status=TaskStatus.DONE,
            tracker_name="mock",
            external_task_id=external_task_id,
        )
    )
    execute = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.EXECUTE,
            parent_id=fetch.id,
            status=TaskStatus.DONE,
        )
    )
    deliver = repository.create_task(
        TaskCreateParams(
            task_type=TaskType.DELIVER,
            parent_id=execute.id,
            status=TaskStatus.NEW,
        )
    )
    return {"root_id": fetch.id, "execute_id": execute.id, "deliver_id": deliver.id}


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
