"""Database engine and session dependency."""

from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

# SQLite only for the time being; check_same_thread is a SQLite-only option.
connect_args = {"check_same_thread": False}
engine = create_engine(settings.database_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
