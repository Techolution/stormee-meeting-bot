"""Application exceptions.

Each carries a stable ``code``. The API layer maps the code to an HTTP status
and puts it in the response envelope, so callers branch on the code rather than
parsing prose — the same contract the bot API offers the handler.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class DomainException(Exception):
    """Base exception for all domain and business logic errors."""

    code = "internal_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Session Exceptions
class SessionNotFoundError(DomainException):
    """Raised when a requested session_id or meeting_id does not exist."""

    code = "session_not_found"

    def __init__(self, message: str = "Session not found", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class SessionAlreadyExistsError(DomainException):
    """Raised when attempting to create a session that already exists."""

    code = "session_already_exists"

    def __init__(self, message: str = "Session already exists", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class InvalidSessionStateError(DomainException):
    """Raised when an operation is attempted in an invalid state transition."""

    code = "invalid_session_state"

    def __init__(self, message: str = "Invalid session state transition", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


# Bot Target & Service Resolver Exceptions
class BotServiceNotAssignedError(DomainException):
    """Raised when a session has no bot pod assigned to it yet."""

    code = "bot_service_not_assigned"

    def __init__(self, message: str = "No bot pod assigned to this session", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class NoBotPodAvailableError(DomainException):
    """Raised when every bot pod in the cluster is busy or unreachable.

    Distinct from an unassigned session: the cluster was asked and had nothing
    to give. The right response is to retry later or scale the Deployment.
    """

    code = "no_bot_pod_available"

    def __init__(self, message: str = "No bot pod is available to take this meeting", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class BotServiceUnavailableError(DomainException):
    """Raised when the assigned bot pod is unreachable or non-responsive."""

    code = "bot_service_unavailable"

    def __init__(self, message: str = "Bot pod is unreachable", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class ClusterUnavailableError(DomainException):
    """Raised when the Kubernetes API cannot be reached or is not configured."""

    code = "cluster_unavailable"

    def __init__(self, message: str = "Kubernetes API is unavailable", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


# Worker Bot API Response Exceptions
class BotOperationError(DomainException):
    """Raised when the bot API returns an error response.

    ``code`` is the bot's own error code, forwarded unchanged so a caller of the
    handler sees the same taxonomy the bot documents.
    """

    def __init__(
        self,
        message: str,
        code: str = "internal_error",
        status_code: int = 500,
        request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, details)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id

    def __str__(self) -> str:
        return f"[{self.status_code}] {self.code}: {self.message}"


# Recording & Transcription Specific Exceptions
class RecordingOperationError(BotOperationError):
    """Raised when a recording lifecycle command fails."""


class TranscriptionOperationError(BotOperationError):
    """Raised when a transcription lifecycle command fails."""
