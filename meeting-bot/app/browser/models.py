"""Browser-layer value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BrowserStatus(str, Enum):
    """Lifecycle of the browser owned by one session."""

    IDLE = "idle"
    LAUNCHING = "launching"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class SessionMode(str, Enum):
    """How the browser session is authenticated.

    ``PERSISTENT`` reuses a Chromium profile directory, so the bot appears as
    whichever Google account is signed in there. ``EPHEMERAL`` starts clean and
    the bot must join as a guest. The two follow different join flows, so the
    mode is part of the browser's public state rather than an internal detail.
    """

    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True, slots=True)
class BrowserOptions:
    """Everything needed to launch Chromium for a meeting.

    Built from settings by :class:`~app.browser.browser_manager.BrowserManager`;
    tests construct one directly.
    """

    headless: bool = True
    profile_dir: Path | None = None
    launch_timeout_ms: int = 30_000
    max_attempts: int = 3
    retry_delay_seconds: float = 3.0
    screenshot_dir: Path | None = None

    #: Chromium flags. Media flags let the page open a fake microphone and
    #: camera without a device present; the sandbox flags are required inside
    #: an unprivileged container; the automation flag reduces bot detection.
    launch_args: tuple[str, ...] = field(
        default=(
            "--disable-blink-features=AutomationControlled",
            # "--start-maximized",
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-component-update",
            "--disable-features=Translate,BackForwardCache",
        )
    )

    #: Permissions granted up front so Meet never shows a browser prompt.
    permissions: tuple[str, ...] = field(default=("microphone", "camera"))

    @property
    def use_persistent_profile(self) -> bool:
        """True when a usable profile directory is configured and present.

        A missing directory is not an error: the bot falls back to a guest join,
        which is the expected path in ephemeral container deployments.
        """
        return self.profile_dir is not None and self.profile_dir.exists()
