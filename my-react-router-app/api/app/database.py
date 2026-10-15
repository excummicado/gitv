"""Database engine and session dependency."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

# SQLite only for the time being; check_same_thread is a SQLite-only option.
# timeout: wait up to 30 s for another process's write (sync running while the API reads) instead of 5 s.
connect_args = {"check_same_thread": False, "timeout": 30}
engine = create_engine(settings.database_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    add_missing_columns()


def add_missing_columns():
    """create_all only makes missing tables; this adds new nullable columns to existing ones (no migrations yet).
    A new NOT NULL column can't be added this way and needs a real migration."""
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            have = {c["name"] for c in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name not in have and column.nullable:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'))


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
