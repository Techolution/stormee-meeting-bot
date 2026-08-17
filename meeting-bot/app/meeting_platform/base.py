"""The meeting-platform interface.

This is the seam between "what the bot does" and "how a specific product does
it". :class:`~app.meeting.meeting_manager.MeetingManager` orchestrates against
this interface only; it never learns that captions come from a DOM node or that
joining involves clicking a button.

Adding a platform means implementing this class and registering it in
:mod:`app.meeting_platform.registry`. Nothing else changes.

Contract notes for implementers:

  * Observation methods (``get_participants``, ``get_captions``,
    ``get_room_state``) are polled continuously. They must degrade — return an
    empty result or ``UNKNOWN`` — rather than raise on a transient UI hiccup, or
    every monitoring loop becomes a source of noise.
  * Action methods (``join``, ``leave``, ``start_recording``) may raise; a
    caller asked for something specific and deserves to know it failed.
  * ``leave`` must be idempotent. Shutdown paths call it from more than one
    place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.meeting_platform.models import (
    AudioPlaybackRequest,
    CaptionLine,
    ChatMessage,
    JoinRequest,
    JoinResult,
    MeetingRoomState,
    Participant,
    PlatformCapabilities,
    PlatformName,
    RecordingHandle,
)


class MeetingPlatform(ABC):
    """Drives one meeting product through a browser."""

    #: Which platform this implementation speaks for.
    name: PlatformName

    #: Declared feature support. Callers should check before using a feature.
    capabilities: PlatformCapabilities = PlatformCapabilities()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def join(self, request: JoinRequest) -> JoinResult:
        """Navigate to the meeting and get admitted.

        Covers the full flow: navigation, dismissing interstitials, silencing
        the microphone and camera before entry, submitting the join request,
        and waiting out the lobby.

        Raises:
            AuthenticationRequiredError: The meeting rejects anonymous joins.
            MeetingAdmissionTimeoutError: Never admitted within the budget.
            MeetingJoinError: Any other failure to enter.
        """

    @abstractmethod
    async def leave(self) -> None:
        """Leave the meeting. Must be safe to call more than once."""

    @abstractmethod
    async def get_room_state(self) -> MeetingRoomState:
        """Where the bot currently stands. Never raises; returns ``UNKNOWN`` when unsure."""

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_participants(self) -> list[Participant]:
        """Everyone visible in the meeting, including the bot. Empty on failure."""

    @abstractmethod
    async def get_captions(self) -> list[CaptionLine]:
        """The caption area's current contents.

        This is a snapshot of live, mutating text — successive calls overlap
        heavily. Deduplication belongs to the transcription provider.
        """

    @abstractmethod
    async def get_chat_messages(self) -> list[ChatMessage]:
        """Every chat message currently in the panel.

        Returns the full visible history each call; the caller tracks which
        message ids it has already seen.
        """

    # ------------------------------------------------------------------
    # Media controls
    # ------------------------------------------------------------------

    @abstractmethod
    async def mute_microphone(self) -> bool:
        """Turn the bot's microphone off. Returns True if it is off afterwards."""

    @abstractmethod
    async def unmute_microphone(self) -> bool:
        """Turn the bot's microphone on. Returns True if it is on afterwards."""

    @abstractmethod
    async def is_microphone_on(self) -> bool:
        """Whether the microphone is currently transmitting."""

    @abstractmethod
    async def disable_camera(self) -> bool:
        """Turn the bot's camera off. Returns True if it is off afterwards."""

    @abstractmethod
    async def enable_captions(self) -> bool:
        """Switch on in-meeting captions. Returns True if they are on afterwards."""

    @abstractmethod
    async def open_chat_panel(self) -> bool:
        """Open the chat panel so messages become readable."""

    @abstractmethod
    async def play_audio(self, request: AudioPlaybackRequest) -> bool:
        """Play audio into the meeting through the bot's virtual microphone.

        Unmutes first when needed. Returns True if playback started.
        """

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    @abstractmethod
    async def start_recording(
        self,
        meeting_id: str,
        *,
        chunk_duration_ms: int,
    ) -> RecordingHandle:
        """Begin in-page capture of the mixed meeting audio.

        The page emits chunks through the callback installed by
        :meth:`bind_chunk_sink`, which must be called first.

        Raises:
            RecordingError: If capture cannot start.
        """

    @abstractmethod
    async def stop_recording(self) -> None:
        """Stop in-page capture and flush any chunk still being assembled."""

    @abstractmethod
    async def bind_chunk_sink(self, sink: ChunkSink) -> None:
        """Install the page-side callback that delivers audio chunks.

        Must be called before :meth:`start_recording`.
        """


class ChunkSink(ABC):
    """Receives audio chunks emitted by the page.

    Implemented by :class:`~app.recording.audio_capture.AudioCapture`. Declared
    here so platform implementations depend on an interface rather than on the
    recording package — keeping the dependency arrow pointing one way.
    """

    @abstractmethod
    async def on_chunk(self, payload: dict) -> None:
        """Handle one raw chunk payload from the page.

        Must not raise: an exception here surfaces inside page JavaScript and
        can stop the recorder.
        """


__all__ = ["ChunkSink", "MeetingPlatform"]
