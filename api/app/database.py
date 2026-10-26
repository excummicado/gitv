"""Database engine and session dependency."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

# SQLite only for the time being; check_same_thread is a SQLite-only option.
# timeout: wait up to 30 s for another process's write (sync running while the API reads) instead of 5 s.
connect_args = {"check_same_thread": False, "timeout": 30}
engine = create_engine(settings.database_url, connect_args=connect_args)


@event.listens_for(engine, "connect")
def sqlite_wal(dbapi_connection, _):
    """WAL: readers and a writer don't block each other, so a long read (the API building its statistics) can't
    lock out a write from the CLI or sync. The mode is stored in the database file; setting it again is a no-op."""
    if engine.dialect.name == "sqlite" and settings.database_url != "sqlite://":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    add_missing_columns()
    drop_removed_tables()
    drop_removed_columns()


# Tables of removed features, dropped from databases made before: members' suggestions of players' real names,
# birthdays and avatars, and the profiles and change log made from them.
REMOVED_TABLES = ["playerprofilechange", "playersuggestion", "suggestionban", "playerprofile"]


def drop_removed_tables(bind=None):
    with (bind or engine).begin() as conn:
        for table in REMOVED_TABLES:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))


# Columns the models no longer have, dropped (with their indexes) from databases made before.
REMOVED_COLUMNS = {"user": ["email"]}  # members' emails aren't kept any more


def drop_removed_columns(bind=None):
    bind = bind or engine
    existing = inspect(bind)
    with bind.begin() as conn:
        for table, columns in REMOVED_COLUMNS.items():
            if not existing.has_table(table):
                continue
            have = {c["name"] for c in existing.get_columns(table)}
            for column in columns:
                if column not in have:
                    continue
                for index in existing.get_indexes(table):
                    if column in index["column_names"]:
                        conn.execute(text(f'DROP INDEX "{index["name"]}"'))
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))


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
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                            f"{column.type.compile(engine.dialect)}"
                        )
                    )


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
