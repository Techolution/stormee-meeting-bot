"""Retry Manager - Handles idempotent retries for failed uploads.

Tracks failed chunks and implements exponential backoff with circuit breaker
to prevent cascading failures during network issues.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ErrorClassification(Enum):
    """Classifies errors as transient or permanent."""
    TRANSIENT = "transient"  # Network, timeout, 5xx - retry
    PERMANENT = "permanent"  # Invalid data, 4xx - don't retry
    UNKNOWN = "unknown"      # Default - treat as transient


class CircuitBreakerState(Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Too many failures, stop retrying
    HALF_OPEN = "half_open"  # Trying recovery


@dataclass
class RetryableChunk:
    """Tracks state of a chunk awaiting retry."""
    session_id: str
    sequence_number: int
    attempt: int = 0
    first_failure_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_attempt_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    error_classification: ErrorClassification = ErrorClassification.UNKNOWN
    error_message: str = ""
    total_backoff_ms: int = 0  # Total time spent backing off
    
    def get_backoff_ms(self) -> int:
        """Calculate exponential backoff: 1s, 2s, 4s, 8s, max 30s."""
        base_ms = 1000  # 1 second
        exponent = min(self.attempt, 4)  # Cap at 2^4 = 16s base
        backoff_ms = base_ms * (2 ** exponent)
        return min(backoff_ms, 30000)  # Cap at 30 seconds
    
    def should_retry_now(self) -> bool:
        """Check if enough time has passed to retry."""
        if self.next_retry_at is None:
            return True
        return datetime.now(timezone.utc) >= self.next_retry_at
    
    def schedule_next_retry(self) -> None:
        """Schedule next retry with exponential backoff."""
        backoff_ms = self.get_backoff_ms()
        self.next_retry_at = datetime.now(timezone.utc) + timedelta(milliseconds=backoff_ms)
        self.total_backoff_ms += backoff_ms


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures.
    
    States:
    - CLOSED: Normal, no failures
    - OPEN: Too many failures in window, stop retrying
    - HALF_OPEN: Attempting recovery after delay
    """
    
    def __init__(
        self,
        failure_threshold: int = 10,
        recovery_timeout_sec: int = 60,
        window_sec: int = 300,
    ):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures needed to open circuit
            recovery_timeout_sec: Wait before trying recovery
            window_sec: Time window for counting failures
        """
        self.state = CircuitBreakerState.CLOSED
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.window_sec = window_sec
        
        self.failures = []  # List of failure timestamps
        self.last_opened_at: Optional[datetime] = None
        self.last_half_open_at: Optional[datetime] = None
    
    def record_failure(self) -> None:
        """Record a failure and check if circuit should open."""
        now = datetime.now(timezone.utc)
        self.failures.append(now)
        
        # Remove old failures outside window
        cutoff = now - timedelta(seconds=self.window_sec)
        self.failures = [f for f in self.failures if f > cutoff]
        
        # Open circuit if threshold exceeded
        if len(self.failures) >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.last_opened_at = now
            logger.warning(
                f"[CircuitBreaker] OPENED after {len(self.failures)} failures in {self.window_sec}s"
            )
    
    def record_success(self) -> None:
        """Record success and reset state."""
        self.failures = []
        self.state = CircuitBreakerState.CLOSED
        logger.info("[CircuitBreaker] CLOSED - recovery successful")
    
    def should_allow_retry(self) -> bool:
        """Check if retry is allowed based on circuit breaker state."""
        now = datetime.now(timezone.utc)
        
        if self.state == CircuitBreakerState.CLOSED:
            return True
        
        if self.state == CircuitBreakerState.OPEN:
            # Try recovery after timeout
            if self.last_opened_at:
                elapsed = (now - self.last_opened_at).total_seconds()
                if elapsed > self.recovery_timeout_sec:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.last_half_open_at = now
                    logger.info("[CircuitBreaker] HALF_OPEN - attempting recovery")
                    return True
            return False
        
        # HALF_OPEN: allow one retry to test
        return True


class RetryManager:
    """Manages idempotent retries for failed chunks.
    
    Uses (sessionId, sequenceNumber) as unique identity for deduplication.
    """
    
    def __init__(
        self,
        meeting_id: str,
        max_retries: int = 5,
        max_total_backoff_sec: int = 300,  # 5 minutes max
        on_retry_exhausted: Optional[Callable[[RetryableChunk], None]] = None,
    ):
        """Initialize retry manager.
        
        Args:
            meeting_id: Meeting identifier
            max_retries: Maximum retry attempts per chunk
            max_total_backoff_sec: Maximum total backoff time across retries
            on_retry_exhausted: Callback when retries exhausted
        """
        self.meeting_id = meeting_id
        self.max_retries = max_retries
        self.max_total_backoff_sec = max_total_backoff_sec * 1000  # Convert to ms
        self.on_retry_exhausted = on_retry_exhausted
        
        # Retry tracking: (session_id, sequence_number) -> RetryableChunk
        self.retry_queue: dict[tuple[str, int], RetryableChunk] = {}
        
        # Circuit breaker for upload service
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=10,
            recovery_timeout_sec=60,
            window_sec=300,
        )
        
        # Metrics
        self.total_retries_attempted = 0
        self.total_retries_succeeded = 0
        self.total_retries_failed = 0
        self.chunks_permanently_failed = 0
        
        logger.info(
            f"[RetryManager] Initialized for meeting {meeting_id}, "
            f"max_retries={max_retries}, max_backoff={max_total_backoff_sec}ms"
        )
    
    def classify_error(self, error: Exception, http_status: Optional[int] = None) -> ErrorClassification:
        """Classify error as transient or permanent.
        
        Args:
            error: Exception that occurred
            http_status: HTTP status code if available
        
        Returns:
            ErrorClassification
        """
        if http_status:
            if 500 <= http_status < 600:
                return ErrorClassification.TRANSIENT  # Server error - retry
            elif http_status == 429:
                return ErrorClassification.TRANSIENT  # Rate limited - retry
            elif 400 <= http_status < 500:
                return ErrorClassification.PERMANENT  # Client error - don't retry
        
        # Classify by exception type
        error_msg = str(error).lower()
        if any(x in error_msg for x in ["timeout", "connection", "network", "refused"]):
            return ErrorClassification.TRANSIENT
        
        # Default to transient (better to retry than lose data)
        return ErrorClassification.UNKNOWN
    
    def record_failure(
        self,
        session_id: str,
        sequence_number: int,
        error: Exception,
        http_status: Optional[int] = None,
    ) -> bool:
        """Record chunk upload failure.
        
        Args:
            session_id: Session ID
            sequence_number: Chunk sequence number
            error: Exception that occurred
            http_status: HTTP status code if available
        
        Returns:
            True if chunk will be retried, False if retries exhausted
        """
        key = (session_id, sequence_number)
        
        # Get or create retry entry
        if key not in self.retry_queue:
            self.retry_queue[key] = RetryableChunk(
                session_id=session_id,
                sequence_number=sequence_number,
            )
        
        chunk = self.retry_queue[key]
        chunk.attempt += 1
        chunk.last_attempt_at = datetime.now(timezone.utc)
        chunk.error_classification = self.classify_error(error, http_status)
        chunk.error_message = str(error)
        
        # Record in circuit breaker
        self.circuit_breaker.record_failure()
        
        # Check if permanent failure
        if chunk.error_classification == ErrorClassification.PERMANENT:
            logger.warning(
                f"[RetryManager] Permanent failure for seq={sequence_number}: {error}"
            )
            self.chunks_permanently_failed += 1
            del self.retry_queue[key]
            return False
        
        # Check if max retries exceeded
        if chunk.attempt > self.max_retries:
            logger.error(
                f"[RetryManager] Exhausted retries for seq={sequence_number} "
                f"after {chunk.attempt} attempts"
            )
            self.chunks_permanently_failed += 1
            if self.on_retry_exhausted:
                self.on_retry_exhausted(chunk)
            del self.retry_queue[key]
            return False
        
        # Check if total backoff exceeded
        if chunk.total_backoff_ms > self.max_total_backoff_sec:
            logger.error(
                f"[RetryManager] Exceeded max backoff for seq={sequence_number} "
                f"({chunk.total_backoff_ms}ms > {self.max_total_backoff_sec}ms)"
            )
            self.chunks_permanently_failed += 1
            if self.on_retry_exhausted:
                self.on_retry_exhausted(chunk)
            del self.retry_queue[key]
            return False
        
        # Schedule retry
        chunk.schedule_next_retry()
        self.total_retries_attempted += 1
        
        logger.info(
            f"[RetryManager] Scheduled retry for seq={sequence_number}, "
            f"attempt={chunk.attempt}, next_retry_in={chunk.get_backoff_ms()}ms"
        )
        
        return True
    
    def record_success(self, session_id: str, sequence_number: int) -> None:
        """Record successful upload.
        
        Args:
            session_id: Session ID
            sequence_number: Chunk sequence number
        """
        key = (session_id, sequence_number)
        
        if key in self.retry_queue:
            chunk = self.retry_queue[key]
            logger.info(
                f"[RetryManager] Retry successful for seq={sequence_number} "
                f"after {chunk.attempt} attempts"
            )
            self.total_retries_succeeded += 1
            del self.retry_queue[key]
        
        # Reset circuit breaker on success
        if self.circuit_breaker.state != CircuitBreakerState.CLOSED:
            self.circuit_breaker.record_success()
    
    def get_chunks_ready_for_retry(self) -> list[tuple[str, int]]:
        """Get chunks that should be retried now.
        
        Returns:
            List of (session_id, sequence_number) tuples
        """
        # Check circuit breaker first
        if not self.circuit_breaker.should_allow_retry():
            return []
        
        ready = []
        for (session_id, seq), chunk in list(self.retry_queue.items()):
            if chunk.should_retry_now():
                ready.append((session_id, seq))
        
        return ready
    
    def can_retry_now(self, session_id: str, sequence_number: int) -> bool:
        """Check if a specific chunk can be retried now.
        
        Args:
            session_id: Session ID
            sequence_number: Chunk sequence number
        
        Returns:
            True if ready to retry
        """
        if not self.circuit_breaker.should_allow_retry():
            return False
        
        key = (session_id, sequence_number)
        if key not in self.retry_queue:
            return False
        
        return self.retry_queue[key].should_retry_now()
    
    def get_retry_state(self, session_id: str, sequence_number: int) -> Optional[dict]:
        """Get current retry state for a chunk.
        
        Args:
            session_id: Session ID
            sequence_number: Chunk sequence number
        
        Returns:
            Retry state dict or None if not retrying
        """
        key = (session_id, sequence_number)
        if key not in self.retry_queue:
            return None
        
        chunk = self.retry_queue[key]
        return {
            "session_id": chunk.session_id,
            "sequence_number": chunk.sequence_number,
            "attempt": chunk.attempt,
            "max_retries": self.max_retries,
            "error_classification": chunk.error_classification.value,
            "error_message": chunk.error_message,
            "total_backoff_ms": chunk.total_backoff_ms,
            "next_retry_at": chunk.next_retry_at.isoformat() if chunk.next_retry_at else None,
            "will_retry": chunk.should_retry_now(),
        }
    
    def get_metrics(self) -> dict:
        """Get retry metrics.
        
        Returns:
            Metrics dict
        """
        return {
            "circuit_breaker_state": self.circuit_breaker.state.value,
            "queue_size": len(self.retry_queue),
            "total_retries_attempted": self.total_retries_attempted,
            "total_retries_succeeded": self.total_retries_succeeded,
            "total_retries_failed": self.total_retries_failed,
            "chunks_permanently_failed": self.chunks_permanently_failed,
            "failure_rate": (
                (self.total_retries_failed / self.total_retries_attempted * 100)
                if self.total_retries_attempted > 0
                else 0
            ),
        }
    
    def get_recovery_info(self) -> dict:
        """Get recovery info for resuming interrupted recording.
        
        Returns:
            Recovery state
        """
        return {
            "meeting_id": self.meeting_id,
            "pending_retries": [
                {
                    "session_id": chunk.session_id,
                    "sequence_number": chunk.sequence_number,
                    "attempt": chunk.attempt,
                    "next_retry_at": chunk.next_retry_at.isoformat() if chunk.next_retry_at else None,
                }
                for chunk in self.retry_queue.values()
            ],
            "metrics": self.get_metrics(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

