"""FastAPI application factory and ASGI entry point."""

from fastapi import FastAPI

from app.core.config import settings
from app.routes.router import api_router


def create_app() -> FastAPI:
    application = FastAPI(title=settings.app_name, debug=settings.debug)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
