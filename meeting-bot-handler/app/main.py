"""Application entry point.

Startup builds the container — HTTP client, Kubernetes client, session store —
and shutdown tears it down. Nothing with a lifetime is created per request.

Runnable four ways, all equivalent:

    uvicorn app.main:app        production
    make run                    development, with reload
    python -m app.main
    python app/main.py
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

if __package__ in (None, ""):
    # Running this file as a script puts `app/` on sys.path rather than the
    # project root. `import app.…` below then finds no local package and falls
    # through to whatever else claims the name `app` — which, in an environment
    # where the bot worker is installed, is the *bot's* package rather than
    # this one, and the failure reads as a missing attribute rather than a
    # missing path. Adding the root keeps `python app/main.py` honest; the `-m`
    # and uvicorn entry points already have the root on the path.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


#: ASGI application. Served with `uvicorn app.main:app`.
app = create_app()


def main() -> None:
    """Run the service directly, for local development.

    Production uses `uvicorn app.main:app` so the server is configured by the
    deployment rather than by this file.
    """
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment != "production",
        # Watch source only: the reloader walking the whole project turns every
        # incidental file into a restart.
        reload_dirs=[str(Path(__file__).resolve().parent)],
        log_config=None,  # logging is already configured by create_app
    )


if __name__ == "__main__":
    main()
