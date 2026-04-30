from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from backend.db import build_engine
from backend.models import AgentPrompt, Base, Task, TokenUsage

DEFAULT_AGENT_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "agents"

MVP_SCHEMA_TABLES = (Task.__tablename__, TokenUsage.__tablename__, AgentPrompt.__tablename__)
MVP_SCHEMA_METADATA = (
    Base.metadata.tables[Task.__tablename__],
    Base.metadata.tables[TokenUsage.__tablename__],
    Base.metadata.tables[AgentPrompt.__tablename__],
)


def bootstrap_schema(database_url: str | None = None) -> tuple[str, ...]:
    engine = build_engine(database_url)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    Base.metadata.create_all(engine, tables=list(MVP_SCHEMA_METADATA))

    with Session(engine) as session:
        seed_default_agent_prompts(session)
        session.commit()

    return tuple(
        table_name for table_name in MVP_SCHEMA_TABLES if table_name not in existing_tables
    )


def seed_default_agent_prompts(
    session: Session,
    prompts_dir: Path = DEFAULT_AGENT_PROMPTS_DIR,
) -> None:
    for prompt_path in sorted(prompts_dir.glob("*.md")):
        prompt_key = prompt_path.stem
        source_path = prompt_path.relative_to(Path(__file__).resolve().parents[2]).as_posix()
        content = prompt_path.read_text(encoding="utf-8")

        prompt = (
            session.query(AgentPrompt).filter(AgentPrompt.prompt_key == prompt_key).one_or_none()
        )
        if prompt is None:
            session.add(
                AgentPrompt(
                    prompt_key=prompt_key,
                    source_path=source_path,
                    content=content,
                )
            )
            continue

        prompt.source_path = source_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the MVP database schema for local development and containers.",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="Override DATABASE_URL for a single bootstrap run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    created_tables = bootstrap_schema(database_url=args.database_url)

    if created_tables:
        print(f"MVP schema is ready; created tables: {', '.join(created_tables)}")
    else:
        print("MVP schema is ready; no new tables were created")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
