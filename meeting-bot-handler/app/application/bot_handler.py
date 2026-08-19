"""Control-plane orchestration.

Every operation follows the same shape:

    session_id -> session -> resolve pod -> call the bot -> persist -> respond

The two things this file exists to get right:

**Dispatch.** ``start_bot`` walks the candidate pods returned by the resolver
and joins on the first that accepts. A pod that answers 409
``meeting_already_active`` was claimed between the probe and the join; that is
expected under concurrency and simply means "try the next one". Only once a pod
accepts is the assignment written to the session, and from then on every command
for that session goes to that pod.

**Asynchrony.** ``POST /meetings/join`` returns 202 the moment the bot registers
the session; admission depends on a human host and can take minutes. The handler
does not block on it. It records STARTING, returns, and a background watcher
polls the pod until the meeting is live or has failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import httpx

from app.application.bot_client import BotClient
from app.application.bot_service_resolver import BotServiceResolver, BotTarget
from app.application.session_service import SessionService
from app.clients.meeting_api import POD_BUSY_CODES
from app.core.config import Settings, get_settings
from app.core.context import set_session_id
from app.domain.enums import BotStatus, RecordingStatus, TranscriptionStatus
from app.domain.exceptions import (
    BotOperationError,
    BotServiceUnavailableError,
    InvalidSessionStateError,
    NoBotPodAvailableError,
)
from app.domain.models import BotSession
from app.runtime.locks import KeyedLock

logger = logging.getLogger(__name__)

#: Bot session states that mean the attendance is over.
_TERMINAL_BOT_STATES = {"ended", "failed"}


class BotHandler:
    """Application orchestrator for bot sessions."""

    def __init__(
        self,
        session_service: SessionService,
        bot_resolver: BotServiceResolver,
        http_client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ):
        self._session_service = session_service
        self.bot_resolver = bot_resolver
        self._settings = settings or get_settings()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self._settings.bot_request_timeout_seconds
        )
        self._locks = KeyedLock()
        self._watchers: Set[asyncio.Task] = set()

    @property
    def session_service(self) -> SessionService:
        return self._session_service

    def _client_for(self, target: BotTarget) -> BotClient:
        return BotClient(
            service_url=target.service_url,
            http_client=self.http_client,
            api_prefix=self._settings.bot_api_prefix,
            timeout=self._settings.bot_request_timeout_seconds,
        )

    async def _client_for_session(self, session: BotSession) -> BotClient:
        target = await self.bot_resolver.resolve(session)
        return self._client_for(target)

    # --- Dispatch -------------------------------------------------------------
    async def start_bot(self, session_id: str) -> Dict[str, Any]:
        """Send the bot into the meeting.

        Returns as soon as a pod has accepted the join. Reaching the meeting is
        reported through the session's status, not by blocking here.
        """
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.bot_status in (BotStatus.STARTING, BotStatus.RUNNING):
                raise InvalidSessionStateError(
                    f"Session {session_id} is already {session.bot_status.value}",
                    details={"session_id": session_id, "bot_status": session.bot_status.value},
                )
            if session.is_terminal:
                raise InvalidSessionStateError(
                    f"Session {session_id} has finished ({session.meeting_status.value})",
                    details={"session_id": session_id, "meeting_status": session.meeting_status.value},
                )

            targets = await self._dispatch_targets(session)
            accepted, response = await self._join_first_available(session, targets)

            await self._session_service.assign_bot(
                session,
                service_url=accepted.service_url,
                pod_name=accepted.pod_name,
                pod_ip=accepted.pod_ip,
                worker_id=accepted.worker_id,
            )
            await self._session_service.mark_starting(session)

            self._watch_join(session_id, accepted)

            return {
                "session_id": session_id,
                "meeting_id": session.meeting_id,
                "meeting_status": session.meeting_status.value,
                "bot_status": session.bot_status.value,
                "pod": accepted.pod_name,
                "detail": response,
            }

    async def _dispatch_targets(self, session: BotSession) -> List[BotTarget]:
        """Pods to try, in order. An existing assignment is tried first."""
        if session.is_dispatched:
            return [
                BotTarget(
                    service_url=session.service_url or "",
                    worker_id=session.worker_id,
                    pod_name=session.pod_name,
                    pod_ip=session.pod_ip,
                )
            ]
        return await self.bot_resolver.allocate(session)

    async def _join_first_available(
        self, session: BotSession, targets: List[BotTarget]
    ) -> tuple[BotTarget, Dict[str, Any]]:
        last_error: Optional[Exception] = None

        for target in targets:
            client = self._client_for(target)
            try:
                response = await client.join_meeting(
                    meeting_id=session.meeting_id,
                    meeting_url=session.meeting_url,
                    user_name=session.user_name,
                    user_email=session.user_email,
                    project_id=session.project_id,
                    project_name=session.project_name,
                    meeting_title=session.meeting_title,
                )
            except BotOperationError as exc:
                if exc.code in POD_BUSY_CODES or exc.status_code == httpx.codes.SERVICE_UNAVAILABLE:
                    logger.info(
                        "Pod %s is busy (%s); trying the next candidate",
                        target.pod_name or target.service_url,
                        exc.code,
                    )
                    last_error = exc
                    continue
                raise
            except BotServiceUnavailableError as exc:
                logger.warning(
                    "Pod %s did not answer the join; trying the next candidate: %s",
                    target.pod_name or target.service_url,
                    exc,
                )
                last_error = exc
                continue

            logger.info(
                "Meeting %s accepted by pod %s",
                session.meeting_id,
                target.pod_name or target.service_url,
            )
            return target, response

        raise NoBotPodAvailableError(
            "Every candidate bot pod refused the meeting",
            details={
                "session_id": session.session_id,
                "candidates": len(targets),
                "last_error": str(last_error) if last_error else None,
            },
        )

    # --- Join watcher ---------------------------------------------------------
    def _watch_join(self, session_id: str, target: BotTarget) -> None:
        task = asyncio.create_task(self._poll_until_in_meeting(session_id, target))
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)

    async def _poll_until_in_meeting(self, session_id: str, target: BotTarget) -> None:
        """Follow a join to its conclusion and record the outcome.

        A 202 from the bot means the request was accepted, nothing more. The
        session is only ACTIVE once the pod reports ``in_meeting``.
        """
        set_session_id(session_id)
        client = self._client_for(target)
        deadline = time.monotonic() + self._settings.join_poll_timeout_seconds

        while time.monotonic() < deadline:
            await asyncio.sleep(self._settings.join_poll_interval_seconds)

            session = await self._session_service.get_session(session_id)
            if session is None or session.bot_status != BotStatus.STARTING:
                return  # Left, failed, or deleted while we waited.

            try:
                status = await client.get_meeting_status(session.meeting_id)
            except BotOperationError as exc:
                if exc.code == "meeting_not_found":
                    await self._session_service.mark_failed(
                        session, "The bot pod no longer holds this meeting"
                    )
                    return
                logger.warning("Join watcher could not read pod status: %s", exc)
                continue
            except BotServiceUnavailableError as exc:
                logger.warning("Join watcher could not reach pod %s: %s", target.pod_name, exc)
                continue

            state = status.get("session_state")
            if state == "in_meeting":
                await self._session_service.mark_started(session, status.get("session_id"))
                logger.info("Session %s is in the meeting", session_id)
                return
            if state in _TERMINAL_BOT_STATES:
                await self._session_service.mark_failed(
                    session, status.get("last_error") or f"Bot session ended in state '{state}'"
                )
                return

        session = await self._session_service.get_session(session_id)
        if session is not None and session.bot_status == BotStatus.STARTING:
            await self._session_service.mark_failed(
                session,
                f"Bot never reached the meeting within {self._settings.join_poll_timeout_seconds:.0f}s",
            )

    # --- Recording ------------------------------------------------------------
    async def start_recording(self, session_id: str) -> Dict[str, Any]:
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.active_recording_status == RecordingStatus.RECORDING:
                raise InvalidSessionStateError(
                    f"Session {session_id} is already recording",
                    details={"session_id": session_id},
                )

            client = await self._client_for_session(session)
            response = await client.start_recording(session.meeting_id)

            recording = await self._session_service.create_recording(
                session, RecordingStatus.RECORDING
            )
            await self._session_service.set_recording_status(session, RecordingStatus.RECORDING)

            return {
                "session_id": session_id,
                "recording_id": recording.recording_id,
                "recording_status": RecordingStatus.RECORDING.value,
                "detail": response,
            }

    async def stop_recording(self, session_id: str) -> Dict[str, Any]:
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.active_recording_status != RecordingStatus.RECORDING:
                # Retries are expected; a stop with nothing running is a no-op.
                return {
                    "session_id": session_id,
                    "recording_status": session.active_recording_status.value,
                    "detail": {"message": "No recording in progress"},
                }

            client = await self._client_for_session(session)
            response = await client.stop_recording(session.meeting_id)

            await self._finalize_recording(session, client)
            await self._session_service.set_recording_status(session, RecordingStatus.STOPPED)

            return {
                "session_id": session_id,
                "recording_status": RecordingStatus.STOPPED.value,
                "detail": response,
            }

    async def _finalize_recording(self, session: BotSession, client: BotClient) -> None:
        """Record what the bot actually uploaded, best effort."""
        active = await self._session_service.get_active_recording(session.session_id)
        if active is None:
            return

        active.status = RecordingStatus.STOPPED
        active.stopped_at = datetime.now(timezone.utc)
        try:
            stats = await client.get_recording_status(session.meeting_id)
        except (BotOperationError, BotServiceUnavailableError) as exc:
            logger.warning("Could not read final recording stats: %s", exc)
        else:
            active.chunks_captured = stats.get("chunksCaptured", active.chunks_captured)
            active.chunks_uploaded = stats.get("chunksUploaded", active.chunks_uploaded)
            active.chunks_pending = stats.get("chunksPending", active.chunks_pending)
            active.bytes_uploaded = stats.get("bytesUploaded", active.bytes_uploaded)

        await self._session_service.update_recording(active)

    async def get_recording_status(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.get_recording_status(session.meeting_id)

    # --- Transcription and chat ------------------------------------------------
    async def start_transcription(self, session_id: str) -> Dict[str, Any]:
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.transcription_status == TranscriptionStatus.RUNNING:
                raise InvalidSessionStateError(
                    f"Transcription is already running for session {session_id}",
                    details={"session_id": session_id},
                )

            client = await self._client_for_session(session)
            response = await client.start_transcription(session.meeting_id)
            await self._session_service.set_transcription_status(
                session, TranscriptionStatus.RUNNING
            )
            return {
                "session_id": session_id,
                "transcription_status": TranscriptionStatus.RUNNING.value,
                "detail": response,
            }

    async def stop_transcription(self, session_id: str) -> Dict[str, Any]:
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.transcription_status != TranscriptionStatus.RUNNING:
                return {
                    "session_id": session_id,
                    "transcription_status": session.transcription_status.value,
                    "detail": {"message": "Transcription is not running"},
                }

            client = await self._client_for_session(session)
            response = await client.stop_transcription(session.meeting_id)
            await self._session_service.set_transcription_status(
                session, TranscriptionStatus.COMPLETED
            )
            return {
                "session_id": session_id,
                "transcription_status": TranscriptionStatus.COMPLETED.value,
                "detail": response,
            }

    async def get_transcript(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.get_transcript(session.meeting_id)

    async def get_chat(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.get_chat(session.meeting_id)

    # --- Audio ------------------------------------------------------------------
    async def play_audio(self, session_id: str, audio_url: str, volume: float = 0.7) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.play_audio(session.meeting_id, audio_url, volume)

    async def mute(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.mute(session.meeting_id)

    async def unmute(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.require_session(session_id)
        client = await self._client_for_session(session)
        return await client.unmute(session.meeting_id)

    # --- Teardown -----------------------------------------------------------------
    async def leave(self, session_id: str) -> Dict[str, Any]:
        async with self._locks.acquire(session_id):
            session = await self._session_service.require_session(session_id)
            set_session_id(session_id)

            if session.is_terminal:
                # Leaving a finished meeting is a no-op, not an error: the
                # caller may simply be retrying.
                return {
                    "session_id": session_id,
                    "meeting_status": session.meeting_status.value,
                    "detail": {"message": "Session has already ended"},
                }

            if not session.is_dispatched:
                await self._session_service.mark_completed(session)
                return {
                    "session_id": session_id,
                    "meeting_status": session.meeting_status.value,
                    "detail": {"message": "Session was never dispatched to a pod"},
                }

            client = await self._client_for_session(session)
            await self._session_service.mark_leaving(session)

            try:
                response = await client.leave_meeting(session.meeting_id)
            except BotOperationError as exc:
                if exc.code != "meeting_not_found":
                    await self._session_service.mark_failed(session, exc.message)
                    raise
                # The pod has already dropped the meeting; the intent still holds.
                response = {"message": "Meeting was no longer active on the pod"}

            await self._session_service.mark_completed(session)
            self._locks.release_key(session_id)

            return {
                "session_id": session_id,
                "meeting_status": session.meeting_status.value,
                "detail": response,
            }

    async def stop(self, session_id: str) -> Dict[str, Any]:
        return await self.leave(session_id)

    # --- Status ---------------------------------------------------------------
    async def get_status(self, session_id: str, include_runtime: bool = True) -> Dict[str, Any]:
        """Durable state, optionally enriched with what the pod reports.

        The database is the answer; the pod is commentary. A pod that cannot be
        reached degrades the response rather than failing it.
        """
        session = await self._session_service.require_session(session_id)
        set_session_id(session_id)

        runtime: Optional[Dict[str, Any]] = None
        runtime_error: Optional[str] = None

        if include_runtime and session.is_dispatched and not session.is_terminal:
            try:
                client = await self._client_for_session(session)
                runtime = await client.get_meeting_status(session.meeting_id)
            except (BotOperationError, BotServiceUnavailableError) as exc:
                logger.warning("Could not read runtime status from the pod: %s", exc)
                runtime_error = str(exc)
            else:
                session = await self._reconcile(session, runtime)

        return {
            "session_id": session.session_id,
            "meeting_id": session.meeting_id,
            "meeting_status": session.meeting_status.value,
            "bot_status": session.bot_status.value,
            "recording_status": session.active_recording_status.value,
            "transcription_status": session.transcription_status.value,
            "last_error": session.last_error,
            "timestamps": session.timestamps(),
            "runtime": runtime,
            "runtime_error": runtime_error,
        }

    async def _reconcile(self, session: BotSession, runtime: Dict[str, Any]) -> BotSession:
        """Let the pod's reality correct the record, in the safe direction."""
        state = runtime.get("session_state")

        if state == "in_meeting" and session.bot_status != BotStatus.RUNNING:
            return await self._session_service.mark_started(session, runtime.get("session_id"))

        if state in _TERMINAL_BOT_STATES and session.bot_status in (
            BotStatus.STARTING,
            BotStatus.RUNNING,
        ):
            if state == "failed":
                return await self._session_service.mark_failed(
                    session, runtime.get("last_error") or "Bot session failed"
                )
            return await self._session_service.mark_completed(session)

        return session

    async def aclose(self) -> None:
        for task in list(self._watchers):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._owns_http_client:
            await self.http_client.aclose()
