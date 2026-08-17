"""Reconnection strategy with exponential backoff for WebSocket resilience."""

import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Enumeration for error categorization."""
    TRANSIENT = "transient"  # Temporary network issues (timeout, connection reset)
    PERMANENT = "permanent"  # Permanent errors (invalid URL, auth failure)


class ReconnectionStrategy:
    """Manages exponential backoff calculation and attempt tracking for WebSocket reconnection.
    
    Encapsulates:
    - Exponential backoff delay calculation with configurable initial delay and backoff factor
    - Attempt counting and tracking
    - Transient vs. permanent error differentiation
    - Maximum retry limits and maximum delay caps
    """
    
    def __init__(
        self,
        initial_delay_ms: int = 1000,
        backoff_factor: float = 2.0,
        max_delay_ms: int = 30000,
        max_attempts: int = 5
    ):
        """Initialize ReconnectionStrategy with backoff parameters.
        
        Args:
            initial_delay_ms: Initial delay in milliseconds (default 1000ms)
            backoff_factor: Factor to multiply delay by for each retry (default 2.0)
            max_delay_ms: Maximum delay cap in milliseconds (default 30000ms)
            max_attempts: Maximum number of reconnection attempts (default 5)
        """
        self.initial_delay_ms = initial_delay_ms
        self.backoff_factor = backoff_factor
        self.max_delay_ms = max_delay_ms
        self.max_attempts = max_attempts
        
        # State tracking
        self.attempt_count = 0
        self.current_delay_ms = initial_delay_ms
    
    def record_attempt(self) -> None:
        """Record a reconnection attempt and update delay for next retry.
        
        Increments attempt counter and calculates next delay using exponential backoff,
        capped at max_delay_ms.
        """
        self.attempt_count += 1
        # Calculate next delay: delay * backoff_factor, capped at max_delay_ms
        self.current_delay_ms = min(
            int(self.current_delay_ms * self.backoff_factor),
            self.max_delay_ms
        )
        logger.debug(
            f"Reconnection attempt {self.attempt_count}: "
            f"next delay {self.current_delay_ms}ms"
        )
    
    def get_delay_ms(self) -> int:
        """Get the current delay in milliseconds.
        
        Returns:
            int: Current delay in milliseconds (exponentially backed off from initial_delay_ms)
        """
        return self.current_delay_ms
    
    def get_delay_seconds(self) -> float:
        """Get the current delay in seconds.
        
        Returns:
            float: Current delay converted to seconds (current_delay_ms / 1000)
        """
        return self.current_delay_ms / 1000.0
    
    def should_retry(self, error_type: ErrorType = ErrorType.TRANSIENT) -> bool:
        """Determine if reconnection should be retried based on error type and attempt count.
        
        Args:
            error_type: Type of error encountered (transient or permanent)
            
        Returns:
            bool: True if reconnection should be retried, False if max attempts reached
                  or if permanent error encountered.
        """
        # Permanent errors should not be retried
        if error_type == ErrorType.PERMANENT:
            logger.warning(
                f"Permanent error encountered; stopping reconnection attempts "
                f"(attempted {self.attempt_count} times)"
            )
            return False
        
        # Transient errors can be retried if under max attempts
        if self.attempt_count >= self.max_attempts:
            logger.error(
                f"Maximum reconnection attempts ({self.max_attempts}) reached; "
                f"stopping reconnection"
            )
            return False
        
        return True
    
    def reset(self) -> None:
        """Reset the strategy to initial state for a new connection attempt sequence.
        
        Resets attempt counter and delay to initial values.
        """
        self.attempt_count = 0
        self.current_delay_ms = self.initial_delay_ms
        logger.debug("Reconnection strategy reset to initial state")
    
    def is_exhausted(self) -> bool:
        """Check if maximum reconnection attempts have been exhausted.
        
        Returns:
            bool: True if attempt_count >= max_attempts, False otherwise.
        """
        return self.attempt_count >= self.max_attempts
    
    def get_attempt_count(self) -> int:
        """Get the current reconnection attempt count.
        
        Returns:
            int: Number of reconnection attempts made so far.
        """
        return self.attempt_count

