"""Application entry point.

Builds the FastAPI application and manages its lifespan. Deliberately short:
wiring lives in :mod:`app.bootstrap`, routes in :mod:`app.api.routes`, and
behaviour in the domain packages.

The lifespan handler is where graceful shutdown happens. It matters here more
than in a typical service: a bot pod that exits without finalizing its
recording loses the meeting, and one that exits without closing Chromium leaks
a process. Both are handled on the way down.

Runnable four ways, all equivalent:

    uvicorn app.main:app        production
    make run                    development, with reload
    python -m app.main
    python app/main.py
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in (None, ""):
    # Running this file as a script puts `app/` on sys.path rather than the
    # project root, so `import app.…` below would fail with a bare
    # ModuleNotFoundError. Adding the root keeps `python app/main.py` working
    # without requiring the package to be installed first; the `-m` and uvicorn
    # entry points already have the root on the path and are unaffected.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import correlate_meeting
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import api_router
from app.bootstrap import build_application_context
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.version import SERVICE_NAME, VERSION

logger = logging.getLogger(__name__)

_DESCRIPTION = """
Meeting bot that joins a video meeting, records its audio, and produces a
transcript.

One pod runs one meeting. Joining is asynchronous — `POST /meetings/join`
returns as soon as the session is registered, and progress is reported through
`GET /meetings/{meeting_id}/status`.
""".strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Configuration to use. Defaults to the process settings; tests
            pass their own.
    """
    settings = settings or get_settings()

    configure_logging(
        level=settings.app.effective_log_level,
        log_format=settings.app.log_format,
    )

    app = FastAPI(
        title="Meeting Bot API",
        description=_DESCRIPTION,
        version=VERSION,
        lifespan=_lifespan,
        docs_url=f"{settings.app.api_prefix}/docs",
        redoc_url=f"{settings.app.api_prefix}/redoc",
        openapi_url=f"{settings.app.api_prefix}/openapi.json",
    )

    # Stored before startup so the lifespan handler and dependencies can reach it.
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    # Applied at the router so every route correlates its logs without each
    # handler having to remember to.
    app.include_router(
        api_router,
        prefix=settings.app.api_prefix,
        dependencies=[Depends(correlate_meeting)],
    )

    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Construct the object graph on startup; unwind it on shutdown."""
    settings: Settings = app.state.settings

    logger.info(
        "Starting %s",
        SERVICE_NAME,
        extra={"version": VERSION, "environment": settings.app.environment},
    )

    context = await build_application_context(settings)
    app.state.context = context
    app.state.meeting_manager = context.manager
    app.state.state_repository = context.state_repository

    try:
        yield
    finally:
        # Runs on SIGTERM. Any live meeting is finalized here — the recording is
        # flushed and the browser released — before the process exits.
        logger.info("Shutting down %s", SERVICE_NAME)
        await context.aclose()
        logger.info("Shutdown complete")


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
        host=settings.app.host,
        port=settings.app.port,
        reload=not settings.app.is_production,
        # Chromium rewrites its profile constantly while in a meeting — caches,
        # cookies, session files. Watching that directory buries the application
        # log under thousands of change notifications and burns CPU comparing
        # trees, so the reloader is pointed at source only.
        reload_dirs=[str(Path(__file__).resolve().parent)],
        reload_excludes=["chrome_profile/*", "*.log", "screenshots/*"],
        log_config=None,  # logging is already configured by create_app
    )


if __name__ == "__main__":
    main()
