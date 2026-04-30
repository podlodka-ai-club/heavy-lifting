from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.demo_seed import DEMO_EXTERNAL_ID_PREFIX, main, seed_frontend_demo
from backend.models import Base, Task, TaskRevenue, TokenUsage
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.task_constants import TaskStatus, TaskType


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_seed_frontend_demo_is_idempotent_and_preserves_non_demo_rows(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        non_demo_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.NEW,
                tracker_name="mock",
                external_task_id="USER-TASK-1",
            )
        )
        non_demo_task_id = non_demo_task.id

    first_result = seed_frontend_demo(session_factory=session_factory)
    first_counts = _counts(session_factory)
    second_result = seed_frontend_demo(session_factory=session_factory)
    second_counts = _counts(session_factory)

    assert first_result == second_result
    assert first_counts == second_counts
    assert first_counts == {
        "tasks": 28,
        "demo_tasks": 27,
        "token_usage": 8,
        "revenue": 3,
    }

    with session_scope(session_factory=session_factory) as session:
        non_demo_task = session.get(Task, non_demo_task_id)
        assert non_demo_task is not None
        assert non_demo_task.external_task_id == "USER-TASK-1"


def test_seed_frontend_demo_makes_factory_snapshot_non_empty(session_factory) -> None:
    seed_frontend_demo(session_factory=session_factory)

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get("/factory")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["bottleneck"] == {"station": "execute", "wip_count": 6}
    stations = {station["name"]: station for station in payload["stations"]}
    assert set(stations) == {"fetch", "execute", "pr_feedback", "deliver"}
    assert all(station["total_count"] > 0 for station in stations.values())
    assert all(station["wip_count"] > 0 for station in stations.values())
    assert stations["execute"]["failed_count"] == 2
    assert stations["pr_feedback"]["failed_count"] == 1


def test_seed_frontend_demo_makes_economics_snapshot_monetized(session_factory) -> None:
    seed_frontend_demo(session_factory=session_factory)

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get("/economics")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["totals"]["closed_roots_count"] == 3
    assert payload["totals"]["monetized_roots_count"] == 3
    assert payload["totals"]["missing_revenue_count"] == 0
    assert Decimal(payload["totals"]["revenue_usd"]) > 0
    assert Decimal(payload["totals"]["token_cost_usd"]) > 0
    assert len(payload["series"]) == 3
    assert {root["revenue_source"] for root in payload["roots"]} == {"expert", "external"}
    assert {root["revenue_confidence"] for root in payload["roots"]} == {
        "actual",
        "estimated",
    }


def test_main_accepts_database_url_override_and_seeds_demo_data(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"

    exit_code = main(["--database-url", database_url])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert "Frontend demo data is ready; tasks=27, token_usage=8, revenues=3" in stdout

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    assert _counts(session_factory) == {
        "tasks": 27,
        "demo_tasks": 27,
        "token_usage": 8,
        "revenue": 3,
    }


def _counts(session_factory) -> dict[str, int]:
    with session_scope(session_factory=session_factory) as session:
        return {
            "tasks": session.query(Task).count(),
            "demo_tasks": session.query(Task)
            .filter(Task.external_task_id.like(f"{DEMO_EXTERNAL_ID_PREFIX}%"))
            .count(),
            "token_usage": session.query(TokenUsage).count(),
            "revenue": session.query(TaskRevenue).count(),
        }


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
