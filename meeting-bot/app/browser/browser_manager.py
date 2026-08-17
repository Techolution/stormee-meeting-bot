"""Chromium launch and lifecycle.

Launching a browser inside a container fails intermittently — a slow image
pull, a profile lock left behind by a killed pod, transient resource pressure.
This module owns the retry loop and, critically, the cleanup between attempts:
a failed launch that leaves a Playwright driver running will exhaust the pod's
memory after a handful of retries.

Init scripts are injected here rather than by the meeting platform because they
must be registered *before* the first navigation, which is a property of the
browser's lifecycle rather than of any particular meeting.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.browser.browser import Browser
from app.browser.models import BrowserOptions, SessionMode
from app.core.config import BrowserSettings
from app.core.exceptions import BrowserLaunchError

logger = logging.getLogger(__name__)


class BrowserManager:
    """Creates :class:`~app.browser.browser.Browser` instances.

    One manager serves the whole process; each meeting session launches its own
    browser through it.
    """

    def __init__(self, options: BrowserOptions) -> None:
        self._options = options

    @classmethod
    def from_settings(cls, settings: BrowserSettings) -> BrowserManager:
        return cls(
            BrowserOptions(
                headless=settings.headless,
                profile_dir=settings.profile_dir,
                launch_timeout_ms=settings.launch_timeout_ms,
                max_attempts=settings.launch_max_attempts,
                retry_delay_seconds=settings.launch_retry_delay_seconds,
                screenshot_dir=settings.screenshot_dir,
            )
        )

    @property
    def options(self) -> BrowserOptions:
        return self._options

    async def launch(self, *, init_scripts: tuple[str, ...] = ()) -> Browser:
        """Start Chromium and return a ready page.

        Args:
            init_scripts: JavaScript evaluated in every frame before page
                scripts run. Used to install the audio pipeline and to mask
                automation flags.

        Raises:
            BrowserLaunchError: If every attempt fails.
        """
        last_error: Exception | None = None

        for attempt in range(1, self._options.max_attempts + 1):
            resources: _LaunchResources = _LaunchResources()
            try:
                browser = await self._launch_once(resources, init_scripts)
                logger.info(
                    "Browser ready",
                    extra={
                        "attempt": attempt,
                        "mode": browser.mode.value,
                        "headless": self._options.headless,
                    },
                )
                return browser

            except asyncio.CancelledError:
                # Shutdown cancels an in-flight join, and `except Exception` does
                # not cover CancelledError. Without this the partially-launched
                # Playwright driver and Chromium are orphaned and outlive the
                # pod — which is the failure this class exists to prevent.
                await resources.release()
                raise

            except Exception as error:  # noqa: BLE001 - retried below, re-raised as domain error
                last_error = error
                logger.warning(
                    "Browser launch attempt failed",
                    extra={
                        "attempt": attempt,
                        "max_attempts": self._options.max_attempts,
                        "reason": str(error),
                    },
                )
                await resources.release()

                if attempt < self._options.max_attempts:
                    await asyncio.sleep(self._options.retry_delay_seconds)

        raise BrowserLaunchError(
            f"Chromium failed to start after {self._options.max_attempts} attempts",
            details={"cause": str(last_error) if last_error else "unknown"},
        )

    async def _launch_once(
        self,
        resources: _LaunchResources,
        init_scripts: tuple[str, ...],
    ) -> Browser:
        """One launch attempt. Everything it opens is tracked on ``resources``."""
        resources.playwright = await _start_driver()

        if self._options.use_persistent_profile:
            mode = SessionMode.PERSISTENT
            resources.context = await self._launch_persistent(resources.playwright)
            logger.debug("Using persistent profile", extra={"profile_dir": str(self._options.profile_dir)})
        else:
            mode = SessionMode.EPHEMERAL
            resources.browser, resources.context = await self._launch_ephemeral(resources.playwright)
            if self._options.profile_dir is not None:
                logger.info(
                    "Profile directory not found; joining as guest",
                    extra={"profile_dir": str(self._options.profile_dir)},
                )

        context = resources.context
        assert context is not None  # narrowed by the branches above

        for script in init_scripts:
            await context.add_init_script(script)

        resources.page = context.pages[0] if context.pages else await context.new_page()

        browser = Browser(
            playwright=resources.playwright,
            context=context,
            page=resources.page,
            mode=mode,
            browser=resources.browser,
            screenshot_dir=self._options.screenshot_dir,
        )
        # Ownership transfers to the Browser; the tracker must not close them.
        resources.disown()
        return browser

    async def _launch_persistent(self, playwright: Playwright) -> BrowserContext:
        """Launch with a user-data directory so the bot joins as a signed-in account."""
        assert self._options.profile_dir is not None
        return await playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._options.profile_dir.resolve()),
            headless=self._options.headless,
            channel="chromium",
            permissions=list(self._options.permissions),
            args=list(self._options.launch_args),
            viewport=None,
            timeout=self._options.launch_timeout_ms,
        )

    async def _launch_ephemeral(
        self, playwright: Playwright
    ) -> tuple[PlaywrightBrowser, BrowserContext]:
        """Launch a clean browser with no stored credentials."""
        browser = await playwright.chromium.launch(
            headless=self._options.headless,
            channel="chromium",
            args=list(self._options.launch_args),
            timeout=self._options.launch_timeout_ms,
        )
        context = await browser.new_context(
            permissions=list(self._options.permissions),
            viewport=None,
        )
        return browser, context


async def _start_driver() -> Playwright:
    """Start the Playwright driver, without leaking it if we are cancelled.

    Starting the driver spawns a Node subprocess. Cancellation landing inside
    that await — which is what happens when shutdown cancels an in-flight join —
    would otherwise leave us without the handle while the subprocess is already
    running, orphaning it for the life of the pod.

    Shielding lets the start finish so the handle can be retrieved and the driver
    stopped before the cancellation is re-raised.
    """
    start = asyncio.ensure_future(async_playwright().start())
    try:
        return await asyncio.shield(start)
    except asyncio.CancelledError:
        with suppress(Exception):
            driver = await start
            await driver.stop()
        raise


class _LaunchResources:
    """Tracks what a launch attempt opened so a failure can unwind it completely.

    Without this, each failed attempt leaks a Chromium process and a Playwright
    driver; three retries are enough to exhaust a modest pod.
    """

    __slots__ = ("_owned", "browser", "context", "page", "playwright")

    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: PlaywrightBrowser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._owned = True

    def disown(self) -> None:
        """Hand ownership to the caller; :meth:`release` becomes a no-op."""
        self._owned = False

    async def release(self) -> None:
        if not self._owned:
            return
        # Each step is attempted regardless of the others: a launch fails
        # partway through, so some of these are legitimately unset or already
        # broken, and one raising must not strand the rest.
        for closer in (self._close_context, self._close_browser, self._stop_playwright):
            with suppress(Exception):
                await closer()

    async def _close_context(self) -> None:
        if self.context is not None:
            await self.context.close()

    async def _close_browser(self) -> None:
        if self.browser is not None:
            await self.browser.close()

    async def _stop_playwright(self) -> None:
        if self.playwright is not None:
            await self.playwright.stop()
