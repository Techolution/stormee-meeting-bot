"""The transcription provider interface.

Captions are today's transcript source. They will not be tomorrow's: the
recorded audio already exists, and running speech-to-text over it produces
better text with real timing and speaker diarisation.

That migration is the reason this interface exists. Meeting code starts and
stops a *provider*; it never learns that text currently comes from scraping a
DOM node. Adding a speech-to-text provider means implementing this class, not
editing meeting logic.

A provider's contract:

  * ``start`` begins producing segments and returns promptly. Long-running work
    belongs in a background task the provider owns.
  * Segments are pushed to the sink as they are produced, not accumulated and
    returned at the end — a caller may want to stream them live.
  * ``stop`` returns the complete transcript and is safe to call when not running.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from app.transcription.models import TranscriptionStats, TranscriptionStatus, TranscriptSegment

#: Called once per segment, as it is produced.
SegmentSink = Callable[[TranscriptSegment], Awaitable[None]]


class TranscriptionProvider(ABC):
    """Produces a transcript for one meeting."""

    #: Identifier used in configuration and status output.
    name: str = "unknown"

    @property
    @abstractmethod
    def status(self) -> TranscriptionStatus:
        """Current lifecycle state."""

    @property
    @abstractmethod
    def stats(self) -> TranscriptionStats:
        """Counters for this run."""

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    @abstractmethod
    async def start(self, sink: SegmentSink) -> None:
        """Begin producing segments into ``sink``.

        Returns once production has started; it does not block for the meeting.

        Raises:
            TranscriptionError: If the source cannot be started.
        """

    @abstractmethod
    async def stop(self) -> list[TranscriptSegment]:
        """Stop producing and return the full transcript.

        Safe to call when not running, in which case it returns whatever was
        produced earlier.
        """

    @abstractmethod
    def segments(self) -> list[TranscriptSegment]:
        """The transcript so far, without stopping."""
