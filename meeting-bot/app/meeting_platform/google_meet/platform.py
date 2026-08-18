"""Google Meet implementation of :class:`~app.meeting_platform.base.MeetingPlatform`.

This is where "join a meeting" becomes a concrete sequence of Meet-specific
steps. It composes :class:`~app.meeting_platform.google_meet.actions.GoogleMeetActions`
for individual UI operations and owns the ordering, the waits, and the
translation of Meet's behaviour into platform-neutral results.

Two join flows exist because Meet presents two different screens:

  * **Persistent profile** — the browser is signed in. Meet shows the standard
    pre-join screen and the bot goes straight to the media toggles and "Join now".
  * **Ephemeral profile** — no credentials. Meet shows a guest screen with a
    name field, an account interstitial, and "Ask to join".

Both converge on the same lobby wait.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from app.browser.browser import Browser
from app.browser.models import SessionMode
from app.core.exceptions import (
    AuthenticationRequiredError,
    MeetingAdmissionTimeoutError,
    RecordingError,
)
from app.core.timers import Stopwatch, wait_until
from app.meeting_platform.base import ChunkSink, MeetingPlatform
from app.meeting_platform.google_meet import selectors
from app.meeting_platform.google_meet.actions import GoogleMeetActions
from app.meeting_platform.google_meet.scripts import load_script, recorder_start, recorder_stop
from app.meeting_platform.models import (
    AudioPlaybackRequest,
    CaptionLine,
    ChatMessage,
    DeviceState,
    JoinRequest,
    JoinResult,
    MeetingRoomState,
    Participant,
    PlatformCapabilities,
    PlatformName,
    RecordingHandle,
)

logger = logging.getLogger(__name__)

#: Name of the page callback the recorder pushes chunks into.
_CHUNK_CALLBACK = "sendAudioChunkToPython"

_MERGED_AUDIO_HEADER = re.compile(
    r"^(?P<name>.+?)\s*&\s*(?P<count>\d+)\s+others?\b\s*(?P<speech>.*)$",
    re.IGNORECASE,
)


def _normalise_merged_audio_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Expose only the primary name from Meet's merged-audio caption header."""
    normalised: list[dict[str, str]] = []
    for block in blocks:
        match = (
            _MERGED_AUDIO_HEADER.match(block.get("text", "").strip())
            if block.get("speaker", "").strip().casefold() == "groups"
            else None
        )
        if not match:
            normalised.append(block)
            continue

        normalised.append(
            {
                **block,
                "speaker": match.group("name").strip(),
                "text": match.group("speech").strip(),
            }
        )

    return normalised

#: Meet redirects here when a meeting forbids anonymous participants.
_GOOGLE_SIGN_IN_HOST = "accounts.google.com"

#: Pre-join controls animate in; acting sooner than this hits stale elements.
_PREJOIN_SETTLE_SECONDS = 4.0
_SIGNED_IN_SETTLE_SECONDS = 2.0


class GoogleMeetPlatform(MeetingPlatform):
    """Drives Google Meet."""

    name = PlatformName.GOOGLE_MEET
    capabilities = PlatformCapabilities(
        supports_captions=True,
        supports_chat=True,
        supports_participant_list=True,
        supports_audio_playback=True,
        supports_recording=True,
    )

    def __init__(
        self,
        browser: Browser,
        *,
        admission_timeout_seconds: int = 300,
        admission_poll_interval_seconds: float = 2.0,
        navigation_timeout_ms: int = 30_000,
    ) -> None:
        self._browser = browser
        self._actions = GoogleMeetActions(browser)
        self._admission_timeout = admission_timeout_seconds
        self._admission_poll_interval = admission_poll_interval_seconds
        self._navigation_timeout_ms = navigation_timeout_ms

        self._room_state_script = load_script("room_state.js")
        self._captions_script = load_script("captions.js")
        self._chat_script = load_script("chat_messages.js")
        self._play_audio_script = load_script("play_audio.js")

        self._left = False
        self._recording = False

    @property
    def actions(self) -> GoogleMeetActions:
        """Direct access to UI operations, for flows the interface does not cover."""
        return self._actions

    # ------------------------------------------------------------------
    # Join
    # ------------------------------------------------------------------

    async def join(self, request: JoinRequest) -> JoinResult:
        """Navigate to the meeting, request entry, and wait for admission.

        Raises:
            AuthenticationRequiredError: Meet demanded a Google sign-in.
            MeetingAdmissionTimeoutError: The host never admitted the bot.
        """
        watch = Stopwatch()
        logger.info("Navigating to meeting", extra={"meeting_url": request.meeting_url})

        await self._browser.goto(request.meeting_url, timeout_ms=self._navigation_timeout_ms)

        if _GOOGLE_SIGN_IN_HOST in self._browser.url:
            await self._browser.screenshot("sign-in-required")
            raise AuthenticationRequiredError(
                "meeting requires a signed-in Google account; configure BROWSER_PROFILE_DIR",
                details={"meeting_url": request.meeting_url},
            )

        if self._browser.mode is SessionMode.PERSISTENT:
            await self._request_entry_as_account()
        else:
            await self._request_entry_as_guest(request.display_name)

        admitted = await self._wait_for_admission()
        waited = watch.elapsed_seconds

        if not admitted:
            await self._browser.screenshot("admission-timeout")
            raise MeetingAdmissionTimeoutError(request.meeting_id or request.meeting_url, waited)

        logger.info("Admitted to meeting", extra={"waited_seconds": round(waited, 1)})

        # Meet occasionally restores the microphone on entry; make sure the bot
        # is silent before anyone hears it.
        await self._ensure_muted()

        return JoinResult(
            admitted=True,
            state=MeetingRoomState.IN_MEETING,
            waited_seconds=waited,
        )

    async def _request_entry_as_account(self) -> None:
        """Pre-join flow for a signed-in profile."""
        await asyncio.sleep(_SIGNED_IN_SETTLE_SECONDS)
        await self._actions.set_microphone(enabled=False)
        await self._actions.set_camera(enabled=False)
        await self._actions.submit_join()

    async def _request_entry_as_guest(self, display_name: str) -> None:
        """Pre-join flow for an anonymous session."""
        await asyncio.sleep(_PREJOIN_SETTLE_SECONDS)
        await self._actions.dismiss_sign_in_popup()
        await self._actions.fill_guest_name(display_name)
        await self._actions.submit_join()

        # The guest screen exposes only the camera control before entry; the
        # microphone toggle appears once inside and is handled by _ensure_muted.
        await self._browser.click(selectors.PREJOIN_CAMERA_OFF, timeout_ms=8_000, force=True)

    async def _wait_for_admission(self) -> bool:
        """Poll until the bot is in the room or the budget runs out."""
        logger.debug(
            "Waiting for admission",
            extra={"timeout_seconds": self._admission_timeout},
        )

        def _log_progress(waited: float) -> None:
            # Once every ~10s rather than every poll.
            if int(waited) % 10 == 0:
                logger.debug("Still waiting in lobby", extra={"waited_seconds": int(waited)})

        async def _admitted() -> bool:
            return await self.get_room_state() is MeetingRoomState.IN_MEETING

        return await wait_until(
            _admitted,
            timeout_seconds=self._admission_timeout,
            poll_interval_seconds=self._admission_poll_interval,
            on_poll=_log_progress,
        )

    async def _ensure_muted(self) -> None:
        try:
            if await self.is_microphone_on():
                await self.mute_microphone()
        except Exception as error:  # noqa: BLE001 - never fail a join over this
            logger.warning("Could not verify microphone state after joining", extra={"reason": str(error)})

    # ------------------------------------------------------------------
    # Leave
    # ------------------------------------------------------------------

    async def leave(self) -> None:
        """Press leave. Idempotent — repeat calls and a closed page are no-ops."""
        if self._left or not self._browser.is_available:
            return
        self._left = True

        if await self._actions.leave_call():
            logger.info("Left the meeting")
            # Let Meet send its departure signal before the page is torn down.
            await asyncio.sleep(1.5)
        else:
            logger.warning("Leave control not found; closing the page instead")

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    async def get_room_state(self) -> MeetingRoomState:
        """Classify the current screen. Never raises."""
        if not self._browser.is_available:
            return MeetingRoomState.ENDED

        # Wake the control bar first: several in-meeting markers live in it and
        # are absent from the DOM while it is hidden.
        await self._browser.wake_controls()

        raw = await self._browser.try_evaluate(
            self._room_state_script,
            {
                "lobbySelectors": list(selectors.LOBBY_INDICATORS),
                "lobbyText": selectors.LOBBY_WAIT_TEXT,
                "inMeetingSelectors": list(selectors.IN_MEETING_INDICATORS),
            },
            default="UNKNOWN",
        )

        return {
            "LOBBY": MeetingRoomState.LOBBY,
            "IN_MEETING": MeetingRoomState.IN_MEETING,
        }.get(raw, MeetingRoomState.UNKNOWN)

    async def get_participants(self) -> list[Participant]:
        """Every participant tile currently rendered.

        Meet virtualises tiles for large meetings, so this is a lower bound on
        attendance rather than an exact roster.
        """
        if not self._browser.is_available:
            return []

        entries = await self._browser.try_evaluate(
            """
            (selector) => Array.from(document.querySelectorAll(selector)).map((node) => ({
                id: node.getAttribute('data-participant-id') || '',
                name: (node.getAttribute('aria-label') || '').trim(),
            }))
            """,
            selectors.PARTICIPANT_TILE,
            default=[],
        )

        return [
            Participant(identifier=entry.get("id", ""), name=entry.get("name", ""))
            for entry in entries or []
            if entry.get("id")
        ]

    async def get_captions(self) -> list[CaptionLine]:
        """Snapshot the caption region."""
        if not self._browser.is_available:
            return []

        blocks = await self._browser.try_evaluate(
            self._captions_script,
            {
                "containerSelector": selectors.CAPTIONS_CONTAINER,
                "noiseMarkers": list(selectors.CAPTION_NOISE_MARKERS),
            },
            default=[],
        )

        blocks = _normalise_merged_audio_blocks(blocks or [])
        captured_at = datetime.now(timezone.utc)
        return [
            CaptionLine(
                speaker=block.get("speaker", "").strip(),
                text=block.get("text", "").strip(),
                captured_at=captured_at,
            )
            for block in blocks
            if block.get("text", "").strip()
        ]

    async def get_chat_messages(self) -> list[ChatMessage]:
        """Every chat message currently in the panel."""
        if not self._browser.is_available:
            return []

        messages = await self._browser.try_evaluate(self._chat_script, default=[])
        received_at = datetime.now(timezone.utc)

        return [
            ChatMessage(
                message_id=message.get("id", ""),
                sender=message.get("sender", "Unknown"),
                text=message.get("text", ""),
                received_at=received_at,
            )
            for message in messages or []
            if message.get("id") and message.get("text")
        ]

    # ------------------------------------------------------------------
    # Media controls
    # ------------------------------------------------------------------

    async def mute_microphone(self) -> bool:
        return await self._actions.set_microphone(enabled=False)

    async def unmute_microphone(self) -> bool:
        return await self._actions.set_microphone(enabled=True)

    async def is_microphone_on(self) -> bool:
        return await self._actions.microphone_state() is DeviceState.ON

    async def disable_camera(self) -> bool:
        return await self._actions.set_camera(enabled=False)

    async def enable_captions(self) -> bool:
        return await self._actions.enable_captions()

    async def open_chat_panel(self) -> bool:
        return await self._actions.open_chat_panel()

    async def play_audio(self, request: AudioPlaybackRequest) -> bool:
        """Play audio into the meeting, unmuting first if necessary."""
        if not self._browser.is_available:
            logger.error("Cannot play audio: no live page")
            return False

        if not await self.is_microphone_on():
            await self.unmute_microphone()

        try:
            await self._browser.evaluate(
                self._play_audio_script,
                {"audioUrl": request.audio_url, "volume": request.volume},
            )
        except Exception as error:  # noqa: BLE001 - reported to the caller as a bool
            logger.error("Audio playback failed", extra={"reason": str(error)})
            return False

        logger.info("Audio playback started", extra={"volume": request.volume})
        return True


    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def bind_chunk_sink(self, sink: ChunkSink) -> None:
        """Expose the page callback that delivers audio chunks to Python.

        Playwright allows a name to be bound once per page, so re-binding on a
        second recording is a no-op — the original callback stays live, which is
        why the sink is stateless with respect to individual recordings.
        """

        async def _receive(payload: dict) -> None:
            # Exceptions raised here propagate into page JavaScript and stop the
            # recorder, so the sink's contract is to never raise.
            await sink.on_chunk(payload)

        await self._browser.expose_function(_CHUNK_CALLBACK, _receive)

    async def start_recording(self, meeting_id: str, *, chunk_duration_ms: int) -> RecordingHandle:
        """Start the in-page MediaRecorder over the mixed audio graph.

        Raises:
            RecordingError: If the page could not start capturing.
        """
        if not self._browser.is_available:
            raise RecordingError("cannot start recording: no live page")

        try:
            await self._browser.evaluate(recorder_start(), meeting_id)
        except Exception as error:
            raise RecordingError(
                f"failed to start in-page recording: {error}",
                details={"meeting_id": meeting_id},
            ) from error

        self._recording = True
        logger.info(
            "In-page recording started",
            extra={"meeting_id": meeting_id, "chunk_duration_ms": chunk_duration_ms},
        )
        return RecordingHandle(meeting_id=meeting_id, chunk_duration_ms=chunk_duration_ms)

    async def stop_recording(self) -> None:
        """Stop the recorder and let it emit its final chunk.

        Best-effort: if the page has already gone, the recording is over anyway.
        """
        if not self._recording:
            return
        self._recording = False

        if not self._browser.is_available:
            logger.debug("Skipping recorder stop: page already closed")
            return

        try:
            await self._browser.evaluate(recorder_stop())
            logger.info("In-page recording stopped")
        except Exception as error:  # noqa: BLE001
            logger.warning("Recorder stop script failed", extra={"reason": str(error)})
