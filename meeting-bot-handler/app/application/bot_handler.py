"""
Main application orchestrator for Bot sessions.

This module owns workflow orchestration only.

It must not contain:
- Playwright logic
- Google Meet implementation
- recording implementation
- transcription implementation
- WebSocket implementation
- direct Kubernetes API details
"""

from __future__ import annotations


class BotHandler:
    """Orchestrates the lifecycle of one Bot session."""

    async def start_bot(self, session_id: str) -> None:
        raise NotImplementedError

    async def start_recording(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop_recording(self, session_id: str) -> None:
        raise NotImplementedError

    async def start_transcription(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop_transcription(self, session_id: str) -> None:
        raise NotImplementedError

    async def leave(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop(self, session_id: str) -> None:
        raise NotImplementedError

    async def get_status(self, session_id: str):
        raise NotImplementedError
