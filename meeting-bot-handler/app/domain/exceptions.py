from __future__ import annotations

from typing import Any, Dict, Optional


class DomainException(Exception):
    """Base exception for all domain and business logic errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Session Exceptions
class SessionNotFoundError(DomainException):
    """Raised when a requested session_id or meeting_id does not exist."""

    def __init__(self, message: str = "Session not found", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class SessionAlreadyExistsError(DomainException):
    """Raised when attempting to create a session that already exists."""

    def __init__(self, message: str = "Session already exists", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class InvalidSessionStateError(DomainException):
    """Raised when an operation is attempted in an invalid state transition."""

    def __init__(self, message: str = "Invalid session state transition", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


# Bot Target & Service Resolver Exceptions
class BotServiceNotAssignedError(DomainException):
    """Raised when a session does not have a resolved bot_service_url or target worker."""

    def __init__(self, message: str = "Bot service URL not assigned to session", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class BotServiceUnavailableError(DomainException):
    """Raised when the resolved target worker bot pod is unreachable or non-responsive."""

    def __init__(self, message: str = "Worker bot service is unavailable", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


# Worker Bot API Response Exceptions
class BotOperationError(DomainException):
    """Raised when the worker bot API returns an error response."""

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


# Recording & Transcription Specific Exceptions
class RecordingOperationError(BotOperationError):
    """Raised when a recording lifecycle command fails."""
    pass


class TranscriptionOperationError(BotOperationError):
    """Raised when a transcription lifecycle command fails."""
    pass