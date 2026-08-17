"""Application configuration.

All configuration enters the process here and nowhere else. Modules receive a
:class:`Settings` instance (or a slice of one) by injection rather than reading
the environment themselves, which keeps them testable and keeps the set of
knobs discoverable in a single file.

Settings are grouped by concern. Each group is an independent settings model
with its own environment prefix, so the flat environment used by earlier
deployments keeps working: ``REDIS_HOST`` populates ``settings.redis.host``,
``WEBSOCKET_URL`` populates ``settings.websocket.url``, and so on. Where a
newer, better name exists, both are accepted via ``AliasChoices`` and the new
name wins.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "qa", "prod"]

_ENV_FILE = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)


class AppSettings(BaseSettings):
    """Process-level identity and logging."""

    model_config = _ENV_FILE

    environment: Environment = Field(
        default="local",
        validation_alias=AliasChoices("APP_ENVIRONMENT", "ENVIRONMENT", "ENV"),
        description="Deployment environment. Drives default log level and verbosity.",
    )
    log_level: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_LOG_LEVEL", "LOG_LEVEL"),
        description="Explicit log level. When unset, derived from the environment.",
    )
    log_format: Literal["text", "json"] = Field(
        default="text",
        validation_alias=AliasChoices("APP_LOG_FORMAT", "LOG_FORMAT"),
        description="'text' for humans, 'json' for log aggregators.",
    )
    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("APP_HOST", "HOST"))
    port: int = Field(
        default=5000,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("APP_PORT", "PORT"),
    )
    api_prefix: str = Field(default="/api/meet", validation_alias=AliasChoices("API_PREFIX"))
    cors_origins: str = Field(
        default="*",
        validation_alias=AliasChoices("CORS_ORIGINS"),
        description="Comma-separated list of allowed origins, or '*'.",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str | None) -> str | None:
        if value is None:
            return None
        level = value.strip().upper()
        if not isinstance(getattr(logging, level, None), int):
            raise ValueError(f"log level must be a valid Python logging level, got {value!r}")
        return level

    @property
    def is_production(self) -> bool:
        return self.environment in ("qa", "prod")

    @property
    def effective_log_level(self) -> str:
        """Explicit level if given, otherwise DEBUG locally and INFO elsewhere."""
        if self.log_level:
            return self.log_level
        return "INFO" if self.is_production else "DEBUG"

    @property
    def allowed_origins(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class BrowserSettings(BaseSettings):
    """Playwright / Chromium launch behaviour."""

    model_config = _ENV_FILE

    headless: bool = Field(
        default=True,
        validation_alias=AliasChoices("BROWSER_HEADLESS", "HEADLESS"),
    )
    profile_dir: Path | None = Field(
        default=Path("chrome_profile"),
        validation_alias=AliasChoices("BROWSER_PROFILE_DIR", "PROFILE_DIR"),
        description=(
            "Chromium user-data directory. When it exists, a persistent context is used "
            "and the bot joins as the signed-in profile; otherwise it joins as a guest."
        ),
    )
    launch_timeout_ms: int = Field(
        default=30_000,
        gt=0,
        validation_alias=AliasChoices("BROWSER_LAUNCH_TIMEOUT_MS", "TIMEOUT_MS"),
    )
    launch_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("BROWSER_LAUNCH_MAX_ATTEMPTS", "MAX_RETRIES"),
    )
    launch_retry_delay_seconds: float = Field(
        default=3.0,
        ge=0.0,
        validation_alias=AliasChoices("BROWSER_LAUNCH_RETRY_DELAY_SECONDS"),
    )
    guest_display_name: str = Field(
        default="Stormee.Ai",
        validation_alias=AliasChoices("BROWSER_GUEST_DISPLAY_NAME", "GUEST_DISPLAY_NAME"),
        description="Name the bot types into the guest-join field.",
    )
    screenshot_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("BROWSER_SCREENSHOT_DIR"),
        description="When set, join failures are captured here for debugging.",
    )


class MeetingSettings(BaseSettings):
    """Meeting lifecycle timings."""

    model_config = _ENV_FILE

    admission_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        validation_alias=AliasChoices("MEETING_ADMISSION_TIMEOUT_SECONDS"),
        description="How long to wait in the lobby for a host to admit the bot.",
    )
    admission_poll_interval_seconds: float = Field(
        default=2.0,
        gt=0,
        validation_alias=AliasChoices("MEETING_ADMISSION_POLL_INTERVAL_SECONDS"),
    )
    participant_poll_interval_seconds: float = Field(
        default=2.0,
        gt=0,
        validation_alias=AliasChoices("MEETING_PARTICIPANT_POLL_INTERVAL_SECONDS"),
    )
    solo_grace_period_seconds: int = Field(
        default=120,
        ge=1,
        le=3600,
        validation_alias=AliasChoices(
            "MEETING_SOLO_GRACE_PERIOD_SECONDS",
            "WAIT_TIME_FOR_BOT_LAST_PARTICIPANT",
        ),
        description="How long the bot stays alone in a meeting before leaving on its own.",
    )
    auto_leave_when_alone: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEETING_AUTO_LEAVE_WHEN_ALONE"),
    )
    chat_commands_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEETING_CHAT_COMMANDS_ENABLED"),
        description="Allow participants to drive the bot with in-chat commands.",
    )
    chat_command_prefix: str = Field(
        default="stormee",
        validation_alias=AliasChoices("MEETING_CHAT_COMMAND_PREFIX"),
    )


class RecordingSettings(BaseSettings):
    """Audio capture, buffering and upload."""

    model_config = _ENV_FILE

    chunk_duration_ms: int = Field(
        default=5_000,
        ge=1_000,
        le=60_000,
        validation_alias=AliasChoices("RECORDING_CHUNK_DURATION_MS"),
        description="MediaRecorder timeslice. One chunk is emitted per interval.",
    )
    upload_transport: Literal["websocket", "direct"] = Field(
        default="websocket",
        validation_alias=AliasChoices("RECORDING_UPLOAD_TRANSPORT"),
        description=(
            "'websocket' streams chunks to the external audio service, which owns "
            "object-storage ingest. 'direct' makes this process perform the resumable "
            "upload itself — useful when no audio service is deployed."
        ),
    )
    resumable_block_size_bytes: int = Field(
        default=256 * 1024,
        ge=256 * 1024,
        validation_alias=AliasChoices("RECORDING_RESUMABLE_BLOCK_SIZE_BYTES"),
        description=(
            "Bytes accumulated before a resumable PUT. GCS requires every non-final "
            "block to be a multiple of 256 KiB."
        ),
    )
    upload_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        validation_alias=AliasChoices("RECORDING_UPLOAD_TIMEOUT_SECONDS"),
    )
    finalize_grace_period_seconds: float = Field(
        default=2.0,
        ge=0,
        validation_alias=AliasChoices("RECORDING_FINALIZE_GRACE_PERIOD_SECONDS"),
        description="Time allowed for in-flight chunks to land after the recorder stops.",
    )
    queue_max_chunks: int = Field(
        default=100,
        ge=10,
        le=10_000,
        validation_alias=AliasChoices("RECORDING_QUEUE_MAX_CHUNKS", "AUDIO_QUEUE_MAX_CHUNKS"),
    )
    queue_max_memory_mb: int = Field(
        default=10,
        ge=1,
        le=1_000,
        validation_alias=AliasChoices("RECORDING_QUEUE_MAX_MEMORY_MB", "AUDIO_QUEUE_MAX_MEMORY_MB"),
    )
    content_type: str = Field(
        default="audio/webm;codecs=opus",
        validation_alias=AliasChoices("RECORDING_CONTENT_TYPE"),
    )

    @property
    def queue_max_memory_bytes(self) -> int:
        return self.queue_max_memory_mb * 1024 * 1024


class TranscriptionSettings(BaseSettings):
    """Transcript acquisition."""

    model_config = _ENV_FILE

    provider: Literal["caption"] = Field(
        default="caption",
        validation_alias=AliasChoices("TRANSCRIPTION_PROVIDER"),
        description="Transcript source. Only in-meeting captions are implemented today.",
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        gt=0,
        validation_alias=AliasChoices("TRANSCRIPTION_POLL_INTERVAL_SECONDS"),
    )
    context_buffer_max_segments: int = Field(
        default=5_000,
        ge=1,
        validation_alias=AliasChoices("TRANSCRIPTION_CONTEXT_BUFFER_MAX_SEGMENTS"),
    )


class WebSocketSettings(BaseSettings):
    """Client-side connection to the external audio service."""

    model_config = _ENV_FILE

    url: str = Field(
        default="",
        validation_alias=AliasChoices("WEBSOCKET_URL"),
        description="Socket.IO endpoint of the audio service. Empty disables streaming.",
    )
    path: str = Field(
        default="api/meet/socket.io",
        validation_alias=AliasChoices("WEBSOCKET_PATH"),
        description="Socket.IO mount path on the audio service.",
    )
    connect_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        validation_alias=AliasChoices("WEBSOCKET_CONNECT_TIMEOUT_SECONDS"),
    )
    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices("WEBSOCKET_REQUEST_TIMEOUT_SECONDS"),
    )
    reconnect_initial_delay_ms: int = Field(
        default=1_000,
        ge=100,
        le=60_000,
        validation_alias=AliasChoices("WEBSOCKET_RECONNECT_DELAY"),
    )
    reconnect_backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        le=5.0,
        validation_alias=AliasChoices("WEBSOCKET_BACKOFF_FACTOR"),
    )
    reconnect_max_delay_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=600_000,
        validation_alias=AliasChoices("WEBSOCKET_MAX_RECONNECT_DELAY"),
    )
    max_reconnect_attempts: int = Field(
        default=5,
        ge=1,
        le=100,
        validation_alias=AliasChoices("WEBSOCKET_MAX_RECONNECT_ATTEMPTS"),
    )
    auto_reconnect: bool = Field(
        default=True,
        validation_alias=AliasChoices("WEBSOCKET_AUTO_RECONNECT"),
        description="Supervise the connection and reconnect in the background when it drops.",
    )

    @property
    def enabled(self) -> bool:
        return bool(self.url.strip())


class CWUtilsSettings(BaseSettings):
    """Creative Workspace backend — uploads, artifacts, notification mail."""

    model_config = _ENV_FILE

    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("CW_UTILS_URL", "BACKEND_URL"),
    )
    timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        validation_alias=AliasChoices("CW_UTILS_TIMEOUT_SECONDS"),
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        validation_alias=AliasChoices("CW_UTILS_MAX_RETRIES"),
    )
    project_url_template: str = Field(
        default="https://dev.appmod.ai/mode/Project%20Mode/projects/{project_id}",
        validation_alias=AliasChoices("CW_PROJECT_URL_TEMPLATE"),
        description="Used to deep-link users to a project from notification email.",
    )
    artifact_model_type: str = Field(
        default="google",
        validation_alias=AliasChoices("CW_ARTIFACT_MODEL_TYPE"),
    )
    artifact_llm: str = Field(
        default="claude-3.5-sonnet",
        validation_alias=AliasChoices("CW_ARTIFACT_LLM"),
    )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip())


class MailSettings(BaseSettings):
    """Outbound notification mail, sent through the CW mail relay."""

    model_config = _ENV_FILE

    enabled: bool = Field(default=True, validation_alias=AliasChoices("MAIL_ENABLED"))
    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("MAIL_BASE_URL", "CW_UTILS_URL", "BACKEND_URL"),
    )
    timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices("MAIL_TIMEOUT_SECONDS"),
    )


class MeetingAPISettings(BaseSettings):
    """Upstream service that owns durable meeting state."""

    model_config = _ENV_FILE

    base_url: str = Field(default="", validation_alias=AliasChoices("MEETING_API_URL"))
    timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices("MEETING_API_TIMEOUT_SECONDS"),
    )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip())


class RedisSettings(BaseSettings):
    """Meeting-state persistence. Optional — the bot degrades to in-memory state."""

    model_config = _ENV_FILE

    enabled: bool = Field(default=True, validation_alias=AliasChoices("REDIS_ENABLED"))
    host: str = Field(default="localhost", validation_alias=AliasChoices("REDIS_HOST"))
    port: int = Field(default=6379, ge=1, le=65535, validation_alias=AliasChoices("REDIS_PORT"))
    db: int = Field(default=0, ge=0, le=15, validation_alias=AliasChoices("REDIS_DB"))
    password: str | None = Field(default=None, validation_alias=AliasChoices("REDIS_PASSWORD"))
    socket_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias=AliasChoices("REDIS_SOCKET_TIMEOUT_SECONDS"),
    )
    state_ttl_seconds: int = Field(
        default=3_600,
        ge=60,
        le=86_400,
        validation_alias=AliasChoices("REDIS_STATE_TTL_SECONDS", "MEETING_STATE_TTL"),
    )
    history_max_entries: int = Field(
        default=500,
        ge=10,
        le=10_000,
        validation_alias=AliasChoices("REDIS_HISTORY_MAX_ENTRIES"),
        description="History list is trimmed to this length so a long meeting cannot grow unbounded.",
    )


class ProjectSettings(BaseSettings):
    """Defaults applied when a request omits project or user attribution."""

    model_config = _ENV_FILE

    default_project_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PROJECT_ID", "DEFAULT_PROJECT_ID"),
    )
    default_project_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PROJECT_NAME", "DEFAULT_PROJECT_NAME"),
    )
    default_user_name: str = Field(
        default="Unknown User",
        validation_alias=AliasChoices("DEFAULT_USER_NAME"),
    )
    default_user_email: str = Field(
        default="no-reply@example.com",
        validation_alias=AliasChoices("DEFAULT_USER_EMAIL"),
    )

    @field_validator("default_user_email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError(f"DEFAULT_USER_EMAIL must be an email address, got {value!r}")
        return value


class Settings(BaseSettings):
    """Root configuration object. One instance per process."""

    model_config = _ENV_FILE

    app: AppSettings = Field(default_factory=AppSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    meeting: MeetingSettings = Field(default_factory=MeetingSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)
    cw_utils: CWUtilsSettings = Field(default_factory=CWUtilsSettings)
    mail: MailSettings = Field(default_factory=MailSettings)
    meeting_api: MeetingAPISettings = Field(default_factory=MeetingAPISettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    project: ProjectSettings = Field(default_factory=ProjectSettings)

    def describe(self) -> dict:
        """Configuration summary safe to log or expose on a status endpoint.

        Secrets are reported as booleans, never as values.
        """
        return {
            "environment": self.app.environment,
            "log_level": self.app.effective_log_level,
            "browser": {
                "headless": self.browser.headless,
                "profile_dir": str(self.browser.profile_dir) if self.browser.profile_dir else None,
            },
            "recording": {
                "chunk_duration_ms": self.recording.chunk_duration_ms,
                "upload_transport": self.recording.upload_transport,
            },
            "transcription": {"provider": self.transcription.provider},
            "websocket": {"enabled": self.websocket.enabled, "url": self.websocket.url or None},
            "cw_utils": {"enabled": self.cw_utils.enabled},
            "meeting_api": {"enabled": self.meeting_api.enabled},
            "redis": {
                "enabled": self.redis.enabled,
                "host": self.redis.host,
                "port": self.redis.port,
                "password_set": bool(self.redis.password),
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Tests that need a different configuration should call
    ``get_settings.cache_clear()`` after patching the environment, or build a
    :class:`Settings` instance directly and inject it.
    """
    return Settings()
