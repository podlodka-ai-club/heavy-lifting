from __future__ import annotations

from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.api.openapi import build_openapi_schema
from backend.composition import RuntimeContainer
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings


def test_get_openapi_json_describes_public_api() -> None:
    app = create_app(runtime=_runtime())

    response = app.test_client().get("/openapi.json")

    assert response.status_code == 200
    schema = response.get_json()
    assert schema is not None
    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["title"] == "Heavy Lifting API"
    assert set(schema["paths"]) == {
        "/factory",
        "/health",
        "/openapi.json",
        "/prompts",
        "/prompts/{prompt_key}",
        "/stats",
        "/tasks",
        "/tasks/{task_id}",
        "/tasks/intake",
    }


def test_openapi_json_uses_pydantic_contract_for_intake_payload() -> None:
    app = create_app(runtime=_runtime())

    schema = app.test_client().get("/openapi.json").get_json()

    assert schema is not None
    intake_operation = schema["paths"]["/tasks/intake"]["post"]
    assert intake_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TrackerTaskCreatePayload"
    }
    components = schema["components"]["schemas"]
    assert "TrackerTaskCreatePayload" in components
    assert "TaskContext" in components
    assert "TaskInputPayload" in components
    assert components["TrackerTaskCreatePayload"]["properties"]["context"] == {
        "$ref": "#/components/schemas/TaskContext"
    }


def test_openapi_json_describes_task_and_stats_responses() -> None:
    app = create_app(runtime=_runtime())

    schema = app.test_client().get("/openapi.json").get_json()

    assert schema is not None
    components = schema["components"]["schemas"]
    assert components["Task"]["properties"]["status"]["enum"] == [
        "new",
        "processing",
        "done",
        "failed",
    ]
    assert components["Task"]["properties"]["task_type"]["enum"] == [
        "fetch",
        "execute",
        "deliver",
        "pr_feedback",
    ]
    assert schema["paths"]["/stats"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/StatsResponse"}


def test_openapi_json_describes_factory_response() -> None:
    app = create_app(runtime=_runtime())

    schema = app.test_client().get("/openapi.json").get_json()

    assert schema is not None
    assert schema["paths"]["/factory"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/FactoryResponse"}
    factory_schema = schema["components"]["schemas"]["FactoryResponse"]
    assert factory_schema["required"] == [
        "generated_at",
        "stations",
        "bottleneck",
        "data_gaps",
    ]
    station_schema = factory_schema["properties"]["stations"]["items"]
    assert station_schema["properties"]["name"]["enum"] == [
        "fetch",
        "execute",
        "pr_feedback",
        "deliver",
    ]
    assert station_schema["properties"]["counts_by_status"]["required"] == [
        "new",
        "processing",
        "done",
        "failed",
    ]
    assert factory_schema["properties"]["data_gaps"]["items"]["enum"] == [
        "transition_history",
        "throughput_per_hour",
        "worker_capacity",
        "rework_loops",
        "business_task_kind",
    ]


def test_openapi_json_describes_prompt_endpoints() -> None:
    app = create_app(runtime=_runtime())

    schema = app.test_client().get("/openapi.json").get_json()

    assert schema is not None
    components = schema["components"]["schemas"]
    assert components["AgentPrompt"]["required"] == [
        "id",
        "prompt_key",
        "source_path",
        "content",
        "created_at",
        "updated_at",
    ]
    assert schema["paths"]["/prompts"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/AgentPromptsListResponse"}
    prompt_path = schema["paths"]["/prompts/{prompt_key}"]
    assert set(prompt_path) == {"get", "patch"}
    assert prompt_path["patch"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PromptUpdatePayload"
    }


def test_build_openapi_schema_returns_isolated_copy() -> None:
    first_schema = build_openapi_schema()

    first_schema["info"]["title"] = "mutated"

    assert build_openapi_schema()["info"]["title"] == "Heavy Lifting API"


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )
