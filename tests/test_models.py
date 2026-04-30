from sqlalchemy import inspect
from sqlalchemy.orm import configure_mappers

from backend.db import build_engine
from backend.models import (
    AgentFeedbackEntry,
    AgentPrompt,
    ApplicationSetting,
    Base,
    Task,
    TokenUsage,
)
from backend.task_constants import TASK_STATUS_VALUES, TASK_TYPE_VALUES, TaskStatus, TaskType


def test_models_reuse_shared_task_constants() -> None:
    from backend import models

    assert models.TaskType is TaskType
    assert models.TaskStatus is TaskStatus
    assert models.TASK_TYPE_VALUES is TASK_TYPE_VALUES
    assert models.TASK_STATUS_VALUES is TASK_STATUS_VALUES


def test_task_enum_values_match_mvp_spec() -> None:
    assert TASK_TYPE_VALUES == ("fetch", "execute", "deliver", "pr_feedback")
    assert TASK_STATUS_VALUES == ("new", "processing", "done", "failed")
    assert [task_type.value for task_type in TaskType] == list(TASK_TYPE_VALUES)
    assert [status.value for status in TaskStatus] == list(TASK_STATUS_VALUES)


def test_task_table_contains_mvp_columns(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns(Task.__tablename__)}

    assert set(columns) == {
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
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["task_type"]["nullable"] is False
    assert columns["status"]["nullable"] is False
    assert columns["attempt"]["nullable"] is False


def test_task_table_has_expected_indexes_and_foreign_keys(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {
        index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("tasks")
    }
    foreign_keys = inspector.get_foreign_keys("tasks")

    assert indexes["ix_tasks_status_task_type_updated_at"] == (
        "status",
        "task_type",
        "updated_at",
    )
    assert indexes["ix_tasks_root_id"] == ("root_id",)
    assert indexes["ix_tasks_parent_id"] == ("parent_id",)
    assert indexes["ix_tasks_pr_external_id"] == ("pr_external_id",)
    assert len(foreign_keys) == 2
    assert {fk["constrained_columns"][0] for fk in foreign_keys} == {"root_id", "parent_id"}
    assert {fk["referred_columns"][0] for fk in foreign_keys} == {"id"}


def test_token_usage_table_contains_mvp_columns(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    columns = {
        column["name"]: column for column in inspect(engine).get_columns(TokenUsage.__tablename__)
    }

    assert set(columns) == {
        "id",
        "task_id",
        "model",
        "provider",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "estimated",
        "cost_usd",
        "created_at",
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["task_id"]["nullable"] is False
    assert columns["model"]["nullable"] is False
    assert columns["provider"]["nullable"] is False
    assert columns["input_tokens"]["nullable"] is False
    assert columns["output_tokens"]["nullable"] is False
    assert columns["cached_tokens"]["nullable"] is False
    assert columns["estimated"]["nullable"] is False
    assert columns["cost_usd"]["nullable"] is False


def test_token_usage_table_has_expected_indexes_and_foreign_key(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(TokenUsage.__tablename__)
    }
    foreign_keys = inspector.get_foreign_keys(TokenUsage.__tablename__)

    assert indexes["ix_token_usage_task_id"] == ("task_id",)
    assert indexes["ix_token_usage_provider_model_created_at"] == (
        "provider",
        "model",
        "created_at",
    )
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["task_id"]
    assert foreign_keys[0]["referred_table"] == "tasks"
    assert foreign_keys[0]["referred_columns"] == ["id"]


def test_agent_prompts_table_contains_default_prompt_columns(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    columns = {
        column["name"]: column for column in inspect(engine).get_columns(AgentPrompt.__tablename__)
    }

    assert set(columns) == {
        "id",
        "prompt_key",
        "source_path",
        "content",
        "created_at",
        "updated_at",
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["prompt_key"]["nullable"] is False
    assert columns["source_path"]["nullable"] is False
    assert columns["content"]["nullable"] is False
    assert columns["created_at"]["nullable"] is False
    assert columns["updated_at"]["nullable"] is False


def test_agent_prompts_table_has_prompt_key_index_and_unique_constraint(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(AgentPrompt.__tablename__)
    }
    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(AgentPrompt.__tablename__)
    }

    assert indexes["ix_agent_prompts_prompt_key"] == ("prompt_key",)
    assert unique_constraints["uq_agent_prompts_prompt_key"] == ("prompt_key",)


def test_application_settings_table_contains_default_columns(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(ApplicationSetting.__tablename__)
    }

    assert set(columns) == {
        "id",
        "setting_key",
        "env_var",
        "value_type",
        "value",
        "default_value",
        "description",
        "display_order",
        "created_at",
        "updated_at",
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["setting_key"]["nullable"] is False
    assert columns["env_var"]["nullable"] is False
    assert columns["value_type"]["nullable"] is False
    assert columns["value"]["nullable"] is False
    assert columns["default_value"]["nullable"] is False
    assert columns["description"]["nullable"] is False
    assert columns["display_order"]["nullable"] is False


def test_application_settings_table_has_indexes_and_unique_constraint(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(ApplicationSetting.__tablename__)
    }
    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(ApplicationSetting.__tablename__)
    }
    check_constraints = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints(ApplicationSetting.__tablename__)
    }

    assert indexes["ix_application_settings_setting_key"] == ("setting_key",)
    assert indexes["ix_application_settings_display_order"] == ("display_order",)
    assert unique_constraints["uq_application_settings_setting_key"] == ("setting_key",)
    assert check_constraints["ck_application_settings_value_type"] == (
        "value_type IN ('int', 'string')"
    )


def test_agent_feedback_entries_table_contains_retro_columns(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(AgentFeedbackEntry.__tablename__)
    }

    assert set(columns) == {
        "id",
        "task_id",
        "root_id",
        "task_type",
        "role",
        "attempt",
        "source",
        "category",
        "tag",
        "severity",
        "message",
        "suggested_action",
        "metadata",
        "created_at",
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["task_id"]["nullable"] is False
    assert columns["root_id"]["nullable"] is False
    assert columns["task_type"]["nullable"] is False
    assert columns["role"]["nullable"] is True
    assert columns["attempt"]["nullable"] is False
    assert columns["source"]["nullable"] is False
    assert columns["category"]["nullable"] is False
    assert columns["tag"]["nullable"] is False
    assert columns["severity"]["nullable"] is False
    assert columns["message"]["nullable"] is False
    assert columns["suggested_action"]["nullable"] is True


def test_agent_feedback_entries_table_has_indexes_and_foreign_key(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(AgentFeedbackEntry.__tablename__)
    }
    foreign_keys = inspector.get_foreign_keys(AgentFeedbackEntry.__tablename__)

    assert indexes["ix_agent_feedback_entries_task_id"] == ("task_id",)
    assert indexes["ix_agent_feedback_entries_tag_created_at"] == ("tag", "created_at")
    assert indexes["ix_agent_feedback_entries_task_type_created_at"] == (
        "task_type",
        "created_at",
    )
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["task_id"]
    assert foreign_keys[0]["referred_table"] == "tasks"
    assert foreign_keys[0]["referred_columns"] == ["id"]


def test_task_and_token_usage_relationships_are_linked() -> None:
    configure_mappers()

    task_relationship = inspect(Task).relationships["token_usage_entries"]
    token_usage_relationship = inspect(TokenUsage).relationships["task"]
    retro_relationship = inspect(Task).relationships["agent_feedback_entries"]
    retro_task_relationship = inspect(AgentFeedbackEntry).relationships["task"]

    assert task_relationship.mapper.class_ is TokenUsage
    assert task_relationship.back_populates == "task"
    assert token_usage_relationship.mapper.class_ is Task
    assert token_usage_relationship.back_populates == "token_usage_entries"
    assert retro_relationship.mapper.class_ is AgentFeedbackEntry
    assert retro_relationship.back_populates == "task"
    assert retro_task_relationship.mapper.class_ is Task
    assert retro_task_relationship.back_populates == "agent_feedback_entries"


def test_task_table_has_enum_check_constraints(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    constraints = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspect(engine).get_check_constraints("tasks")
    }

    assert constraints["task_type_enum"] == (
        "task_type IN ('fetch', 'execute', 'deliver', 'pr_feedback')"
    )
    assert constraints["task_status_enum"] == ("status IN ('new', 'processing', 'done', 'failed')")


def test_token_usage_table_has_non_negative_check_constraints(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)

    constraints = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspect(engine).get_check_constraints(TokenUsage.__tablename__)
    }

    assert constraints["ck_token_usage_input_tokens_non_negative"] == "input_tokens >= 0"
    assert constraints["ck_token_usage_output_tokens_non_negative"] == "output_tokens >= 0"
    assert constraints["ck_token_usage_cached_tokens_non_negative"] == "cached_tokens >= 0"
    assert constraints["ck_token_usage_cost_usd_non_negative"] == "cost_usd >= 0"
