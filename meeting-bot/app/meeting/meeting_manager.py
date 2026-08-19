"""The application's entry point into meeting behaviour.

Everything the API can ask for goes through here. The manager owns the session
registry and the process-level dependencies; it creates sessions, routes
requests to them, and tears them down.

It is deliberately thin. Anything that happens *inside* a meeting belongs to
:class:`~app.meeting.meeting_session.MeetingSession`; the manager's job is
knowing which session a request is for and keeping the registry honest. Keeping
that boundary is what stops this class becoming the god object it replaces.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.core.exceptions import MeetingNotFoundError
from app.core.request_context import bind
from app.meeting.meeting_session import MeetingSession
from app.meeting.models import MeetingRequest
from app.meeting.session_dependencies import SessionDependencies
from app.meeting_platform.models import ChatMessage
from app.repositories.base import MeetingLifecycleEvent, MeetingStateRecord
from app.runtime.session import SessionRegistry
from app.transcription.models import TranscriptSegment

logger = logging.getLogger(__name__)


class MeetingManager:
    """Creates, addresses and disposes of meeting sessions."""

    #: Upper bound on stopping one session. Teardown steps are individually
    #: bounded too, so this only guards against the sum of them exceeding a
    #: pod's termination grace period.
    _STOP_TIMEOUT_SECONDS = 180.0

    def __init__(
        self,
        dependencies: SessionDependencies,
        *,
        max_concurrent_sessions: int = 0,
    ) -> None:
        self._deps = dependencies
        self._sessions = SessionRegistry(max_sessions=max_concurrent_sessions)
        # Startup runs in the background, so the manager holds each task: an
        # unreferenced task can be garbage-collected mid-join, and shutdown must
        # be able to cancel a join that is still in progress.
        self._startup_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    def sessions(self) -> list[MeetingSession]:
        return self._sessions.all()

    def get_session(self, meeting_id: str) -> MeetingSession | None:
        return self._sessions.get(meeting_id)

    def require_session(self, meeting_id: str) -> MeetingSession:
        """Look up a session.

        Raises:
            MeetingNotFoundError: If no session exists for this meeting.
        """
        return self._sessions.require(meeting_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def join_meeting(self, request: MeetingRequest) -> MeetingSession:
        """Register a session and start joining in the background.

        Returns as soon as the session is registered. Joining a meeting takes
        as long as a host takes to admit the bot — up to several minutes — so
        the caller gets an identifier immediately and polls
        :meth:`session_status` for progress.

        Raises:
            MeetingAlreadyActiveError: If this meeting already has a session, or
                the process is at its session limit.
        """
        session = MeetingSession(request, self._deps)
        await self._sessions.add(session)

        with bind(meeting_id=request.meeting_id, session_id=session.session_id):
            logger.info(
                "Joining meeting",
                extra={
                    "meeting_url": request.meeting_url,
                    "project_id": request.project_id,
                    "user_email": request.user_email,
                },
            )
            task = asyncio.create_task(
                self._run_session(session), name=f"session:{request.meeting_id}"
            )
            self._startup_tasks[request.meeting_id] = task
            task.add_done_callback(self._forget_startup_task(request.meeting_id))

        return session

    async def _run_session(self, session: MeetingSession) -> None:
        """Drive a session's startup and guarantee it leaves the registry."""
        try:
            await session.start()
        except asyncio.CancelledError:
            # Shutdown cancelled the join. Teardown is the canceller's
            # responsibility, so unwind without touching the registry.
            raise
        except Exception as error:  # noqa: BLE001 - already logged by the session
            logger.error(
                "Session ended during startup",
                extra={"meeting_id": session.meeting_id, "reason": str(error)},
            )
            await self._sessions.remove(session.meeting_id)

    async def leave_meeting(self, meeting_id: str) -> None:
        """Stop a session and deregister it.

        Raises:
            MeetingNotFoundError: If no session exists for this meeting.
        """
        session = self._sessions.require(meeting_id)
        with bind(meeting_id=meeting_id, session_id=session.session_id):
            try:
                await self._stop_session(session)
            finally:
                # Always deregister: a session that failed to stop cleanly must
                # not block a later join for the same meeting.
                await self._sessions.remove(meeting_id)

    async def shutdown(self) -> None:
        """Stop every session. Called during application shutdown.

        Bounded, because this runs on ``SIGTERM``: exceeding the pod's
        termination grace period turns a graceful shutdown into a ``SIGKILL``,
        which is precisely when a recording gets lost.
        """
        sessions = await self._sessions.clear()
        if not sessions:
            return

        logger.info("Stopping active sessions", extra={"session_count": len(sessions)})
        results = await asyncio.gather(
            *(self._stop_session(session) for session in sessions), return_exceptions=True
        )
        for session, result in zip(sessions, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "Session did not stop cleanly",
                    extra={"meeting_id": session.meeting_id, "reason": str(result)},
                )

    async def _stop_session(self, session: MeetingSession) -> None:
        """Cancel any in-flight join, then tear the session down.

        Cancelling first matters: a join waiting on browser launch or on host
        admission can take minutes, and ``stop`` would otherwise queue behind it.
        """
        await self._cancel_startup(session.meeting_id)
        try:
            await asyncio.wait_for(session.stop(), timeout=self._STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error(
                "Session teardown exceeded its timeout; abandoning it",
                extra={"meeting_id": session.meeting_id, "timeout": self._STOP_TIMEOUT_SECONDS},
            )

    def _forget_startup_task(self, meeting_id: str) -> Callable[[asyncio.Task[None]], None]:
        """Build the done-callback that drops a finished join task."""

        def _forget(_task: asyncio.Task[None]) -> None:
            self._startup_tasks.pop(meeting_id, None)

        return _forget

    async def _cancel_startup(self, meeting_id: str) -> None:
        """Cancel a join still in progress and wait for it to unwind."""
        task = self._startup_tasks.pop(meeting_id, None)
        if task is None or task.done():
            return

        logger.info("Cancelling in-progress join", extra={"meeting_id": meeting_id})
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as error:  # noqa: BLE001 - the task already logged
            logger.debug("Join task raised while cancelling", extra={"reason": str(error)})

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def start_recording(
        self,
        meeting_id: str,
        max_duration_seconds: int | None = None,
        generate_incremental_highlights: bool = False,
    ) -> None:
        """Begin recording a meeting's audio.

        Args:
            meeting_id: The meeting identifier.
            max_duration_seconds: Optional maximum duration before auto-uploading this segment.
            generate_incremental_highlights: Whether to request highlights for segments.
        """
        await self._sessions.require(meeting_id).start_recording(
            max_duration_seconds=max_duration_seconds,
            generate_incremental_highlights=generate_incremental_highlights,
        )

    async def stop_recording(self, meeting_id: str) -> None:
        """Stop recording and finalize the upload."""
        await self._sessions.require(meeting_id).stop_recording()

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    async def start_transcription(self, meeting_id: str) -> None:
        """Begin producing a transcript."""
        await self._sessions.require(meeting_id).start_transcription()

    async def stop_transcription(self, meeting_id: str) -> list[TranscriptSegment]:
        """Stop transcribing and return the transcript."""
        return await self._sessions.require(meeting_id).stop_transcription()

    def get_transcript(self, meeting_id: str) -> list[TranscriptSegment]:
        """The transcript so far, without stopping transcription."""
        return self._sessions.require(meeting_id).transcript()

    def get_chat_messages(self, meeting_id: str) -> list[ChatMessage]:
        """Chat messages collected so far."""
        return self._sessions.require(meeting_id).chat_messages()

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    async def play_audio(self, meeting_id: str, audio_url: str, volume: float = 0.7) -> bool:
        """Play audio into a meeting."""
        return await self._sessions.require(meeting_id).play_audio(audio_url, volume)

    async def set_microphone(self, meeting_id: str, *, enabled: bool) -> bool:
        """Mute or unmute the bot.

        Raises:
            MeetingNotFoundError: If the session exists but has not joined yet,
                so there is no meeting UI to act on.
        """
        session = self._sessions.require(meeting_id)
        if session.platform is None:
            raise MeetingNotFoundError(meeting_id)
        return await (
            session.platform.unmute_microphone() if enabled else session.platform.mute_microphone()
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def session_status(self, meeting_id: str) -> dict:
        """Live status for one session."""
        return self._sessions.require(meeting_id).status_snapshot()

    def all_status(self) -> list[dict]:
        """Live status for every session."""
        return [session.status_snapshot() for session in self._sessions.all()]

    async def meeting_state(self, meeting_id: str) -> MeetingStateRecord | None:
        """The most recent persisted transition for a meeting."""
        return await self._deps.state_repository.current(meeting_id)

    async def meeting_history(self, meeting_id: str, *, limit: int = 100) -> list[MeetingStateRecord]:
        """Persisted transitions for a meeting, newest first."""
        return await self._deps.state_repository.history(meeting_id, limit=limit)

    async def delete_meeting_state(self, meeting_id: str) -> bool:
        """Remove a meeting's persisted state."""
        return await self._deps.state_repository.delete(meeting_id)

    async def record_external_event(
        self,
        meeting_id: str,
        event: MeetingLifecycleEvent,
        *,
        metadata: dict | None = None,
    ) -> bool:
        """Persist a transition raised outside a session."""
        return await self._deps.state_repository.record(meeting_id, event, metadata=metadata)
