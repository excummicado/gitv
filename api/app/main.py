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
from .database import engine
from .messages import request_lang, translate
from .routers import (
    abyss,
    admin,
    analytics,
    articles,
    characters,
    discord,
    health,
    matches,
    news,
    players,
    preview,
    schedule,
    tournaments,
    users,
)
from .services.abyss import ASSETS as ABYSS_ASSETS
from .services.media import MEDIA_DIR
from .services.stats.snapshot import warm_up
from .services.stream import run_stream_forever
from .services.sync import run_forever, run_live_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Statistics are built before the API takes requests (about 10 s): requests arriving during the first build would
    # each hold a database connection while waiting for it, and a crowd after a restart used them all up. Meanwhile
    # nginx answers from its cache. A failed build doesn't keep the API down: the first request tries again.
    try:
        await asyncio.to_thread(warm_up, engine)
    except Exception:  # noqa: BLE001
        logging.getLogger("gitv").exception("building the statistics at startup failed")
    # Background sync with the tournament site, when SYNC_INTERVAL is set (off by default): the hourly one and the
    # live poll of running tournaments every two minutes, and the stream (Telegram channel, Twitch) every minute.
    tasks = (
        [
            asyncio.create_task(run_forever(engine, settings.sync_interval)),
            asyncio.create_task(run_live_forever(engine)),
            asyncio.create_task(run_stream_forever(engine)),
        ]
        if settings.sync_interval > 0
        else []
    )
    yield
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# The interactive API docs only when running locally: in production they'd hand out the whole API's map.
LOCAL = settings.frontend_url.startswith(("http://localhost", "http://127.0.0.1"))
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if LOCAL else None,
    redoc_url="/redoc" if LOCAL else None,
    openapi_url="/openapi.json" if LOCAL else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """The API's answers are data, never pages: not to be sniffed into something else or framed."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


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
app.include_router(schedule.router, prefix=settings.api_prefix)
app.include_router(articles.router, prefix=settings.api_prefix)
app.include_router(news.router, prefix=settings.api_prefix)
app.include_router(preview.router, prefix=settings.api_prefix)
app.include_router(tournaments.router, prefix=settings.api_prefix)
app.include_router(characters.router, prefix=settings.api_prefix)
app.include_router(analytics.router, prefix=settings.api_prefix)
app.include_router(abyss.router, prefix=settings.api_prefix)

# Spiral Abyss icons downloaded from alioth.wiki (services/abyss.py): game assets only, never uploads.
ABYSS_ASSETS.mkdir(parents=True, exist_ok=True)
app.mount(f"{settings.api_prefix}/abyss-assets", StaticFiles(directory=ABYSS_ASSETS), name="abyss-assets")

# Uploaded news pictures. Only images checked by their bytes are ever written there (services/media.py).
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount(f"{settings.api_prefix}/media", StaticFiles(directory=MEDIA_DIR), name="media")
