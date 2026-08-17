"""Tests for configuration loading.

Two things matter here: the legacy flat environment must keep working, and
secrets must never appear in the summary that gets logged.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_legacy_variable_names_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing deployments set these names; renaming them silently would break them."""
    settings = _settings(
        monkeypatch,
        ENV="prod",
        HEADLESS="false",
        BACKEND_URL="https://legacy.invalid",
        WAIT_TIME_FOR_BOT_LAST_PARTICIPANT="300",
        AUDIO_QUEUE_MAX_CHUNKS="250",
        MEETING_STATE_TTL="7200",
        PROFILE_DIR="/data/profile",
    )

    assert settings.app.environment == "prod"
    assert settings.browser.headless is False
    assert settings.cw_utils.base_url == "https://legacy.invalid"
    assert settings.meeting.solo_grace_period_seconds == 300
    assert settings.recording.queue_max_chunks == 250
    assert settings.redis.state_ttl_seconds == 7200
    assert str(settings.browser.profile_dir) == "/data/profile"


def test_new_names_take_precedence_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        BACKEND_URL="https://legacy.invalid",
        CW_UTILS_URL="https://current.invalid",
    )

    assert settings.cw_utils.base_url == "https://current.invalid"


def test_log_level_defaults_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert _settings(monkeypatch, ENVIRONMENT="local").app.effective_log_level == "DEBUG"
    assert _settings(monkeypatch, ENVIRONMENT="prod").app.effective_log_level == "INFO"


def test_explicit_log_level_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, ENVIRONMENT="prod", LOG_LEVEL="warning")

    assert settings.app.effective_log_level == "WARNING"


def test_invalid_log_level_is_rejected_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Exception, match="logging level"):
        _settings(monkeypatch, LOG_LEVEL="CHATTY")


def test_invalid_default_email_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Exception, match="email"):
        _settings(monkeypatch, DEFAULT_USER_EMAIL="not-an-email")


def test_optional_integrations_report_their_own_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code branches on these rather than on whether a string is empty."""
    monkeypatch.delenv("WEBSOCKET_URL", raising=False)
    monkeypatch.delenv("MEETING_API_URL", raising=False)
    monkeypatch.delenv("CW_UTILS_URL", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)
    settings = Settings(_env_file=None)

    assert settings.websocket.enabled is False
    assert settings.meeting_api.enabled is False
    assert settings.cw_utils.enabled is False

    configured = _settings(monkeypatch, WEBSOCKET_URL="https://audio.invalid")
    assert configured.websocket.enabled is True


def test_cors_origins_parse_into_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(monkeypatch, CORS_ORIGINS="*").app.allowed_origins == ["*"]
    assert _settings(
        monkeypatch, CORS_ORIGINS="https://a.test, https://b.test"
    ).app.allowed_origins == ["https://a.test", "https://b.test"]


def test_describe_never_leaks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """`describe()` is logged at startup and exposed on /status."""
    settings = _settings(monkeypatch, REDIS_PASSWORD="super-secret", REDIS_ENABLED="true")

    summary = settings.describe()

    assert summary["redis"]["password_set"] is True
    assert "super-secret" not in repr(summary)


def test_memory_limit_is_exposed_in_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, AUDIO_QUEUE_MAX_MEMORY_MB="20")

    assert settings.recording.queue_max_memory_bytes == 20 * 1024 * 1024
