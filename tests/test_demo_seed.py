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
from backend.models import AgentFeedbackEntry, Base, Task, TaskRevenue, TokenUsage
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import LocalAgentRunner
from backend.services.retro_service import RetroService
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
        RetroService(session).record_agent_feedback(
            task=non_demo_task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": "user-owned",
                        "severity": "info",
                        "message": "Non-demo retro feedback must remain untouched.",
                    }
                ]
            },
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
        "retro_entries": 12,
        "demo_retro_entries": 11,
    }

    with session_scope(session_factory=session_factory) as session:
        non_demo_task = session.get(Task, non_demo_task_id)
        assert non_demo_task is not None
        assert non_demo_task.external_task_id == "USER-TASK-1"
        non_demo_feedback_count = (
            session.query(AgentFeedbackEntry).filter(AgentFeedbackEntry.tag == "user-owned").count()
        )
        assert non_demo_feedback_count == 1


def test_seed_frontend_demo_makes_factory_snapshot_non_empty(session_factory) -> None:
    seed_frontend_demo(session_factory=session_factory)

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get("/factory")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["bottleneck"] == {"station": "execute", "wip_count": 6}
    stations = {station["name"]: station for station in payload["stations"]}
    assert set(stations) == {"fetch", "execute", "pr_feedback", "tracker_feedback", "deliver"}
    assert all(
        station["total_count"] > 0
        for name, station in stations.items()
        if name != "tracker_feedback"
    )
    assert all(
        station["wip_count"] > 0 for name, station in stations.items() if name != "tracker_feedback"
    )
    assert stations["execute"]["failed_count"] == 2
    assert stations["pr_feedback"]["failed_count"] == 1
    assert stations["tracker_feedback"]["total_count"] == 0


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


def test_seed_frontend_demo_makes_retro_tags_and_entries_available(session_factory) -> None:
    seed_frontend_demo(session_factory=session_factory)

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    client = app.test_client()
    tags_response = client.get("/retro/tags")

    assert tags_response.status_code == 200
    tags_payload = tags_response.get_json()
    assert tags_payload is not None
    tags = {tag["tag"]: tag for tag in tags_payload["tags"]}
    assert set(tags) == {
        "acceptance-missing",
        "slow-ci",
        "flaky-tests",
        "ambiguous-reqs",
        "docker-fail",
        "auth-error",
    }
    assert tags["acceptance-missing"]["count"] == 3
    assert tags["acceptance-missing"]["severity_counts"] == {
        "error": 1,
        "info": 1,
        "warning": 1,
    }
    assert tags["acceptance-missing"]["affected_tasks_count"] == 3
    assert tags["flaky-tests"]["severity_counts"] == {"error": 1, "warning": 1}

    entries_response = client.get("/retro/entries?tag=acceptance-missing")

    assert entries_response.status_code == 200
    entries_payload = entries_response.get_json()
    assert entries_payload is not None
    entries = entries_payload["entries"]
    assert len(entries) == 3
    assert {entry["severity"] for entry in entries} == {"error", "warning", "info"}
    assert {entry["message"] for entry in entries} == {
        "Implementation started before the acceptance criteria named the observable UI states.",
        "The task needed a tighter definition of done for API response behavior.",
        "Review feedback found assumptions that were not written in the task.",
    }
    assert any(
        entry["suggested_action"]
        == "Ask for explicit acceptance criteria before editing source files."
        for entry in entries
    )


def test_main_accepts_database_url_override_and_seeds_demo_data(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"

    exit_code = main(["--database-url", database_url])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert (
        "Frontend demo data is ready; tasks=27, token_usage=8, revenues=3, retro_entries=11"
    ) in stdout

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    assert _counts(session_factory) == {
        "tasks": 27,
        "demo_tasks": 27,
        "token_usage": 8,
        "revenue": 3,
        "retro_entries": 11,
        "demo_retro_entries": 11,
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
            "retro_entries": session.query(AgentFeedbackEntry).count(),
            "demo_retro_entries": session.query(AgentFeedbackEntry)
            .join(Task, Task.id == AgentFeedbackEntry.task_id)
            .filter(Task.external_task_id.like(f"{DEMO_EXTERNAL_ID_PREFIX}%"))
            .count(),
        }


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
