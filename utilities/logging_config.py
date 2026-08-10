"""Centralized logging configuration module.

This module provides a single configuration point for logging setup across the
application, enabling environment-aware log level configuration (DEBUG for
development, INFO for production) and context-aware formatting for request-scoped
logging context.
"""

import logging
import os
import sys
from typing import Optional, Any


def configure_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None
) -> None:
    """Configure the root logger with environment-aware settings.

    This function reads the ENVIRONMENT variable and sets the log level to
    logging.DEBUG for development or logging.INFO for production. Optional
    parameters can override defaults. Invalid log levels raise ValueError.

    Args:
        log_level: Optional log level as string (e.g., 'DEBUG', 'INFO'). If
                   provided, overrides environment-based default.
        log_format: Optional format string for log messages. If not provided,
                    uses default format with timestamp, logger name, level, and message.

    Raises:
        ValueError: If log_level parameter or LOG_LEVEL environment variable
                    contains an invalid logging level.

    Example:
        >>> configure_logging()
        >>> configure_logging(log_level='DEBUG')
    """
    # Determine the final log level
    final_level = logging.INFO  # Safe default
    environment = os.getenv('ENV', '').strip().lower()

    # Set level based on ENVIRONMENT variable
    if environment == 'local':
        final_level = logging.DEBUG
    elif environment == 'production' or environment == 'qa' or environment == 'dev' :
        final_level = logging.INFO
    else:
        # Warn if ENVIRONMENT is not set or has unexpected value
        if not environment:
            sys.stderr.write(
                "WARNING: ENVIRONMENT variable not set. Using default level: INFO\n"
            )

    # Override with LOG_LEVEL environment variable if present
    env_log_level = os.getenv('LOG_LEVEL', '').strip()
    if env_log_level:
        try:
            final_level = getattr(logging, env_log_level.upper())
        except AttributeError:
            raise ValueError(f"Invalid log level: {env_log_level}")

    # Override with parameter if provided
    if log_level is not None:
        try:
            final_level = getattr(logging, log_level.upper())
        except AttributeError:
            raise ValueError(f"Invalid log level: {log_level}")

    # Set up the default format string
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - [%(request_id)s] - %(meetingId)s - %(levelname)s - %(message)s'

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(final_level)

    # Create stream handler for stderr
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(final_level)

    # Create and apply formatter
    formatter = ContextAwareFormatter(log_format)
    handler.setFormatter(formatter)

    # Add handler to root logger
    root_logger.addHandler(handler)


class ContextAwareFormatter(logging.Formatter):
    """Custom formatter that injects request context into log records.

    This formatter retrieves request-scoped context variables (request_id, timer,
    meetingId, request_url) and injects them as attributes on the log record
    before formatting. This enables context-aware log messages without explicitly
    passing context to each logging call.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with injected request context.

        Args:
            record: The log record to format.

        Returns:
            Formatted log message with context values injected.
        """
        # Import here to avoid circular imports
        from utilities.logging_context import RequestContext

        # Get request context
        context = RequestContext.get_context()

        # Inject context values as record attributes
        record.request_id = context.get('request_id', '')
        record.timer = context.get('timer', '')
        record.meetingId = context.get('meetingId', '')
        record.request_url = context.get('request_url', '')

        # Call parent format method to apply the format string
        return super().format(record)

