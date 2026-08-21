"""One meeting, from join to teardown.

A session owns the components for a single meeting and coordinates them. It is
an orchestrator, not an implementation: it decides *what* happens and in *what
order*, and delegates every how.

The distinction is the point of the refactor. The class this replaces did the
Playwright calls, the DOM queries, the WebSocket emits, the HTTP uploads and
the email sending itself. Here each of those lives behind an interface, so a
change to any one of them lands in exactly one file.

What a session owns:

    Browser            -> BrowserManager
    Meeting platform   -> MeetingPlatform      (Google Meet today)
    Audio              -> Recorder             -> ChunkUploader
    Transcript         -> TranscriptionProvider -> ContextBuffer
    Chat               -> ChatMonitor
    Headcount          -> ParticipantMonitor
    Streaming          -> ConnectionManager    -> AudioServiceClient
    Live status        -> RuntimeState
    Durable status     -> MeetingStateRepository

Several methods here are only ever reached through a callback — a chat command, a
socket event, a monitor, the heartbeat. Those carry a ``Called by:`` line;
``docs/ENTRY_POINTS.md`` is the full index.
"""

from __future__ import annotations

import asyncio
import logging

from app.browser.browser import Browser
from app.clients.audio_service import AudioServiceClient
from app.context.buffer import ContextBuffer, InMemoryContextBuffer
from app.core.exceptions import (
    MeetingBotError,
    RecordingAlreadyActiveError,
    RecordingNotActiveError,
    TranscriptionNotActiveError,
)
from app.core.request_context import bind
from app.meeting.chat_monitor import ChatMonitor
from app.meeting.lifecycle import LifecycleRunner, LifecycleStep
from app.meeting.models import MeetingRequest, new_session_id
from app.meeting.participant_monitor import ParticipantMonitor
from app.meeting.session_dependencies import SessionDependencies
from app.meeting_platform.base import MeetingPlatform
from app.meeting_platform.google_meet.scripts import init_scripts
from app.meeting_platform.models import (
    AudioPlaybackRequest,
    ChatMessage,
    JoinRequest,
    MeetingRoomState,
)
from app.meeting_platform.registry import create_platform
from app.recording.audio_buffer import AudioBuffer
from app.recording.chunk_uploader import (
    ChunkUploader,
    DirectChunkUploader,
    StreamingChunkUploader,
)
from app.recording.models import RecordingStats, RecordingStatus
from app.recording.recorder import Recorder
from app.recording.upload_finalizer import UploadFinalizer
from app.repositories.base import MeetingLifecycleEvent
from app.runtime.heartbeat import Heartbeat
from app.runtime.state import ComponentState, RuntimeState, SessionState
from app.schemas.websocket import RecordingEndedEvent
from app.transcription.base import TranscriptionProvider
from app.transcription.models import TranscriptSegment
from app.transcription.provider import create_provider
from app.websocket.connection_manager import ConnectionManager
from app.websocket.event_handler import AudioServiceEventHandler

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 15.0


class MeetingSession:
    """Coordinates one meeting's components."""

    def __init__(self, request: MeetingRequest, dependencies: SessionDependencies) -> None:
        self._request = request
        self._deps = dependencies
        self._settings = dependencies.settings

        self._session_id = new_session_id()
        self._state = RuntimeState(meeting_id=request.meeting_id, session_id=self._session_id)
        self._lifecycle = LifecycleRunner(meeting_id=request.meeting_id)

        self._browser: Browser | None = None
        self._platform: MeetingPlatform | None = None
        self._recorder: Recorder | None = None
        self._transcription: TranscriptionProvider | None = None
        self._chat: ChatMonitor | None = None
        self._participants: ParticipantMonitor | None = None
        self._heartbeat: Heartbeat | None = None

        self._context: ContextBuffer = InMemoryContextBuffer(
            max_items=self._settings.transcription.context_buffer_max_segments
        )
        self._connection = ConnectionManager(self._settings.websocket, owner=f"ws:{request.meeting_id}")
        self._audio_service = AudioServiceClient(self._connection)
        self._events = AudioServiceEventHandler(self._connection)

        self._stopping = False
        self._torn_down = False
        self._stop_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Identity and status
    # ------------------------------------------------------------------

    @property
    def meeting_id(self) -> str:
        return self._request.meeting_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def request(self) -> MeetingRequest:
        return self._request

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def is_live(self) -> bool:
        return self._state.session_state.is_live

    @property
    def recorder(self) -> Recorder | None:
        return self._recorder

    @property
    def platform(self) -> MeetingPlatform | None:
        """The platform driver, or ``None`` before the browser has launched."""
        return self._platform

    def status_snapshot(self) -> dict:
        """Cheap status for the API. Touches no I/O."""
        snapshot = self._state.as_dict()
        snapshot["websocket"] = self._connection.info().as_dict()
        snapshot["recording"] = self._recorder.status_detail() if self._recorder else None
        snapshot["transcription"] = (
            {"provider": self._transcription.name, **self._transcription.stats.as_dict()}
            if self._transcription
            else None
        )
        snapshot["chat_messages"] = self._chat.message_count if self._chat else 0
        return snapshot

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Join the meeting and bring up monitoring.

        Recording and transcription are not started here; they are started on
        request, or by a chat command. Joining and observing is what makes a
        session *live*.

        Raises:
            MeetingBotError: If a critical startup step fails. The session is
                torn down before the error propagates, so a failed join leaves
                no browser behind.
        """
        with bind(meeting_id=self.meeting_id, session_id=self._session_id):
            await self._record_event(MeetingLifecycleEvent.INITIALIZED, self._initial_metadata())

            try:
                await self._lifecycle.start(self._startup_steps())
            except Exception as error:
                self._state.transition(SessionState.FAILED, error=str(error))
                self._state.last_error = str(error)
                await self._record_event(MeetingLifecycleEvent.FAILED, {"error": str(error)})
                logger.error("Session startup failed", exc_info=error, extra={"meeting_id": self.meeting_id})
                await self._teardown()
                raise

            self._state.transition(SessionState.IN_MEETING)
            await self._record_event(
                MeetingLifecycleEvent.IN_MEETING,
                {"participant_count": self._state.participant_count},
            )

    def _startup_steps(self) -> list[LifecycleStep]:
        """Startup order. Everything before the join must exist for it to work."""
        return [
            LifecycleStep("launch_browser", self._launch_browser, timeout_seconds=120.0),
            LifecycleStep("create_platform", self._create_platform, timeout_seconds=10.0),
            LifecycleStep(
                "join_meeting",
                self._join_meeting,
                timeout_seconds=self._settings.meeting.admission_timeout_seconds + 60,
            ),
            # From here on nothing is essential to being in the meeting, so a
            # failure degrades the session rather than ending it.
            #
            # Monitors come first deliberately. Reaching the audio service can
            # take the full retry budget — half a minute against an unreachable
            # one — and the bot is already sitting in the meeting by then. Doing
            # it the other way round left the meeting unwatched for that whole
            # window: no participant count, no chat commands, no heartbeat.
            LifecycleStep("start_monitors", self._start_monitors, critical=False, timeout_seconds=30.0),
            LifecycleStep(
                "connect_audio_service", self._connect_audio_service, critical=False, timeout_seconds=60.0
            ),
        ]

    async def _launch_browser(self) -> None:
        self._state.browser.set(ComponentState.STARTING)
        self._browser = await self._deps.browser_manager.launch(init_scripts=init_scripts())
        self._state.browser.set(ComponentState.ACTIVE, mode=self._browser.mode.value)

    async def _create_platform(self) -> None:
        assert self._browser is not None
        self._platform = create_platform(
            self._request.meeting_url, self._browser, self._settings.meeting
        )
        self._state.platform.set(ComponentState.STARTING, platform=self._platform.name.value)

    async def _join_meeting(self) -> None:
        assert self._platform is not None
        self._state.transition(SessionState.JOINING)
        await self._record_event(
            MeetingLifecycleEvent.JOINING, {"meeting_url": self._request.meeting_url}
        )

        result = await self._platform.join(
            JoinRequest(
                meeting_url=self._request.meeting_url,
                display_name=self._settings.browser.guest_display_name,
                meeting_id=self.meeting_id,
            )
        )
        self._state.platform.set(ComponentState.ACTIVE, waited_seconds=round(result.waited_seconds, 1))

    async def _connect_audio_service(self) -> None:
        """Connect to the audio service and wire the reconnect drain."""
        if not self._connection.enabled:
            self._state.websocket.set(ComponentState.IDLE, reason="not configured")
            return

        self._events.register()
        self._events.on_play_audio(self._handle_remote_play_audio)
        self._events.on_leave_meeting(self._handle_remote_leave)
        self._connection.set_on_reconnect(self._drain_buffered_audio)

        connected = await self._connection.connect()
        self._state.websocket.set(
            ComponentState.ACTIVE if connected else ComponentState.DEGRADED,
            connection_state=self._connection.state.value,
        )

    async def _start_monitors(self) -> None:
        """Start participant monitoring, chat monitoring and the heartbeat."""
        assert self._platform is not None

        self._participants = ParticipantMonitor(
            platform=self._platform,
            meeting_id=self.meeting_id,
            poll_interval_seconds=self._settings.meeting.participant_poll_interval_seconds,
            solo_grace_period_seconds=self._settings.meeting.solo_grace_period_seconds,
            auto_leave_when_alone=self._settings.meeting.auto_leave_when_alone,
        )
        self._participants.on_count_change(self._handle_participant_change)
        self._participants.on_alone(self._handle_left_alone)
        await self._participants.start()
        self._state.participant_count = self._participants.count

        self._chat = ChatMonitor(
            platform=self._platform,
            meeting_id=self.meeting_id,
            command_prefix=self._settings.meeting.chat_command_prefix,
            commands_enabled=self._settings.meeting.chat_commands_enabled,
        )
        self._register_chat_commands(self._chat)
        await self._chat.start()

        self._heartbeat = Heartbeat(
            state=self._state,
            probe=self._probe_liveness,
            interval_seconds=_HEARTBEAT_INTERVAL_SECONDS,
            on_dead=self._handle_session_dead,
        )
        self._heartbeat.start()

    def _register_chat_commands(self, chat: ChatMonitor) -> None:
        """Bind in-chat phrases to session actions."""
        chat.register_command("start recording", lambda _message: self._safe(self.start_recording()))
        chat.register_command("stop recording", lambda _message: self._safe(self.stop_recording()))
        chat.register_command(
            "start caption recording", lambda _message: self._safe(self.start_transcription())
        )
        chat.register_command(
            "stop caption recording", lambda _message: self._safe(self.stop_transcription())
        )
        chat.register_command("leave", lambda _message: self._safe(self.stop()))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def start_recording(
        self,
        max_duration_seconds: int | None = None,
        generate_incremental_highlights: bool = False,
    ) -> None:
        """Begin recording meeting audio.

        Args:
            max_duration_seconds: Optional maximum duration before auto-uploading segment.
            generate_incremental_highlights: Whether to request highlights for segments.

        Raises:
            RecordingAlreadyActiveError: If a recording is already running.
            RecordingError: If capture cannot start.
        """
        with bind(meeting_id=self.meeting_id, session_id=self._session_id):
            if self._recorder is not None and self._recorder.is_active:
                raise RecordingAlreadyActiveError(
                    f"recording already active for meeting {self.meeting_id!r}"
                )

            assert self._platform is not None, "cannot record before joining"

            self._state.recording.set(ComponentState.STARTING)
            self._recorder = self._build_recorder(
                max_duration_seconds=max_duration_seconds,
                generate_incremental_highlights=generate_incremental_highlights,
            )

            try:
                await self._recorder.start()
            except Exception as error:
                self._state.recording.set(ComponentState.FAILED, reason=str(error))
                raise

            self._state.recording.set(ComponentState.ACTIVE, transport=self._recorder.transport)
            await self._record_event(
                MeetingLifecycleEvent.RECORDING_STARTED,
                {"transport": self._recorder.transport},
            )

    def _build_recorder(
        self,
        max_duration_seconds: int | None = None,
        generate_incremental_highlights: bool = False,
    ) -> Recorder:
        """Assemble the recording pipeline for the configured transport.

        Args:
            max_duration_seconds: Optional maximum duration before auto-uploading segment.
            generate_incremental_highlights: Whether to request highlights for segments.
        """
        assert self._platform is not None
        stats = RecordingStats()
        uploader = self._build_uploader(stats)

        # Build a factory function for creating new uploaders during segment transitions
        # This ensures each segment gets a fresh uploader with clean state
        def uploader_builder() -> ChunkUploader:
            """Create a new uploader for the next segment."""
            new_stats = RecordingStats()
            return self._build_uploader(new_stats)

        return Recorder(
            platform=self._platform,
            uploader=uploader,
            context=self._request.to_recording_context(),
            finalizer=UploadFinalizer(
                cw_client=self._deps.cw_client,
                mail_client=self._deps.mail_client,
                highlights_manager=self._deps.highlights_manager,
            ),
            chunk_duration_ms=self._settings.recording.chunk_duration_ms,
            finalize_grace_period_seconds=self._settings.recording.finalize_grace_period_seconds,
            max_duration_seconds=max_duration_seconds,
            generate_incremental_highlights=generate_incremental_highlights,
            uploader_builder=uploader_builder,
        )

    def _build_uploader(self, stats: RecordingStats) -> ChunkUploader:
        """Choose an upload transport.

        ``websocket`` requires a configured audio service; without one, direct
        upload is the only way audio reaches storage, so fall back rather than
        record into a void.
        """
        recording = self._settings.recording

        if recording.upload_transport == "websocket" and self._connection.enabled:
            return StreamingChunkUploader(
                audio_service=self._audio_service,
                buffer=AudioBuffer(
                    max_chunks=recording.queue_max_chunks,
                    max_memory_bytes=recording.queue_max_memory_bytes,
                ),
                stats=stats,
            )

        if recording.upload_transport == "websocket":
            logger.warning(
                "Audio service not configured; uploading recording directly to storage",
                extra={"meeting_id": self.meeting_id},
            )

        return DirectChunkUploader(
            cw_client=self._deps.cw_client,
            storage=self._deps.storage_client,
            stats=stats,
            block_size_bytes=recording.resumable_block_size_bytes,
            content_type=recording.content_type,
        )

    async def stop_recording(self) -> None:
        """Stop recording and finalize the upload.

        Raises:
            RecordingNotActiveError: If no recording is running.
        """
        with bind(meeting_id=self.meeting_id, session_id=self._session_id):
            if self._recorder is None or not self._recorder.is_active:
                raise RecordingNotActiveError(f"no active recording for meeting {self.meeting_id!r}")

            self._state.recording.set(ComponentState.STOPPING)
            outcome = await self._recorder.stop()

            # In streaming mode the audio service owns object finalization, so
            # it needs to be told the stream has ended before it can close it.
            if self._recorder.transport == "websocket":
                await self._notify_recording_ended(outcome.pending_chunks)

            self._state.recording.set(
                ComponentState.STOPPED if outcome.complete else ComponentState.DEGRADED,
                **outcome.as_dict(),
            )
            await self._record_event(MeetingLifecycleEvent.RECORDING_STOPPED, outcome.as_dict())

    async def _notify_recording_ended(self, pending_chunks: int) -> None:
        assert self._recorder is not None
        await self._audio_service.notify_recording_ended(
            RecordingEndedEvent(
                meeting_id=self.meeting_id,
                project_id=self._request.project_id,
                queued_chunks=pending_chunks,
                total_chunks=self._recorder.stats.chunks_captured,
                user_name=self._request.user_name,
                user_email=self._request.user_email,
            ),
            timeout_seconds=self._settings.websocket.request_timeout_seconds,
        )

    async def _drain_buffered_audio(self) -> None:
        """Flush buffered chunks after the audio service comes back.

        Called by: ConnectionManager, via ``set_on_reconnect``, once a dropped
        connection is re-established.
        """
        if self._recorder is None or not self._recorder.is_active:
            return
        sent = await self._recorder.flush_pending()
        if sent:
            logger.info("Flushed buffered audio after reconnect", extra={"chunk_count": sent})

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    async def start_transcription(self) -> None:
        """Begin producing a transcript.

        Raises:
            TranscriptionError: If the configured provider cannot start.
        """
        with bind(meeting_id=self.meeting_id, session_id=self._session_id):
            if self._transcription is not None and self._transcription.is_active:
                logger.debug("Transcription already running")
                return

            assert self._platform is not None, "cannot transcribe before joining"

            self._state.transcription.set(ComponentState.STARTING)
            self._transcription = create_provider(
                self._platform, self.meeting_id, self._settings.transcription
            )

            try:
                await self._transcription.start(self._handle_transcript_segment)
            except Exception as error:
                self._state.transcription.set(ComponentState.FAILED, reason=str(error))
                raise

            self._state.transcription.set(ComponentState.ACTIVE, provider=self._transcription.name)
            await self._record_event(
                MeetingLifecycleEvent.TRANSCRIPTION_STARTED,
                {"provider": self._transcription.name},
            )

    async def stop_transcription(self) -> list[TranscriptSegment]:
        """Stop transcribing and return the transcript.

        Raises:
            TranscriptionNotActiveError: If transcription was never started.
        """
        with bind(meeting_id=self.meeting_id, session_id=self._session_id):
            if self._transcription is None:
                raise TranscriptionNotActiveError(
                    f"transcription was never started for meeting {self.meeting_id!r}"
                )

            self._state.transcription.set(ComponentState.STOPPING)
            segments = await self._transcription.stop()
            self._state.transcription.set(ComponentState.STOPPED, segment_count=len(segments))
            await self._record_event(
                MeetingLifecycleEvent.TRANSCRIPTION_STOPPED, {"segment_count": len(segments)}
            )
            return segments

    def transcript(self) -> list[TranscriptSegment]:
        """The transcript so far, without stopping."""
        return self._transcription.segments() if self._transcription else []

    async def _handle_transcript_segment(self, segment: TranscriptSegment) -> None:
        """Store a segment and stream it onward."""
        await self._context.append(segment.as_context_item())
        await self._audio_service.send_transcript_segment(segment.as_wire_payload(self.meeting_id))

    # ------------------------------------------------------------------
    # Chat and audio playback
    # ------------------------------------------------------------------

    def chat_messages(self) -> list[ChatMessage]:
        return self._chat.messages if self._chat else []

    async def play_audio(self, audio_url: str, volume: float = 0.7) -> bool:
        """Play audio into the meeting through the bot's virtual microphone."""
        if self._platform is None:
            return False
        return await self._platform.play_audio(
            AudioPlaybackRequest(audio_url=audio_url, volume=volume)
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Leave the meeting and release everything. Idempotent."""
        async with self._stop_lock:
            if self._stopping or self._state.session_state.is_terminal:
                return
            self._stopping = True

            with bind(meeting_id=self.meeting_id, session_id=self._session_id):
                self._state.transition(SessionState.LEAVING)
                await self._teardown()
                self._state.transition(SessionState.ENDED)
                await self._record_event(
                    MeetingLifecycleEvent.LEFT,
                    {"uptime_seconds": round(self._state.uptime_seconds, 1)},
                )

    async def _teardown(self) -> None:
        """Run shutdown steps in dependency order.

        The order encodes real constraints:
          1. Stop producers, so nothing new arrives mid-flush.
          2. Flush and finalize the recording while the page still exists.
          3. Close the streaming connection.
          4. Leave the meeting politely.
          5. Release the browser — last, and unconditionally.

        Guarded against running twice: a failed startup tears down from
        :meth:`start` while a concurrent shutdown may also call :meth:`stop`,
        and two teardowns racing over the same browser is not worth reasoning
        about.
        """
        if self._torn_down:
            return
        self._torn_down = True

        await self._lifecycle.shutdown(
            [
                LifecycleStep("stop_heartbeat", self._stop_heartbeat, timeout_seconds=5.0),
                LifecycleStep("stop_monitors", self._stop_monitors, timeout_seconds=10.0),
                LifecycleStep("stop_transcription", self._stop_transcription_quietly, timeout_seconds=15.0),
                LifecycleStep("stop_recording", self._stop_recording_quietly, timeout_seconds=120.0),
                LifecycleStep("disconnect_audio_service", self._connection.disconnect, timeout_seconds=15.0),
                LifecycleStep("leave_meeting", self._leave_meeting, timeout_seconds=20.0),
                LifecycleStep("close_browser", self._close_browser, timeout_seconds=30.0),
            ]
        )

    async def _stop_heartbeat(self) -> None:
        if self._heartbeat is not None:
            await self._heartbeat.stop()

    async def _stop_monitors(self) -> None:
        if self._participants is not None:
            await self._participants.stop()
        if self._chat is not None:
            await self._chat.stop()

    async def _stop_transcription_quietly(self) -> None:
        """Stop transcription if it is running, treating 'not running' as done."""
        if self._transcription is None or not self._transcription.is_active:
            return
        await self.stop_transcription()

    async def _stop_recording_quietly(self) -> None:
        """Finalize the recording if one is running.

        This is the step that must not be skipped: it is what turns captured
        audio into a stored object.
        """
        if self._recorder is None or not self._recorder.is_active:
            return
        try:
            await self.stop_recording()
        except MeetingBotError as error:
            logger.warning("Could not finalize recording cleanly", extra={"reason": str(error)})
            await self._recorder.abort()

    async def _leave_meeting(self) -> None:
        if self._platform is not None:
            await self._platform.leave()
        self._state.platform.set(ComponentState.STOPPED)

    async def _close_browser(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        self._state.browser.set(ComponentState.STOPPED)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_participant_change(self, previous: int, current: int) -> None:
        """Called by: ParticipantMonitor, via ``on_count_change``."""
        self._state.participant_count = current
        await self._record_event(
            MeetingLifecycleEvent.PARTICIPANTS_CHANGED,
            {"participant_count": current, "previous_count": previous},
        )

    async def _handle_left_alone(self) -> None:
        """Called by: ParticipantMonitor, after the solo grace period elapses.

        One of three paths that end a meeting; see docs/ENTRY_POINTS.md §5.
        """
        logger.info("Leaving: no other participants remain", extra={"meeting_id": self.meeting_id})
        await self.stop()

    async def _handle_session_dead(self) -> None:
        """Called by: Heartbeat, once the liveness probe fails repeatedly."""
        logger.warning("Heartbeat declared the session dead; shutting down", extra={"meeting_id": self.meeting_id})
        await self.stop()

    async def _handle_remote_play_audio(self, command) -> None:  # type: ignore[no-untyped-def]
        """Called by: the audio service, via the ``playAudio`` event."""
        await self.play_audio(command.audio_url, command.volume)

    async def _handle_remote_leave(self, _meeting_id: str) -> None:
        """Called by: the audio service, via the ``leaveMeeting`` event."""
        await self.stop()

    async def _probe_liveness(self) -> bool:
        """Whether the bot is still genuinely in the meeting.

        Called by: Heartbeat, on its interval.
        """
        if self._browser is None or not self._browser.is_available:
            return False
        if self._platform is None:
            return False
        return await self._platform.get_room_state() is not MeetingRoomState.ENDED

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _record_event(self, event: MeetingLifecycleEvent, metadata: dict | None = None) -> None:
        """Persist a lifecycle transition. Never raises."""
        await self._deps.state_repository.record(self.meeting_id, event, metadata=metadata)

        if self._deps.meeting_api_client is not None:
            await self._deps.meeting_api_client.report_status(
                self.meeting_id, event.value, detail=metadata
            )

    def _initial_metadata(self) -> dict:
        return {
            "session_id": self._session_id,
            "meeting_url": self._request.meeting_url,
            "user_name": self._request.user_name,
            "user_email": self._request.user_email,
            "project_id": self._request.project_id,
            "project_name": self._request.project_name,
            "meeting_title": self._request.meeting_title,
        }

    @staticmethod
    async def _safe(awaitable) -> None:  # type: ignore[no-untyped-def]
        """Run a chat-triggered action, logging instead of propagating failures.

        A participant mistyping a command must not take the session down.
        """
        try:
            await awaitable
        except Exception as error:  # noqa: BLE001 - chat commands are best-effort
            logger.warning("Chat-triggered action failed", extra={"reason": str(error)})

    @property
    def recording_status(self) -> RecordingStatus:
        return self._recorder.status if self._recorder else RecordingStatus.IDLE
