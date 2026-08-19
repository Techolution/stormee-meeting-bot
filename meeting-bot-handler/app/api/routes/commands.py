"""Command endpoints.

Lifecycle commands live on the session resource in ``bot.py`` — a command is
something done *to* a session, and splitting them across routers only makes the
two halves harder to find. This module is kept as the home for command-style
endpoints that are not per-session.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["commands"])
