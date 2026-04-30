from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
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


def test_get_retro_entries_returns_entries_with_filters(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        execute_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, status=TaskStatus.DONE)
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                status=TaskStatus.DONE,
            )
        )

        service = RetroService(session)
        service.record_agent_feedback(
            task=execute_task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": "missing-tests",
                        "category": "testing",
                        "severity": "warning",
                        "message": "Needed extra regression coverage.",
                        "suggested_action": "Add focused regression tests.",
                        "metadata": {"phase": "execute"},
                    }
                ]
            },
        )
        service.record_agent_feedback(
            task=feedback_task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": "review-loop",
                        "severity": "info",
                        "message": "PR feedback required a small follow-up.",
                    }
                ]
            },
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get(
        "/retro/entries?task_type=execute&tag=missing-tests&severity=warning&source=agent"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["entries"] == [
        {
            "id": 1,
            "task_id": execute_task.id,
            "root_id": execute_task.id,
            "task_type": "execute",
            "role": None,
            "attempt": 0,
            "source": "agent",
            "category": "testing",
            "tag": "missing-tests",
            "severity": "warning",
            "message": "Needed extra regression coverage.",
            "suggested_action": "Add focused regression tests.",
            "metadata": {"phase": "execute"},
            "created_at": payload["entries"][0]["created_at"],
        }
    ]


def test_get_retro_tags_returns_tag_aggregates(session_factory) -> None:
    now = datetime.now(UTC)
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        first_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, status=TaskStatus.DONE)
        )
        second_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.EXECUTE, status=TaskStatus.DONE)
        )

        service = RetroService(session)
        entries = service.record_agent_feedback(
            task=first_task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": "missing-tests",
                        "severity": "warning",
                        "message": "First missing tests signal.",
                    },
                    {
                        "tag": "missing-tests",
                        "severity": "warning",
                        "message": "Second missing tests signal.",
                    },
                    {
                        "tag": "slow-checks",
                        "severity": "info",
                        "message": "Checks were slower than expected.",
                    },
                ]
            },
        )
        more_entries = service.record_agent_feedback(
            task=second_task,
            result_metadata={
                "agent_retro": [
                    {
                        "tag": "missing-tests",
                        "severity": "error",
                        "message": "Missing tests blocked confidence.",
                    },
                ]
            },
        )

        entries[0].created_at = now - timedelta(days=2)
        entries[1].created_at = now - timedelta(days=1)
        entries[2].created_at = now - timedelta(hours=2)
        more_entries[0].created_at = now

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get("/retro/tags")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["tags"] == [
        {
            "tag": "missing-tests",
            "count": 3,
            "severity_counts": {"error": 1, "warning": 2},
            "first_seen": (now - timedelta(days=2)).isoformat(),
            "last_seen": now.isoformat(),
            "affected_tasks_count": 2,
        },
        {
            "tag": "slow-checks",
            "count": 1,
            "severity_counts": {"info": 1},
            "first_seen": (now - timedelta(hours=2)).isoformat(),
            "last_seen": (now - timedelta(hours=2)).isoformat(),
            "affected_tasks_count": 1,
        },
    ]


def test_get_retro_entries_rejects_invalid_filters(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/retro/entries?task_type=unknown&limit=0")

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid task_type filter"}


def test_get_retro_entries_rejects_invalid_source(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/retro/entries?source=bogus")

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid source filter"}


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
