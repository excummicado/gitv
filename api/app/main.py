"""FastAPI application and ASGI entry point."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import create_db_and_tables, engine
from .messages import request_lang, translate
from .routers import (
    abyss,
    admin,
    analytics,
    characters,
    discord,
    health,
    matches,
    players,
    schedule,
    suggestions,
    tournaments,
    users,
)
from .services.abyss import ASSETS as ABYSS_ASSETS
from .services.stats.snapshot import warm_up
from .services.sync import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite tables are created on startup only for the time being (no migrations yet).
    create_db_and_tables()
    # Statistics are built in the background straight away instead of on the first request.
    warming = asyncio.create_task(asyncio.to_thread(warm_up, engine))
    # Background sync with the tournament site, when SYNC_INTERVAL is set (off by default).
    task = asyncio.create_task(run_forever(engine, settings.sync_interval)) if settings.sync_interval > 0 else None
    yield
    warming.cancel()
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def translated_http_exception(request: Request, exc: StarletteHTTPException):
    """Error messages in the site's language (messages.py)."""
    if isinstance(exc.detail, str):
        exc.detail = translate(exc.detail, request_lang(request))
    return await http_exception_handler(request, exc)


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(discord.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(matches.router, prefix=settings.api_prefix)
app.include_router(players.router, prefix=settings.api_prefix)
app.include_router(suggestions.router, prefix=settings.api_prefix)
app.include_router(schedule.router, prefix=settings.api_prefix)
app.include_router(tournaments.router, prefix=settings.api_prefix)
app.include_router(characters.router, prefix=settings.api_prefix)
app.include_router(analytics.router, prefix=settings.api_prefix)
app.include_router(abyss.router, prefix=settings.api_prefix)

# Spiral Abyss icons downloaded from alioth.wiki (services/abyss.py): game assets only, never uploads.
ABYSS_ASSETS.mkdir(parents=True, exist_ok=True)
app.mount(f"{settings.api_prefix}/abyss-assets", StaticFiles(directory=ABYSS_ASSETS), name="abyss-assets")
