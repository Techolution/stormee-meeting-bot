"""Error handling and logging utilities module.

Provides specialized error handlers, decorators, and utilities for comprehensive
exception logging and recovery mechanisms throughout the application.
"""

import logging
import traceback
import asyncio
import platform
from typing import Any, Callable, Optional, TypeVar
from functools import wraps


logger = logging.getLogger(__name__)

T = TypeVar('T')


def log_exception(
    logger_obj: logging.Logger,
    level: int,
    message: str,
    exception: Exception,
    context: Optional[dict] = None
) -> None:
    """Log exception with full traceback and optional context.
    
    Args:
        logger_obj: Logger instance to use
        level: Logging level (logging.ERROR, logging.WARNING, etc.)
        message: Main error message
        exception: Exception instance
        context: Optional dictionary with additional context information
    """
    # Build context message
    context_str = ""
    if context:
        context_items = [f"{k}={v}" for k, v in context.items()]
        context_str = " [" + ", ".join(context_items) + "]"
    
    # Log main message with exception and traceback
    logger_obj.log(
        level,
        f"{message}{context_str}",
        exc_info=True,
    )


def handle_browser_error(
    logger_obj: logging.Logger,
    exception: Exception,
    meeting_id: str,
    browser_type: Optional[str] = None
) -> None:
    """Handle browser-related errors with detailed context.
    
    Args:
        logger_obj: Logger instance
        exception: Exception instance
        meeting_id: Meeting/bot identifier
        browser_type: Type of browser being used (chromium, firefox, webkit)
    """
    context = {
        'meeting_id': meeting_id,
        'browser': browser_type or 'unknown',
        'platform': platform.system(),
    }
    
    message = f"Browser error for meeting {meeting_id}"
    log_exception(logger_obj, logging.ERROR, message, exception, context)


def handle_websocket_error(
    logger_obj: logging.Logger,
    exception: Exception,
    meeting_id: str,
    endpoint: Optional[str] = None
) -> None:
    """Handle WebSocket connection errors with detailed context.
    
    Args:
        logger_obj: Logger instance
        exception: Exception instance
        meeting_id: Meeting/bot identifier
        endpoint: WebSocket endpoint being accessed
    """
    context = {
        'meeting_id': meeting_id,
        'endpoint': endpoint or 'unknown',
    }
    
    message = f"WebSocket error for meeting {meeting_id}"
    log_exception(logger_obj, logging.ERROR, message, exception, context)


def handle_audio_error(
    logger_obj: logging.Logger,
    exception: Exception,
    meeting_id: str,
    audio_format: Optional[str] = None
) -> None:
    """Handle audio processing errors with detailed context.
    
    Args:
        logger_obj: Logger instance
        exception: Exception instance
        meeting_id: Meeting/bot identifier
        audio_format: Audio format being processed
    """
    context = {
        'meeting_id': meeting_id,
        'audio_format': audio_format or 'unknown',
    }
    
    message = f"Audio processing error for meeting {meeting_id}"
    log_exception(logger_obj, logging.ERROR, message, exception, context)


def handle_file_error(
    logger_obj: logging.Logger,
    exception: Exception,
    file_path: str,
    operation: str = 'operation'
) -> None:
    """Handle file operation errors with detailed context.
    
    Args:
        logger_obj: Logger instance
        exception: Exception instance
        file_path: Path to file being accessed
        operation: Type of operation (read, write, delete, etc.)
    """
    context = {
        'file_path': file_path,
        'operation': operation,
    }
    
    message = f"File {operation} error: {file_path}"
    log_exception(logger_obj, logging.ERROR, message, exception, context)


def retry_with_exponential_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0
) -> Callable:
    """Decorator for retrying async operations with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Factor to multiply delay by for each retry
        max_delay: Maximum delay between retries
        
    Returns:
        Decorated function that implements retry logic
        
    Example:
        @retry_with_exponential_backoff(max_retries=3, initial_delay=1.0)
        async def flaky_operation():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Log retry attempt
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}, "
                            f"retrying in {delay}s: {type(e).__name__}: {str(e)}"
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        # All retries exhausted
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )
            
            # Raise the last exception if all retries failed
            raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}, "
                            f"retrying in {delay}s: {type(e).__name__}: {str(e)}"
                        )
                        asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )
            
            raise last_exception
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

