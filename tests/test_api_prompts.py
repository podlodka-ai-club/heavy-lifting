from __future__ import annotations

from dataclasses import replace

import pytest

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import RuntimeContainer
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import AgentPrompt, Base
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_get_prompts_lists_stored_prompts_ordered_by_prompt_key(session_factory) -> None:
    dev_prompt, review_prompt = _seed_prompts(session_factory)
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/prompts")

    assert response.status_code == 200
    assert response.get_json() == {
        "prompts": [
            {
                "id": dev_prompt.id,
                "prompt_key": "dev",
                "source_path": "prompts/agents/dev.md",
                "content": "DEV prompt",
                "created_at": dev_prompt.created_at.isoformat(),
                "updated_at": dev_prompt.updated_at.isoformat(),
            },
            {
                "id": review_prompt.id,
                "prompt_key": "review",
                "source_path": "prompts/agents/review.md",
                "content": "REVIEW prompt",
                "created_at": review_prompt.created_at.isoformat(),
                "updated_at": review_prompt.updated_at.isoformat(),
            },
        ]
    }


def test_get_prompt_returns_stored_prompt_by_key(session_factory) -> None:
    dev_prompt, _ = _seed_prompts(session_factory)
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().get("/prompts/dev")

    assert response.status_code == 200
    assert response.get_json() == {
        "prompt": {
            "id": dev_prompt.id,
            "prompt_key": "dev",
            "source_path": "prompts/agents/dev.md",
            "content": "DEV prompt",
            "created_at": dev_prompt.created_at.isoformat(),
            "updated_at": dev_prompt.updated_at.isoformat(),
        }
    }


def test_patch_prompt_updates_content_by_key(session_factory) -> None:
    dev_prompt, _ = _seed_prompts(session_factory)
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch(
        "/prompts/dev",
        json={"content": "Updated DEV prompt"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["prompt"]["id"] == dev_prompt.id
    assert payload["prompt"]["prompt_key"] == "dev"
    assert payload["prompt"]["source_path"] == "prompts/agents/dev.md"
    assert payload["prompt"]["content"] == "Updated DEV prompt"

    with session_scope(session_factory=session_factory) as session:
        stored_prompt = (
            session.query(AgentPrompt).filter(AgentPrompt.prompt_key == "dev").one()
        )

    assert stored_prompt.content == "Updated DEV prompt"


def test_prompt_endpoints_return_json_404_for_missing_prompt(session_factory) -> None:
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    get_response = app.test_client().get("/prompts/missing")
    patch_response = app.test_client().patch(
        "/prompts/missing",
        json={"content": "Updated prompt"},
    )

    assert get_response.status_code == 404
    assert get_response.get_json() == {"error": "Prompt missing not found"}
    assert patch_response.status_code == 404
    assert patch_response.get_json() == {"error": "Prompt missing not found"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"content": None},
        {"content": 123},
    ],
)
def test_patch_prompt_returns_json_400_for_invalid_payload(session_factory, payload) -> None:
    _seed_prompts(session_factory)
    app = create_app(runtime=_runtime(), session_factory=session_factory)

    response = app.test_client().patch("/prompts/dev", json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid prompt update payload"}

    with session_scope(session_factory=session_factory) as session:
        stored_prompt = (
            session.query(AgentPrompt).filter(AgentPrompt.prompt_key == "dev").one()
        )

    assert stored_prompt.content == "DEV prompt"


def _seed_prompts(session_factory) -> tuple[AgentPrompt, AgentPrompt]:
    with session_scope(session_factory=session_factory) as session:
        dev_prompt = AgentPrompt(
            prompt_key="dev",
            source_path="prompts/agents/dev.md",
            content="DEV prompt",
        )
        review_prompt = AgentPrompt(
            prompt_key="review",
            source_path="prompts/agents/review.md",
            content="REVIEW prompt",
        )
        session.add_all([review_prompt, dev_prompt])

    return dev_prompt, review_prompt


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
