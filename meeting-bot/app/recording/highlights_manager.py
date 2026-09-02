"""Incremental meeting highlights generation.

Supports generating highlights for partial recordings, enabling incremental
processing of long meetings. Tracks which segments have been processed and
generates highlights only for new duration ranges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.clients.cw_utils import CWUtilsClient
from app.recording.models import RecordingContext, RecordingStats

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HighlightSegment:
    """One segment of a recording that has been processed for highlights."""

    segment_id: str
    meeting_id: str
    project_id: str | None
    duration_seconds: float
    start_seconds: float = 0.0
    audio_filename: str = ""
    request_id: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        """Serialize for logging or storage."""
        return {
            "segment_id": self.segment_id,
            "meeting_id": self.meeting_id,
            "project_id": self.project_id,
            "duration_seconds": self.duration_seconds,
            "start_seconds": self.start_seconds,
            "audio_filename": self.audio_filename,
            "request_id": self.request_id,
            "generated_at": self.generated_at.isoformat(),
        }


class HighlightsManager:
    """Manages incremental highlight generation for recorded meetings.

    When a long meeting is recorded, highlights can be generated in segments
    rather than waiting for the entire recording to complete. This manager
    tracks which portions of a recording have been processed and generates
    highlights incrementally.
    """

    def __init__(
        self,
        *,
        cw_client: CWUtilsClient,
        min_duration_seconds: float = 60.0,
    ) -> None:
        """
        Args:
            cw_client: Client for CW API calls.
            min_duration_seconds: Minimum recording duration before highlights are generated.
        """
        self._cw = cw_client
        self._min_duration = min_duration_seconds
        self._segments: dict[str, HighlightSegment] = {}
        self._processed_duration: dict[str, float] = {}

    def should_generate_highlights(
        self,
        meeting_id: str,
        current_duration_seconds: float,
    ) -> bool:
        """Check if highlights should be generated for the current duration.

        Highlights are generated when:
        1. The minimum duration threshold is met
        2. Significant new duration has been added since the last generation

        Args:
            meeting_id: The meeting identifier.
            current_duration_seconds: Total recorded duration in seconds.

        Returns:
            True if highlights should be generated now.
        """
        if current_duration_seconds < self._min_duration:
            return False

        # Generate highlights if this is the first segment or if we've added
        # substantial new duration (e.g., 50% more)
        last_processed = self._processed_duration.get(meeting_id, 0.0)
        duration_increase = current_duration_seconds - last_processed
        min_increase = self._min_duration * 0.5

        return duration_increase >= min_increase

    async def generate_incremental_highlights(
        self,
        context: RecordingContext,
        stats: RecordingStats,
        audio_filename: str,
        segment_number: int = 1,
        is_final: bool = False,
    ) -> HighlightSegment | None:
        """Generate highlights for the current recording state.

        Args:
            context: Recording context with user and project information.
            stats: Recording statistics including duration.
            audio_filename: Name of the audio file in storage.
            segment_number: Which incremental segment this is (1, 2, 3, ...).
            is_final: True when this segment ends the meeting. The duration
                threshold is skipped in that case: the tail of a meeting is
                whatever is left after the last boundary, so holding it to a
                minimum length would silently drop the closing segment.

        Returns:
            HighlightSegment if generation was requested, None if skipped.

        Raises:
            ExternalServiceError: If CW rejects the request.
        """
        assert context.project_id is not None

        if not is_final and not self.should_generate_highlights(
            context.meeting_id, stats.duration_seconds
        ):
            logger.debug(
                "Skipping highlights: insufficient duration",
                extra={
                    "meeting_id": context.meeting_id,
                    "duration_seconds": stats.duration_seconds,
                    "min_duration_seconds": self._min_duration,
                },
            )
            return None

        segment_id = f"{context.meeting_id}-segment-{segment_number}"
        display_name = f"{context.meeting_title or context.meeting_id} (Part {segment_number})"

        # Where the previous segment ended, which is where this one begins.
        # Recorded before the bookkeeping below overwrites it.
        last_duration = self._processed_duration.get(context.meeting_id, 0.0)

        incremental_mh_metadata = {
            "meeting_id": context.meeting_id,
            "segment_number": segment_number,
            "last_duration": last_duration,
            "is_final": is_final,
        }

        logger.info(
            "Generating incremental highlights",
            extra={
                "segment_id": segment_id,
                "meeting_id": context.meeting_id,
                "duration_seconds": stats.duration_seconds,
                "last_duration": last_duration,
                "is_final": is_final,
            },
        )

        try:
            result = await self._cw.generate_meeting_artifact(
                audio_name=audio_filename,
                project_id=context.project_id,
                display_name=display_name,
                user_email=context.user_email,
                user_name=context.user_name,
                request_id=segment_id,
                incremental_mh_metadata=incremental_mh_metadata,
                mode_ids=context.mode_ids,
            )
        except Exception as error:
            logger.warning(
                "Failed to request incremental highlights",
                exc_info=error,
                extra={"segment_id": segment_id, "meeting_id": context.meeting_id},
            )
            return None

        segment = HighlightSegment(
            segment_id=segment_id,
            meeting_id=context.meeting_id,
            project_id=context.project_id,
            duration_seconds=stats.duration_seconds,
            start_seconds=last_duration,
            audio_filename=audio_filename,
            request_id=result.get("request_id"),
        )

        self._segments[segment_id] = segment
        self._processed_duration[context.meeting_id] = stats.duration_seconds

        logger.info(
            "Incremental highlights requested",
            extra={"segment_id": segment_id, **segment.as_dict()},
        )

        return segment

    def get_segment(self, segment_id: str) -> HighlightSegment | None:
        """Retrieve a processed segment by ID."""
        return self._segments.get(segment_id)

    def get_meeting_segments(self, meeting_id: str) -> list[HighlightSegment]:
        """Get all processed segments for a meeting."""
        return [
            seg
            for seg in self._segments.values()
            if seg.meeting_id == meeting_id
        ]
