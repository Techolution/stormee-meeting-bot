class DomainError(Exception):
    """Base domain exception."""


class InvalidStateTransition(DomainError):
    """Raised when a bot session state transition is invalid."""


class BotSessionNotFound(DomainError):
    """Raised when a requested bot session does not exist."""
