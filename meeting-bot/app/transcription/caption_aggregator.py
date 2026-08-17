"""Turning live captions into a transcript.

Meet's caption area is not a log. It shows two or three blocks, rewrites them
in place as a speaker continues, and drops them once they scroll away. Polling
it produces a stream of overlapping snapshots, not a sequence of utterances.

The naive readings both fail:

  * Appending every snapshot produces a transcript where each sentence appears
    once per poll.
  * Keeping only the newest snapshot — which the previous implementation did —
    produces a transcript containing the last few seconds of the meeting and
    nothing else.

This aggregator reconstructs utterances instead. It tracks each speaker's
in-progress block across snapshots, merges each new reading into the text it
already has, and emits a finished segment when the block disappears.

The merge handles the three ways Meet rewrites a block:

  ``extension``  New text extends what was there: take the new text.
  ``redraw``     New text is a prefix of what was there, mid-re-render: keep the longer.
  ``scroll``     Meet dropped the start of a long utterance, so the new text
                 overlaps the tail of the old. Splice on the overlap.

No overlap at all means the speaker started something new, so the previous
block is finished and emitted.

Pure and synchronous, so the rules above are directly testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.meeting_platform.models import CaptionLine
from app.transcription.models import TranscriptSegment, TranscriptSource

logger = logging.getLogger(__name__)

#: Shorter overlaps than this are coincidence — common words repeat — and
#: splicing on them corrupts the text.
_MIN_OVERLAP_CHARS = 8


@dataclass(slots=True)
class _ActiveBlock:
    """A caption block still being spoken."""

    speaker: str
    text: str
    started_at: datetime
    last_seen_at: datetime

    def to_segment(self) -> TranscriptSegment:
        return TranscriptSegment(
            speaker=self.speaker,
            text=self.text.strip(),
            source=TranscriptSource.CAPTION,
            created_at=self.started_at,
        )


@dataclass(slots=True)
class CaptionAggregator:
    """Reassembles overlapping caption snapshots into utterances."""

    _active: dict[str, _ActiveBlock] = field(default_factory=dict)
    _completed: list[TranscriptSegment] = field(default_factory=list)
    _suppressed: int = 0

    @property
    def suppressed_count(self) -> int:
        """Snapshot readings absorbed into an existing block rather than emitted."""
        return self._suppressed

    def ingest(self, snapshot: list[CaptionLine]) -> list[TranscriptSegment]:
        """Fold one snapshot in and return any utterances it completed.

        Args:
            snapshot: The caption area's current contents.

        Returns:
            Segments finished by this snapshot, in the order they were spoken.
            Usually empty — a segment completes only when its block leaves the
            caption area.
        """
        now = datetime.now(timezone.utc)
        finished: list[TranscriptSegment] = []
        seen_speakers: set[str] = set()

        for line in snapshot:
            if line.is_empty:
                continue

            speaker = line.speaker or "Unknown"
            text = line.text.strip()
            seen_speakers.add(speaker)

            block = self._active.get(speaker)
            if block is None:
                self._active[speaker] = _ActiveBlock(
                    speaker=speaker, text=text, started_at=line.captured_at, last_seen_at=now
                )
                continue

            merged = _merge(block.text, text)
            if merged is None:
                # Unrelated text: the previous utterance is over.
                finished.append(block.to_segment())
                self._active[speaker] = _ActiveBlock(
                    speaker=speaker, text=text, started_at=line.captured_at, last_seen_at=now
                )
                continue

            if merged == block.text:
                self._suppressed += 1
            block.text = merged
            block.last_seen_at = now

        # A block absent from this snapshot has scrolled out: the utterance ended.
        for speaker in [s for s in self._active if s not in seen_speakers]:
            finished.append(self._active.pop(speaker).to_segment())

        finished = [segment for segment in finished if segment.text]
        self._completed.extend(finished)

        if finished:
            logger.debug(
                "Caption segments completed",
                extra={"count": len(finished), "speakers": [s.speaker for s in finished]},
            )

        return finished

    def flush(self) -> list[TranscriptSegment]:
        """Close every in-progress block and return the finished segments.

        Called when transcription stops, so the last thing said is not lost.
        """
        remaining = [block.to_segment() for block in self._active.values()]
        remaining = [segment for segment in remaining if segment.text]
        self._active.clear()
        self._completed.extend(remaining)
        return remaining

    def transcript(self) -> list[TranscriptSegment]:
        """Everything completed so far, in spoken order."""
        return sorted(self._completed, key=lambda segment: segment.created_at)

    def reset(self) -> None:
        self._active.clear()
        self._completed.clear()
        self._suppressed = 0


def _merge(existing: str, incoming: str) -> str | None:
    """Combine a block's known text with a new reading of it.

    Returns:
        The merged text, or ``None`` if the two are unrelated — meaning the
        speaker began a new utterance and the old one should be emitted.
    """
    if incoming == existing:
        return existing

    # Extension: the common case, a block growing as speech continues.
    if incoming.startswith(existing):
        return incoming

    # Redraw: a partial re-render briefly shows less than we already have.
    if existing.startswith(incoming):
        return existing

    # Scroll: Meet dropped the head of a long utterance. Find where the new
    # reading picks up within the old text and splice there.
    overlap = _longest_overlap(existing, incoming)
    if overlap >= _MIN_OVERLAP_CHARS:
        return existing + incoming[overlap:]

    return None


def _longest_overlap(existing: str, incoming: str) -> int:
    """Length of the longest suffix of ``existing`` that prefixes ``incoming``."""
    limit = min(len(existing), len(incoming))
    for size in range(limit, 0, -1):
        if existing.endswith(incoming[:size]):
            return size
    return 0
