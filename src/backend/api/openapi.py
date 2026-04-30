from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from backend.schemas import TrackerTaskCreatePayload
from backend.task_constants import TaskStatus, TaskType


def build_openapi_schema() -> dict[str, Any]:
    return deepcopy(_cached_openapi_schema())


@lru_cache(maxsize=1)
def _cached_openapi_schema() -> dict[str, Any]:
    components = _build_components(TrackerTaskCreatePayload)
    components["schemas"].update(
        {
            "ErrorResponse": _object_schema(
                required=["error"],
                properties={
                    "error": {"type": "string"},
                    "details": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                },
            ),
            "HealthResponse": _object_schema(
                required=["status"],
                properties={"status": {"type": "string", "const": "ok"}},
            ),
            "IntakeTaskCreatedResponse": _object_schema(
                required=["external_id"],
                properties={"external_id": {"type": "string"}},
            ),
            "AgentPrompt": _agent_prompt_schema(),
            "AgentPromptResponse": _object_schema(
                required=["prompt"],
                properties={"prompt": {"$ref": "#/components/schemas/AgentPrompt"}},
            ),
            "AgentPromptsListResponse": _object_schema(
                required=["prompts"],
                properties={
                    "prompts": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/AgentPrompt"},
                    }
                },
            ),
            "PromptUpdatePayload": _object_schema(
                required=["content"],
                properties={"content": {"type": "string"}},
            ),
            "Task": _task_schema(),
            "TaskResponse": _object_schema(
                required=["task"],
                properties={"task": {"$ref": "#/components/schemas/Task"}},
            ),
            "TasksListResponse": _object_schema(
                required=["tasks"],
                properties={
                    "tasks": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Task"},
                    }
                },
            ),
            "StatsResponse": _stats_schema(),
            "FactoryResponse": _factory_schema(),
            "EconomicsSnapshotResponse": _economics_snapshot_schema(),
            "MockRevenuePayload": _mock_revenue_payload_schema(),
            "MockRevenueResponse": _mock_revenue_response_schema(),
            "RevenueUpsertPayload": _revenue_upsert_payload_schema(),
            "TaskRevenue": _task_revenue_schema(),
            "TaskRevenueResponse": _object_schema(
                required=["revenue"],
                properties={"revenue": {"$ref": "#/components/schemas/TaskRevenue"}},
            ),
        }
    )

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Heavy Lifting API",
            "version": "0.1.0",
            "description": "REST API for the Heavy Lifting backend orchestrator.",
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Check API health",
                    "operationId": "getHealth",
                    "tags": ["system"],
                    "responses": {
                        "200": _json_response("API is healthy", "HealthResponse"),
                    },
                }
            },
            "/stats": {
                "get": {
                    "summary": "Get task and token usage statistics",
                    "operationId": "getStats",
                    "tags": ["stats"],
                    "responses": {
                        "200": _json_response("Task and token usage aggregates", "StatsResponse"),
                    },
                }
            },
            "/factory": {
                "get": {
                    "summary": "Get operational factory station metrics",
                    "operationId": "getFactory",
                    "tags": ["stats"],
                    "responses": {
                        "200": _json_response(
                            "Factory station aggregates",
                            "FactoryResponse",
                        ),
                    },
                }
            },
            "/economics": {
                "get": {
                    "summary": "Get closed-root economics snapshot",
                    "operationId": "getEconomics",
                    "tags": ["economics"],
                    "parameters": [
                        {
                            "name": "from",
                            "in": "query",
                            "required": False,
                            "description": (
                                "Inclusive lower close-time bound. Defaults to 30 days before "
                                "`to` when omitted."
                            ),
                            "schema": {"type": "string", "format": "date-time"},
                        },
                        {
                            "name": "to",
                            "in": "query",
                            "required": False,
                            "description": (
                                "Inclusive upper close-time bound. Defaults to request time "
                                "when omitted."
                            ),
                            "schema": {"type": "string", "format": "date-time"},
                        },
                        {
                            "name": "bucket",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["day", "week", "month"],
                                "default": "day",
                            },
                        },
                    ],
                    "responses": {
                        "200": _json_response(
                            "Closed-root economics snapshot",
                            "EconomicsSnapshotResponse",
                        ),
                        "400": _json_response("Query validation failed", "ErrorResponse"),
                    },
                }
            },
            "/economics/mock-revenue": {
                "post": {
                    "summary": "Generate deterministic mock revenue for closed roots",
                    "operationId": "generateMockRevenue",
                    "tags": ["economics"],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/MockRevenuePayload"}
                            }
                        },
                    },
                    "responses": {
                        "200": _json_response(
                            "Mock revenue generation result",
                            "MockRevenueResponse",
                        ),
                        "400": _json_response("Payload validation failed", "ErrorResponse"),
                    },
                }
            },
            "/economics/revenue/{root_task_id}": {
                "put": {
                    "summary": "Create or update manual revenue for a root task",
                    "operationId": "upsertRevenue",
                    "tags": ["economics"],
                    "parameters": [
                        {
                            "name": "root_task_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/RevenueUpsertPayload"
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": _json_response("Stored task revenue", "TaskRevenueResponse"),
                        "400": _json_response("Payload validation failed", "ErrorResponse"),
                        "404": _json_response("Root task was not found", "ErrorResponse"),
                    },
                }
            },
            "/prompts": {
                "get": {
                    "summary": "List stored agent prompts",
                    "operationId": "listPrompts",
                    "tags": ["prompts"],
                    "responses": {
                        "200": _json_response(
                            "List of stored agent prompts",
                            "AgentPromptsListResponse",
                        ),
                    },
                }
            },
            "/prompts/{prompt_key}": {
                "get": {
                    "summary": "Get a stored agent prompt",
                    "operationId": "getPrompt",
                    "tags": ["prompts"],
                    "parameters": [_prompt_key_parameter()],
                    "responses": {
                        "200": _json_response("Stored agent prompt", "AgentPromptResponse"),
                        "404": _json_response("Prompt was not found", "ErrorResponse"),
                    },
                },
                "patch": {
                    "summary": "Update stored agent prompt content",
                    "operationId": "updatePrompt",
                    "tags": ["prompts"],
                    "parameters": [_prompt_key_parameter()],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PromptUpdatePayload"}
                            }
                        },
                    },
                    "responses": {
                        "200": _json_response("Updated agent prompt", "AgentPromptResponse"),
                        "400": _json_response("Payload validation failed", "ErrorResponse"),
                        "404": _json_response("Prompt was not found", "ErrorResponse"),
                    },
                },
            },
            "/tasks": {
                "get": {
                    "summary": "List local orchestration tasks",
                    "operationId": "listTasks",
                    "tags": ["tasks"],
                    "responses": {
                        "200": _json_response("List of local tasks", "TasksListResponse"),
                    },
                }
            },
            "/tasks/{task_id}": {
                "get": {
                    "summary": "Get a local orchestration task",
                    "operationId": "getTask",
                    "tags": ["tasks"],
                    "parameters": [
                        {
                            "name": "task_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                        }
                    ],
                    "responses": {
                        "200": _json_response("Local task", "TaskResponse"),
                        "404": _json_response("Task was not found", "ErrorResponse"),
                    },
                }
            },
            "/tasks/intake": {
                "post": {
                    "summary": "Create a tracker intake task",
                    "operationId": "intakeTask",
                    "tags": ["tasks"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/TrackerTaskCreatePayload"
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": _json_response(
                            "Tracker task was created",
                            "IntakeTaskCreatedResponse",
                        ),
                        "400": _json_response("Payload validation failed", "ErrorResponse"),
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "Get OpenAPI schema",
                    "operationId": "getOpenApiSchema",
                    "tags": ["system"],
                    "responses": {
                        "200": {
                            "description": "OpenAPI schema",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                    },
                }
            },
        },
        "components": components,
    }


def _build_components(*models: type[BaseModel]) -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for model in models:
        schema = _rewrite_pydantic_refs(model.model_json_schema())
        definitions = schema.pop("$defs", {})
        schemas.update(definitions)
        schemas[model.__name__] = schema

    return {"schemas": schemas}


def _rewrite_pydantic_refs(value: Any) -> Any:
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                rewritten[key] = item.replace("#/$defs/", "#/components/schemas/")
            else:
                rewritten[key] = _rewrite_pydantic_refs(item)
        return rewritten

    if isinstance(value, list):
        return [_rewrite_pydantic_refs(item) for item in value]

    return value


def _json_response(description: str, schema_name: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{schema_name}"},
            }
        },
    }


def _object_schema(
    *,
    required: list[str],
    properties: dict[str, Any],
    additional_properties: bool | dict[str, Any] = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": additional_properties,
    }


def _prompt_key_parameter() -> dict[str, Any]:
    return {
        "name": "prompt_key",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "minLength": 1},
    }


def _agent_prompt_schema() -> dict[str, Any]:
    return _object_schema(
        required=[
            "id",
            "prompt_key",
            "source_path",
            "content",
            "created_at",
            "updated_at",
        ],
        properties={
            "id": {"type": "integer"},
            "prompt_key": {"type": "string"},
            "source_path": {"type": "string"},
            "content": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    )


def _task_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    nullable_object = {"type": ["object", "null"], "additionalProperties": True}

    return _object_schema(
        required=[
            "id",
            "root_id",
            "parent_id",
            "task_type",
            "status",
            "tracker_name",
            "external_task_id",
            "external_parent_id",
            "repo_url",
            "repo_ref",
            "workspace_key",
            "branch_name",
            "pr_external_id",
            "pr_url",
            "role",
            "context",
            "input_payload",
            "result_payload",
            "error",
            "attempt",
            "created_at",
            "updated_at",
        ],
        properties={
            "id": {"type": "integer"},
            "root_id": nullable_integer,
            "parent_id": nullable_integer,
            "task_type": {"type": "string", "enum": _enum_values(TaskType)},
            "status": {"type": "string", "enum": _enum_values(TaskStatus)},
            "tracker_name": nullable_string,
            "external_task_id": nullable_string,
            "external_parent_id": nullable_string,
            "repo_url": nullable_string,
            "repo_ref": nullable_string,
            "workspace_key": nullable_string,
            "branch_name": nullable_string,
            "pr_external_id": nullable_string,
            "pr_url": nullable_string,
            "role": nullable_string,
            "context": nullable_object,
            "input_payload": nullable_object,
            "result_payload": nullable_object,
            "error": nullable_string,
            "attempt": {"type": "integer"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    )


def _stats_schema() -> dict[str, Any]:
    token_bucket = _object_schema(
        required=["input", "output", "cached", "total"],
        properties={
            "input": {"type": "integer", "minimum": 0},
            "output": {"type": "integer", "minimum": 0},
            "cached": {"type": "integer", "minimum": 0},
            "total": {"type": "integer", "minimum": 0},
        },
    )
    aggregate_bucket = _object_schema(
        required=["entries_count", "tokens", "cost_usd"],
        properties={
            "entries_count": {"type": "integer", "minimum": 0},
            "tokens": deepcopy(token_bucket),
            "cost_usd": {"type": "string"},
        },
    )

    return _object_schema(
        required=["generated_at", "tasks", "token_usage"],
        properties={
            "generated_at": {"type": "string", "format": "date-time"},
            "tasks": _object_schema(
                required=["total", "by_status", "by_type", "by_type_and_status"],
                properties={
                    "total": {"type": "integer", "minimum": 0},
                    "by_status": {
                        "type": "object",
                        "additionalProperties": {"type": "integer", "minimum": 0},
                    },
                    "by_type": {
                        "type": "object",
                        "additionalProperties": {"type": "integer", "minimum": 0},
                    },
                    "by_type_and_status": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": {"type": "integer", "minimum": 0},
                        },
                    },
                },
            ),
            "token_usage": _object_schema(
                required=[
                    "entries_count",
                    "estimated_entries_count",
                    "tokens",
                    "cost_usd",
                    "by_provider",
                    "by_model",
                    "by_task_type",
                ],
                properties={
                    "entries_count": {"type": "integer", "minimum": 0},
                    "estimated_entries_count": {"type": "integer", "minimum": 0},
                    "tokens": token_bucket,
                    "cost_usd": _object_schema(
                        required=["total", "estimated_share"],
                        properties={
                            "total": {"type": "string"},
                            "estimated_share": {"type": "string"},
                        },
                    ),
                    "by_provider": {
                        "type": "object",
                        "additionalProperties": aggregate_bucket,
                    },
                    "by_model": {
                        "type": "object",
                        "additionalProperties": aggregate_bucket,
                    },
                    "by_task_type": {
                        "type": "object",
                        "additionalProperties": aggregate_bucket,
                    },
                },
            ),
        },
    )


def _factory_schema() -> dict[str, Any]:
    nullable_age = {"type": ["integer", "null"], "minimum": 0}
    nullable_bottleneck = {
        "anyOf": [
            _object_schema(
                required=["station", "wip_count"],
                properties={
                    "station": {
                        "type": "string",
                        "enum": ["fetch", "execute", "pr_feedback", "deliver"],
                    },
                    "wip_count": {"type": "integer", "minimum": 1},
                },
            ),
            {"type": "null"},
        ]
    }

    station_schema = _object_schema(
        required=[
            "name",
            "counts_by_status",
            "total_count",
            "wip_count",
            "queue_count",
            "active_count",
            "failed_count",
            "oldest_queue_age_seconds",
            "oldest_active_age_seconds",
        ],
        properties={
            "name": {
                "type": "string",
                "enum": ["fetch", "execute", "pr_feedback", "deliver"],
            },
            "counts_by_status": {
                "type": "object",
                "required": _enum_values(TaskStatus),
                "properties": {
                    status: {"type": "integer", "minimum": 0}
                    for status in _enum_values(TaskStatus)
                },
                "additionalProperties": False,
            },
            "total_count": {"type": "integer", "minimum": 0},
            "wip_count": {"type": "integer", "minimum": 0},
            "queue_count": {"type": "integer", "minimum": 0},
            "active_count": {"type": "integer", "minimum": 0},
            "failed_count": {"type": "integer", "minimum": 0},
            "oldest_queue_age_seconds": nullable_age,
            "oldest_active_age_seconds": nullable_age,
        },
    )

    return _object_schema(
        required=["generated_at", "stations", "bottleneck", "data_gaps"],
        properties={
            "generated_at": {"type": "string", "format": "date-time"},
            "stations": {
                "type": "array",
                "items": station_schema,
                "minItems": 4,
                "maxItems": 4,
            },
            "bottleneck": nullable_bottleneck,
            "data_gaps": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "transition_history",
                        "throughput_per_hour",
                        "worker_capacity",
                        "rework_loops",
                        "business_task_kind",
                    ],
                },
            },
        },
    )


def _economics_snapshot_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    money_string = {"type": "string", "pattern": r"^-?[0-9]+\.[0-9]{6}$"}
    nullable_money_string = {"type": ["string", "null"], "pattern": r"^-?[0-9]+\.[0-9]{6}$"}

    totals_schema = _object_schema(
        required=[
            "closed_roots_count",
            "monetized_roots_count",
            "missing_revenue_count",
            "revenue_usd",
            "token_cost_usd",
            "profit_usd",
        ],
        properties={
            "closed_roots_count": {"type": "integer", "minimum": 0},
            "monetized_roots_count": {"type": "integer", "minimum": 0},
            "missing_revenue_count": {"type": "integer", "minimum": 0},
            "revenue_usd": money_string,
            "token_cost_usd": money_string,
            "profit_usd": money_string,
        },
    )
    series_item_schema = _object_schema(
        required=[
            "bucket",
            "closed_roots_count",
            "monetized_roots_count",
            "missing_revenue_count",
            "revenue_usd",
            "token_cost_usd",
            "profit_usd",
        ],
        properties={
            "bucket": {"type": "string"},
            "closed_roots_count": {"type": "integer", "minimum": 0},
            "monetized_roots_count": {"type": "integer", "minimum": 0},
            "missing_revenue_count": {"type": "integer", "minimum": 0},
            "revenue_usd": money_string,
            "token_cost_usd": money_string,
            "profit_usd": money_string,
        },
    )
    root_schema = _object_schema(
        required=[
            "root_task_id",
            "external_task_id",
            "tracker_name",
            "closed_at",
            "revenue_usd",
            "token_cost_usd",
            "profit_usd",
            "revenue_source",
            "revenue_confidence",
        ],
        properties={
            "root_task_id": {"type": "integer", "minimum": 1},
            "external_task_id": nullable_string,
            "tracker_name": nullable_string,
            "closed_at": {"type": "string", "format": "date-time"},
            "revenue_usd": nullable_money_string,
            "token_cost_usd": money_string,
            "profit_usd": nullable_money_string,
            "revenue_source": {
                "type": ["string", "null"],
                "enum": ["mock", "expert", "external", None],
            },
            "revenue_confidence": {
                "type": ["string", "null"],
                "enum": ["estimated", "actual", None],
            },
        },
    )

    return _object_schema(
        required=["generated_at", "period", "totals", "series", "roots", "data_gaps"],
        properties={
            "generated_at": {"type": "string", "format": "date-time"},
            "period": _object_schema(
                required=["from", "to", "bucket"],
                properties={
                    "from": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Applied inclusive lower close-time bound.",
                    },
                    "to": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Applied inclusive upper close-time bound.",
                    },
                    "bucket": {"type": "string", "enum": ["day", "week", "month"]},
                },
            ),
            "totals": totals_schema,
            "series": {"type": "array", "items": series_item_schema},
            "roots": {"type": "array", "items": root_schema},
            "data_gaps": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "infra_cost",
                        "runner_hours",
                        "external_accounting_import",
                        "retry_waste",
                    ],
                },
            },
        },
    )


def _mock_revenue_payload_schema() -> dict[str, Any]:
    return _object_schema(
        required=[],
        properties={
            "min_usd": {"type": ["string", "number"], "default": "100"},
            "max_usd": {"type": ["string", "number"], "default": "2500"},
            "seed": {"type": "string", "default": "heavy-lifting-economics-v1"},
            "overwrite": {"type": "boolean", "default": False},
        },
    )


def _mock_revenue_response_schema() -> dict[str, Any]:
    id_array = {"type": "array", "items": {"type": "integer", "minimum": 1}}
    return _object_schema(
        required=[
            "created_count",
            "updated_count",
            "created_root_task_ids",
            "updated_root_task_ids",
        ],
        properties={
            "created_count": {"type": "integer", "minimum": 0},
            "updated_count": {"type": "integer", "minimum": 0},
            "created_root_task_ids": id_array,
            "updated_root_task_ids": id_array,
        },
    )


def _revenue_upsert_payload_schema() -> dict[str, Any]:
    return _object_schema(
        required=["amount_usd", "source", "confidence"],
        properties={
            "amount_usd": {"type": ["string", "number"]},
            "source": {"type": "string", "enum": ["expert", "external"]},
            "confidence": {"type": "string", "enum": ["estimated", "actual"]},
            "metadata": {"type": ["object", "null"], "additionalProperties": True},
        },
    )


def _task_revenue_schema() -> dict[str, Any]:
    return _object_schema(
        required=[
            "id",
            "root_task_id",
            "amount_usd",
            "source",
            "confidence",
            "metadata",
            "created_at",
            "updated_at",
        ],
        properties={
            "id": {"type": "integer", "minimum": 1},
            "root_task_id": {"type": "integer", "minimum": 1},
            "amount_usd": {"type": "string"},
            "source": {"type": "string", "enum": ["mock", "expert", "external"]},
            "confidence": {"type": "string", "enum": ["estimated", "actual"]},
            "metadata": {"type": ["object", "null"], "additionalProperties": True},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    )


def _enum_values(enum_type: type[TaskStatus] | type[TaskType]) -> list[str]:
    return [item.value for item in enum_type]


__all__ = ["build_openapi_schema"]
