"""Application entry point.

Startup builds the container — HTTP client, Kubernetes client, session store —
and shutdown tears it down. Nothing with a lifetime is created per request.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestIdMiddleware
from app.api.routes import bot, commands, health, status
from app.bootstrap import create_container
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = create_container(settings)
        logger.info(
            "Meeting bot handler started (environment=%s namespace=%s selector=%s)",
            settings.environment,
            settings.bot_namespace,
            settings.bot_label_selector,
        )
        try:
            yield
        finally:
            await app.state.container.aclose()
            logger.info("Meeting bot handler stopped")

    app = FastAPI(
        title="Meeting Bot Handler",
        description=(
            "Control plane for meeting bot sessions. Assigns each meeting to a "
            "bot pod in the cluster and drives its lifecycle."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(bot.router)
    app.include_router(commands.router)

    @app.get("/", tags=["health"], summary="Service identity")
    async def root() -> dict:
        return {
            "service": settings.app_name,
            "status": "ok",
            "docs": "/docs",
        }

    return app


app = create_app()
