"""Legacy-compatible buffering for live meeting captions.

Every poll replaces the previous snapshot. Stopping returns only the caption
rows that are visible at that moment, matching the legacy bot exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.meeting_platform.models import CaptionLine
from app.transcription.models import TranscriptSegment, TranscriptSource


@dataclass(slots=True)
class CaptionAggregator:
    """Keep only the latest ordered caption DOM snapshot."""

    _live: list[TranscriptSegment] = field(default_factory=list)
    _completed: list[TranscriptSegment] = field(default_factory=list)
    _suppressed: int = 0

    @property
    def suppressed_count(self) -> int:
        return self._suppressed

    def ingest(self, snapshot: list[CaptionLine]) -> list[TranscriptSegment]:
        """Replace the live buffer; legacy mode emits nothing while polling."""
        current: list[TranscriptSegment] = []
        for line in snapshot:
            if line.is_empty:
                continue
            segment = TranscriptSegment(
                speaker=line.speaker or "Unknown",
                text=line.text.strip(),
                source=TranscriptSource.CAPTION,
                created_at=line.captured_at,
            )
            if current and current[-1].text == segment.text:
                self._suppressed += 1
                continue
            current.append(segment)
        self._live = current
        return []

    def flush(self) -> list[TranscriptSegment]:
        """Freeze and return the most recent visible caption snapshot."""
        remaining = list(self._live)
        self._live.clear()
        self._completed = remaining
        return remaining

    def transcript(self) -> list[TranscriptSegment]:
        """Return the frozen result, or the current snapshot while running."""
        return list(self._completed or self._live)

    def reset(self) -> None:
        self._live.clear()
        self._completed.clear()
        self._suppressed = 0
