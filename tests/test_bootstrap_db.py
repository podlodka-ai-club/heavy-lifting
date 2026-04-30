from sqlalchemy import inspect
from sqlalchemy.orm import Session

from backend.bootstrap_db import (
    DEFAULT_AGENT_PROMPTS_DIR,
    MVP_SCHEMA_TABLES,
    bootstrap_schema,
    main,
)
from backend.db import build_engine
from backend.models import AgentPrompt, ApplicationSetting


def test_bootstrap_schema_creates_mvp_tables(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    created_tables = bootstrap_schema(database_url)
    table_names = set(inspect(build_engine(database_url)).get_table_names())

    assert created_tables == MVP_SCHEMA_TABLES
    assert table_names == set(MVP_SCHEMA_TABLES)


def test_bootstrap_schema_is_idempotent(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    bootstrap_schema(database_url)
    created_tables = bootstrap_schema(database_url)

    assert created_tables == ()


def test_bootstrap_schema_seeds_default_agent_prompts(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    bootstrap_schema(database_url)

    engine = build_engine(database_url)
    expected_prompt_paths = sorted(DEFAULT_AGENT_PROMPTS_DIR.glob("*.md"))
    with Session(engine) as session:
        prompts = session.query(AgentPrompt).order_by(AgentPrompt.prompt_key).all()

    assert [prompt.prompt_key for prompt in prompts] == [
        prompt_path.stem for prompt_path in expected_prompt_paths
    ]
    assert [prompt.source_path for prompt in prompts] == [
        f"prompts/agents/{prompt_path.name}" for prompt_path in expected_prompt_paths
    ]
    assert [prompt.content for prompt in prompts] == [
        prompt_path.read_text(encoding="utf-8") for prompt_path in expected_prompt_paths
    ]


def test_bootstrap_schema_preserves_existing_agent_prompt_content(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"
    expected_prompt_paths = sorted(DEFAULT_AGENT_PROMPTS_DIR.glob("*.md"))

    bootstrap_schema(database_url)

    first_prompt_path = expected_prompt_paths[0]
    engine = build_engine(database_url)
    with Session(engine) as session:
        prompt = (
            session.query(AgentPrompt)
            .filter(AgentPrompt.prompt_key == first_prompt_path.stem)
            .one()
        )
        prompt.content = "custom user-edited prompt"
        prompt.source_path = "outdated/path.md"
        session.commit()

    bootstrap_schema(database_url)

    with Session(engine) as session:
        prompt_count = session.query(AgentPrompt).count()
        prompt = (
            session.query(AgentPrompt)
            .filter(AgentPrompt.prompt_key == first_prompt_path.stem)
            .one()
        )

    assert prompt_count == len(expected_prompt_paths)
    assert prompt.content == "custom user-edited prompt"
    assert prompt.source_path == f"prompts/agents/{first_prompt_path.name}"


def test_bootstrap_schema_seeds_default_application_settings(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    bootstrap_schema(database_url)

    engine = build_engine(database_url)
    with Session(engine) as session:
        settings = (
            session.query(ApplicationSetting)
            .order_by(ApplicationSetting.display_order)
            .all()
        )

    assert [setting.setting_key for setting in settings] == [
        "tracker_fetch_limit",
        "pr_feedback_fetch_limit",
        "local_agent_provider",
        "local_agent_model",
        "local_agent_name",
        "cli_agent_preview_chars",
    ]
    assert [setting.value for setting in settings] == [
        "100",
        "100",
        "openai",
        "gpt-5.4",
        "local-placeholder-runner",
        "1000",
    ]


def test_bootstrap_schema_preserves_existing_application_setting_value(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'app.db'}"

    bootstrap_schema(database_url)

    engine = build_engine(database_url)
    with Session(engine) as session:
        setting = (
            session.query(ApplicationSetting)
            .filter(ApplicationSetting.setting_key == "tracker_fetch_limit")
            .one()
        )
        setting.value = "25"
        setting.description = "outdated"
        session.commit()

    bootstrap_schema(database_url)

    with Session(engine) as session:
        setting_count = session.query(ApplicationSetting).count()
        setting = (
            session.query(ApplicationSetting)
            .filter(ApplicationSetting.setting_key == "tracker_fetch_limit")
            .one()
        )

    assert setting_count == 6
    assert setting.value == "25"
    assert setting.description == "Maximum tracker tasks fetched by worker1 in one poll."


def test_main_accepts_database_url_override(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"

    exit_code = main(["--database-url", database_url])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert (
        "MVP schema is ready; created tables: tasks, token_usage, "
        "agent_prompts, application_settings, agent_feedback_entries"
    ) in stdout
