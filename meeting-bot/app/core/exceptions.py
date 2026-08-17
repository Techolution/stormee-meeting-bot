"""Domain exception hierarchy.

Every failure the application raises deliberately derives from
:class:`MeetingBotError`. That gives the API layer one place to translate
failures into HTTP responses (see :mod:`app.api.errors`) and gives callers a
way to distinguish "this component said no" from "something unexpected broke".

Each exception carries an HTTP status and a stable machine-readable ``code`` so
clients can branch on the code rather than on message text.
"""

from __future__ import annotations

from typing import Any


class MeetingBotError(Exception):
    """Base class for every error this service raises on purpose."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class ConfigurationError(MeetingBotError):
    """A required setting is missing or self-contradictory."""

    status_code = 500
    code = "configuration_error"


# --------------------------------------------------------------------------
# Meeting lifecycle
# --------------------------------------------------------------------------


class MeetingError(MeetingBotError):
    """Base for meeting-lifecycle failures."""

    status_code = 500
    code = "meeting_error"


class MeetingNotFoundError(MeetingError):
    """No active session for the requested meeting id."""

    status_code = 404
    code = "meeting_not_found"

    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"No active session for meeting {meeting_id!r}",
            details={"meeting_id": meeting_id},
        )


class MeetingAlreadyActiveError(MeetingError):
    """A session for this meeting id is already running."""

    status_code = 409
    code = "meeting_already_active"

    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"Meeting {meeting_id!r} already has an active session",
            details={"meeting_id": meeting_id},
        )


class MeetingJoinError(MeetingError):
    """The bot could not get into the meeting room."""

    status_code = 502
    code = "meeting_join_failed"


class MeetingAdmissionTimeoutError(MeetingJoinError):
    """The bot reached the lobby but was never admitted."""

    code = "meeting_admission_timeout"

    def __init__(self, meeting_id: str, waited_seconds: float) -> None:
        super().__init__(
            f"Timed out after {waited_seconds:.0f}s waiting to be admitted to {meeting_id!r}",
            details={"meeting_id": meeting_id, "waited_seconds": waited_seconds},
        )


class AuthenticationRequiredError(MeetingJoinError):
    """The meeting refuses anonymous participants and no signed-in profile is available."""

    status_code = 403
    code = "authentication_required"


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------


class BrowserError(MeetingBotError):
    """Base for browser-automation failures."""

    status_code = 500
    code = "browser_error"


class BrowserLaunchError(BrowserError):
    """Chromium would not start, or every launch attempt failed."""

    code = "browser_launch_failed"


class BrowserNotAvailableError(BrowserError):
    """An operation needed a live page and there was none."""

    status_code = 409
    code = "browser_not_available"


class ElementNotFoundError(BrowserError):
    """An expected element never appeared. Usually a platform UI change."""

    status_code = 502
    code = "element_not_found"

    def __init__(self, description: str, *, selector: str | None = None) -> None:
        super().__init__(
            f"Could not find {description}",
            details={"selector": selector} if selector else {},
        )


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


class RecordingError(MeetingBotError):
    """Base for capture and upload failures."""

    status_code = 500
    code = "recording_error"


class RecordingAlreadyActiveError(RecordingError):
    status_code = 409
    code = "recording_already_active"


class RecordingNotActiveError(RecordingError):
    status_code = 409
    code = "recording_not_active"


class ChunkUploadError(RecordingError):
    """A chunk could not be persisted to object storage."""

    status_code = 502
    code = "chunk_upload_failed"


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------


class TranscriptionError(MeetingBotError):
    status_code = 500
    code = "transcription_error"


class TranscriptionNotActiveError(TranscriptionError):
    status_code = 409
    code = "transcription_not_active"


class UnsupportedProviderError(TranscriptionError):
    status_code = 500
    code = "unsupported_transcription_provider"


# --------------------------------------------------------------------------
# External services
# --------------------------------------------------------------------------


class ExternalServiceError(MeetingBotError):
    """A dependency we call over the network failed."""

    status_code = 502
    code = "external_service_error"

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"service": service, **(details or {})}
        if status is not None:
            merged["upstream_status"] = status
        super().__init__(f"{service}: {message}", details=merged)
        self.service = service
        self.upstream_status = status


class WebSocketError(MeetingBotError):
    status_code = 502
    code = "websocket_error"


class WebSocketNotConnectedError(WebSocketError):
    status_code = 409
    code = "websocket_not_connected"


# --------------------------------------------------------------------------
# Platform abstraction
# --------------------------------------------------------------------------


class UnsupportedPlatformError(MeetingBotError):
    """The meeting URL does not map to any implemented platform."""

    status_code = 400
    code = "unsupported_platform"

    def __init__(self, meeting_url: str) -> None:
        super().__init__(
            f"No meeting platform implementation matches {meeting_url!r}",
            details={"meeting_url": meeting_url},
        )
