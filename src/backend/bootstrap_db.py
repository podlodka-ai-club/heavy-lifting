from __future__ import annotations

import argparse
from collections.abc import Sequence

from sqlalchemy import inspect

from backend.db import build_engine
from backend.models import Base, Task, TokenUsage

MVP_SCHEMA_TABLES = (Task.__tablename__, TokenUsage.__tablename__)
MVP_SCHEMA_METADATA = (
    Base.metadata.tables[Task.__tablename__],
    Base.metadata.tables[TokenUsage.__tablename__],
)


def bootstrap_schema(database_url: str | None = None) -> tuple[str, ...]:
    engine = build_engine(database_url)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    Base.metadata.create_all(engine, tables=list(MVP_SCHEMA_METADATA))

    return tuple(
        table_name for table_name in MVP_SCHEMA_TABLES if table_name not in existing_tables
    )


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
