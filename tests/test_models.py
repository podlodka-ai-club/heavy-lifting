from sqlalchemy import inspect

from backend.db import build_engine
from backend.models import (
    TASK_STATUS_VALUES,
    TASK_TYPE_VALUES,
    Base,
    Task,
    TaskStatus,
    TaskType,
)


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
