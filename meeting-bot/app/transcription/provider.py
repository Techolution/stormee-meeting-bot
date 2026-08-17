"""Transcription provider selection.

One place that maps a configured provider name to an implementation. Meeting
code asks for "the configured provider" and gets one; it never names a class.
That is what makes the eventual captions-to-speech-recognition migration a
configuration change rather than a refactor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.config import TranscriptionSettings
from app.core.exceptions import UnsupportedProviderError
from app.meeting_platform.base import MeetingPlatform
from app.transcription.base import TranscriptionProvider
from app.transcription.caption_provider import CaptionTranscriptionProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[MeetingPlatform, str, TranscriptionSettings], TranscriptionProvider]


def _build_caption_provider(
    platform: MeetingPlatform,
    meeting_id: str,
    settings: TranscriptionSettings,
) -> TranscriptionProvider:
    return CaptionTranscriptionProvider(
        platform=platform,
        meeting_id=meeting_id,
        poll_interval_seconds=settings.poll_interval_seconds,
    )


_PROVIDERS: dict[str, ProviderFactory] = {
    "caption": _build_caption_provider,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register an implementation under a configuration name.

    Exposed so a speech-to-text provider can be added without editing this
    module.
    """
    _PROVIDERS[name] = factory
    logger.debug("Registered transcription provider", extra={"provider": name})


def create_provider(
    platform: MeetingPlatform,
    meeting_id: str,
    settings: TranscriptionSettings,
) -> TranscriptionProvider:
    """Build the configured provider.

    Raises:
        UnsupportedProviderError: If the configured name is not registered.
    """
    factory = _PROVIDERS.get(settings.provider)
    if factory is None:
        raise UnsupportedProviderError(
            f"unknown transcription provider {settings.provider!r}; "
            f"available: {', '.join(sorted(_PROVIDERS))}"
        )

    logger.debug(
        "Creating transcription provider",
        extra={"provider": settings.provider, "meeting_id": meeting_id},
    )
    return factory(platform, meeting_id, settings)


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)
