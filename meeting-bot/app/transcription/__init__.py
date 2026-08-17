"""Transcription.

Meeting code starts and stops a :class:`TranscriptionProvider`. It never learns
that today's text comes from scraping the caption area — which is what makes
moving to speech-to-text over the recorded audio a configuration change rather
than a rewrite.
"""

from app.transcription.base import SegmentSink, TranscriptionProvider
from app.transcription.caption_aggregator import CaptionAggregator
from app.transcription.caption_provider import CaptionTranscriptionProvider
from app.transcription.models import (
    TranscriptionStats,
    TranscriptionStatus,
    TranscriptSegment,
    TranscriptSource,
)
from app.transcription.provider import available_providers, create_provider, register_provider

__all__ = [
    "CaptionAggregator",
    "CaptionTranscriptionProvider",
    "SegmentSink",
    "TranscriptSegment",
    "TranscriptSource",
    "TranscriptionProvider",
    "TranscriptionStats",
    "TranscriptionStatus",
    "available_providers",
    "create_provider",
    "register_provider",
]
