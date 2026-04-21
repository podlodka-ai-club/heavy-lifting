from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
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


def test_get_stats_returns_task_and_token_usage_aggregates(session_factory) -> None:
    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                status=TaskStatus.DONE,
                tracker_name="mock",
                external_task_id="TASK-31",
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                status=TaskStatus.DONE,
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.DELIVER,
                parent_id=execute_task.id,
                status=TaskStatus.NEW,
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                status=TaskStatus.FAILED,
            )
        )

        repository.record_token_usage(
            task_id=execute_task.id,
            usage=TokenUsageCreateParams(
                model="gpt-5.4",
                provider="openai",
                input_tokens=120,
                output_tokens=30,
                cached_tokens=10,
                cost_usd=Decimal("0.420000"),
            ),
        )
        repository.record_token_usage(
            task_id=feedback_task.id,
            usage=TokenUsageCreateParams(
                model="gpt-5.4-mini",
                provider="openai",
                input_tokens=40,
                output_tokens=15,
                cached_tokens=5,
                estimated=True,
                cost_usd=Decimal("0.050000"),
            ),
        )

    app = create_app(runtime=_runtime(), session_factory=session_factory)
    response = app.test_client().get("/stats")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["generated_at"]
    assert payload["tasks"] == {
        "total": 4,
        "by_status": {
            "new": 1,
            "processing": 0,
            "done": 2,
            "failed": 1,
        },
        "by_type": {
            "fetch": 1,
            "execute": 1,
            "deliver": 1,
            "pr_feedback": 1,
        },
        "by_type_and_status": {
            "fetch": {"new": 0, "processing": 0, "done": 1, "failed": 0},
            "execute": {"new": 0, "processing": 0, "done": 1, "failed": 0},
            "deliver": {"new": 1, "processing": 0, "done": 0, "failed": 0},
            "pr_feedback": {"new": 0, "processing": 0, "done": 0, "failed": 1},
        },
    }
    assert payload["token_usage"] == {
        "entries_count": 2,
        "estimated_entries_count": 1,
        "tokens": {
            "input": 160,
            "output": 45,
            "cached": 15,
            "total": 220,
        },
        "cost_usd": {
            "total": "0.470000",
            "estimated_share": "0.050000",
        },
        "by_provider": {
            "openai": {
                "entries_count": 2,
                "tokens": {
                    "input": 160,
                    "output": 45,
                    "cached": 15,
                    "total": 220,
                },
                "cost_usd": "0.470000",
            }
        },
        "by_model": {
            "gpt-5.4": {
                "entries_count": 1,
                "tokens": {
                    "input": 120,
                    "output": 30,
                    "cached": 10,
                    "total": 160,
                },
                "cost_usd": "0.420000",
            },
            "gpt-5.4-mini": {
                "entries_count": 1,
                "tokens": {
                    "input": 40,
                    "output": 15,
                    "cached": 5,
                    "total": 60,
                },
                "cost_usd": "0.050000",
            },
        },
        "by_task_type": {
            "fetch": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
            "execute": {
                "entries_count": 1,
                "tokens": {
                    "input": 120,
                    "output": 30,
                    "cached": 10,
                    "total": 160,
                },
                "cost_usd": "0.420000",
            },
            "deliver": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
            "pr_feedback": {
                "entries_count": 1,
                "tokens": {
                    "input": 40,
                    "output": 15,
                    "cached": 5,
                    "total": 60,
                },
                "cost_usd": "0.050000",
            },
        },
    }


def test_get_stats_returns_zeroed_breakdowns_for_empty_database(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/stats")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["tasks"]["total"] == 0
    assert payload["tasks"]["by_status"] == {
        "new": 0,
        "processing": 0,
        "done": 0,
        "failed": 0,
    }
    assert payload["token_usage"] == {
        "entries_count": 0,
        "estimated_entries_count": 0,
        "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
        "cost_usd": {"total": "0.000000", "estimated_share": "0.000000"},
        "by_provider": {},
        "by_model": {},
        "by_task_type": {
            "fetch": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
            "execute": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
            "deliver": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
            "pr_feedback": {
                "entries_count": 0,
                "tokens": {"input": 0, "output": 0, "cached": 0, "total": 0},
                "cost_usd": "0.000000",
            },
        },
    }


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
