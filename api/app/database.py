"""Database engine and session dependency."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlmodel import Session, create_engine

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


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
