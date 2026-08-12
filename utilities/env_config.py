"""Centralized environment configuration management."""

import logging
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=True,
        extra="ignore",
    )

    # ============================================================
    # Application
    # ============================================================

    ENV: Literal["local", "dev", "qa", "prod"]
    LOG_LEVEL: Optional[str] = "DEBUG"

    # ============================================================
    # Browser
    # ============================================================

    HEADLESS: bool = True
    BROWSER_TYPE: Literal["chromium", "chrome", "firefox", "webkit"] = "chromium"

    # ============================================================
    # Server
    # ============================================================

    PORT: int = Field(default=8000, ge=1, le=65535)
    TIMEOUT_MS: int = Field(default=30000, gt=0)
    MAX_RETRIES: int = Field(default=3, ge=0)

    # ============================================================
    # Project
    # ============================================================

    PROJECT_ID: str
    PROJECT_NAME: str

    # ============================================================
    # User
    # ============================================================

    DEFAULT_USER_NAME: str
    DEFAULT_USER_EMAIL: str
    JOIN_AS_GUEST: Optional[bool] = False

    # ============================================================
    # Profile
    # ============================================================

    PROFILE_DIR: Optional[str] = "chrome_profile"

    # ============================================================
    # Backend
    # ============================================================

    BACKEND_URL: str
    WEBSOCKET_URL: str
    WEBSOCKET_RECONNECT_DELAY: int = Field(default=1000, ge=100, le=10000)
    WEBSOCKET_BACKOFF_FACTOR: float = Field(default=2.0, ge=1.0, le=5.0)
    WEBSOCKET_MAX_RECONNECT_DELAY: int = Field(default=30000, ge=5000, le=120000)
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    AUDIO_QUEUE_MAX_CHUNKS: int = Field(default=100, ge=10, le=1000)
    AUDIO_QUEUE_MAX_MEMORY_MB: int = Field(default=10, ge=1, le=100)
    WAIT_TIME_FOR_BOT_LAST_PARTICIPANT: int = Field(default=120,ge=1,le=3600)

    # ============================================================
    # Validators
    # ============================================================

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Ensure LOG_LEVEL is a valid Python logging level."""
        level = value.upper()

        if not hasattr(logging, level):
            raise ValueError(
                f"LOG_LEVEL must be a valid Python logging level, "
                f"got '{value}'"
            )

        return level

    @field_validator("DEFAULT_USER_EMAIL")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Basic email validation."""
        if "@" not in value:
            raise ValueError(
                f"DEFAULT_USER_EMAIL must be a valid email address, got '{value}'"
            )

        return value

    # ============================================================
    # Backwards-compatible helpers
    # ============================================================

    def get(self, key: str) -> str:
        """Get a configuration value as a string."""
        if not hasattr(self, key):
            raise ValueError(
                f"Configuration key '{key}' is not defined"
            )

        value = getattr(self, key)

        if value is None:
            raise ValueError(
                f"Required configuration value '{key}' is not set"
            )

        return str(value)

    def get_bool(self, key: str) -> bool:
        """Get a configuration value as a boolean."""
        if not hasattr(self, key):
            raise ValueError(
                f"Configuration key '{key}' is not defined"
            )

        value = getattr(self, key)

        if not isinstance(value, bool):
            raise ValueError(
                f"Configuration value '{key}' is not a boolean"
            )

        return value

    def get_int(self, key: str) -> int:
        """Get a configuration value as an integer."""
        if not hasattr(self, key):
            raise ValueError(
                f"Configuration key '{key}' is not defined"
            )

        value = getattr(self, key)

        if not isinstance(value, int):
            raise ValueError(
                f"Configuration value '{key}' is not an integer"
            )

        return value

    def validate(self) -> bool:
        """Compatibility method.

        Pydantic validates the configuration when Config is instantiated,
        so no additional validation is required here.
        """
        logger.info(
            "Configuration validated successfully (environment=%s)",
            self.ENV,
        )
        return True

    def to_dict(self) -> dict:
        """Return configuration as a dictionary."""
        return self.model_dump()


# Module-level singleton
config = Config()