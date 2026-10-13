"""FastAPI application and ASGI entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .database import create_db_and_tables
from .routers import admin, discord, health, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite tables are created on startup only for the time being (no migrations yet).
    create_db_and_tables()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(discord.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
