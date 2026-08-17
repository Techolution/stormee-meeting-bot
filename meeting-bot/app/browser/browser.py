"""Thin, safe wrapper around a live Playwright page.

Everything above this module talks to :class:`Browser` instead of touching
Playwright directly. The wrapper exists to enforce three rules that were
previously repeated (and sometimes forgotten) at every call site:

  * Never operate on a closed page — raise a typed error instead of
    ``AttributeError: 'NoneType'``.
  * Wake Google Meet's auto-hiding control bars before interacting with them.
  * Turn Playwright's timeout exceptions into domain errors.

It deliberately knows nothing about meetings. Meet-specific selectors and flows
belong to :mod:`app.meeting_platform`.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext, Page, Playwright
from playwright.async_api import Error as PlaywrightError

from app.browser.models import BrowserStatus, SessionMode
from app.core.exceptions import BrowserNotAvailableError, ElementNotFoundError

logger = logging.getLogger(__name__)


class Browser:
    """One Chromium page, plus the resources that must be released with it."""

    def __init__(
        self,
        *,
        playwright: Playwright,
        context: BrowserContext,
        page: Page,
        mode: SessionMode,
        browser: PlaywrightBrowser | None = None,
        screenshot_dir: Path | None = None,
    ) -> None:
        self._playwright = playwright
        self._context = context
        self._page = page
        self._browser = browser
        self._mode = mode
        self._screenshot_dir = screenshot_dir
        self._status = BrowserStatus.READY

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def mode(self) -> SessionMode:
        return self._mode

    @property
    def status(self) -> BrowserStatus:
        if self._status is BrowserStatus.READY and self._page.is_closed():
            self._status = BrowserStatus.CLOSED
        return self._status

    @property
    def is_available(self) -> bool:
        return self._status is BrowserStatus.READY and not self._page.is_closed()

    @property
    def url(self) -> str:
        return "" if self._page.is_closed() else self._page.url

    @property
    def page(self) -> Page:
        """The live page.

        Prefer the wrapper's own methods; reach for this only when a platform
        implementation genuinely needs a Playwright API the wrapper does not
        expose.

        Raises:
            BrowserNotAvailableError: If the page has been closed.
        """
        if self._page.is_closed():
            raise BrowserNotAvailableError("browser page is closed")
        return self._page

    # ------------------------------------------------------------------
    # Navigation and scripting
    # ------------------------------------------------------------------

    async def goto(self, url: str, *, timeout_ms: int = 30_000) -> None:
        """Navigate, waiting only for the DOM rather than every subresource.

        Raises:
            BrowserNotAvailableError: If navigation fails.
        """
        try:
            await self.page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except PlaywrightError as error:
            raise BrowserNotAvailableError(f"navigation to {url} failed: {error}") from error

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        """Run JavaScript in the page.

        Raises:
            BrowserNotAvailableError: If the page is gone or the script throws.
        """
        try:
            return await self.page.evaluate(script, arg) if arg is not None else await self.page.evaluate(script)
        except PlaywrightError as error:
            raise BrowserNotAvailableError(f"page evaluation failed: {error}") from error

    async def try_evaluate(self, script: str, arg: Any = None, *, default: Any = None) -> Any:
        """Run JavaScript, returning ``default`` instead of raising.

        For probes where a failure means "not right now" — the page is
        mid-navigation, an element has not rendered — rather than a real fault.
        """
        try:
            return await self.evaluate(script, arg)
        except Exception as error:  # noqa: BLE001 - probe failures are expected
            logger.debug("Page evaluation failed, using default", extra={"reason": str(error)})
            return default

    async def expose_function(self, name: str, handler: Any) -> bool:
        """Expose a Python callable to page JavaScript, once.

        Returns:
            True if newly exposed, False if it was already present — which
            happens whenever a recording is restarted on the same page.
        """
        already_defined = await self.try_evaluate(
            f"() => typeof window[{name!r}] === 'function'", default=False
        )
        if already_defined:
            logger.debug("Page function already exposed", extra={"function": name})
            return False

        await self.page.expose_function(name, handler)
        logger.debug("Exposed page function", extra={"function": name})
        return True

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    async def wake_controls(self) -> None:
        """Nudge the pointer so auto-hidden control bars render.

        Meet hides its toolbars after a few idle seconds and the buttons become
        genuinely unclickable. Every interaction with a toolbar control needs
        this first.
        """
        if not self.is_available:
            return
        # Losing a mouse move is never worth failing an action over.
        with suppress(PlaywrightError):
            await self._page.mouse.move(100, 100)

    async def click(
        self,
        selector: str,
        *,
        timeout_ms: int = 5_000,
        force: bool = False,
        required: bool = False,
    ) -> bool:
        """Click the first match for ``selector``.

        Args:
            required: When True, a miss raises instead of returning False. Use
                for controls whose absence means the flow cannot continue.

        Raises:
            ElementNotFoundError: If ``required`` and the element never appears.
        """
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click(force=force)
            return True
        except (PlaywrightError, BrowserNotAvailableError) as error:
            if required:
                raise ElementNotFoundError(f"clickable element {selector!r}", selector=selector) from error
            logger.debug("Click skipped", extra={"selector": selector, "reason": str(error)})
            return False

    async def type_text(self, selector: str, text: str, *, delay_ms: int = 60) -> bool:
        """Focus an input, clear it, and type character by character.

        The per-character delay produces real key events. Meet's join form is a
        controlled React input that ignores a value set programmatically, so
        this is the only reliable way to fill it.
        """
        try:
            locator = self.page.locator(selector).first
            await locator.focus()
            await self._page.keyboard.press("Control+A")
            await self._page.keyboard.press("Backspace")
            await self._page.keyboard.type(text, delay=delay_ms)
            return True
        except (PlaywrightError, BrowserNotAvailableError) as error:
            logger.warning("Failed to type into input", extra={"selector": selector, "reason": str(error)})
            return False

    async def press_key(self, key: str) -> bool:
        """Send a keyboard shortcut to the page."""
        try:
            await self.page.keyboard.press(key)
            return True
        except (PlaywrightError, BrowserNotAvailableError) as error:
            logger.debug("Key press failed", extra={"key": key, "reason": str(error)})
            return False

    async def count(self, selector: str) -> int:
        """How many elements match, or 0 if the page is unusable."""
        try:
            return await self.page.locator(selector).count()
        except (PlaywrightError, BrowserNotAvailableError):
            return 0

    async def screenshot(self, name: str) -> Path | None:
        """Capture the page for debugging, if a screenshot directory is configured."""
        if self._screenshot_dir is None or not self.is_available:
            return None
        try:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = self._screenshot_dir / f"{name}.png"
            await self._page.screenshot(path=str(path))
            logger.debug("Captured screenshot", extra={"path": str(path)})
            return path
        except Exception as error:  # noqa: BLE001 - diagnostics must never fail a flow
            logger.debug("Screenshot failed", extra={"reason": str(error)})
            return None

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release page, context, browser and Playwright driver.

        Each step is independent: a failure in one must not strand the others,
        because anything left open leaks a Chromium process for the life of the
        pod.
        """
        if self._status in (BrowserStatus.CLOSING, BrowserStatus.CLOSED):
            return
        self._status = BrowserStatus.CLOSING

        for label, closer in (
            ("page", self._close_page),
            ("context", self._close_context),
            ("browser", self._close_browser),
            ("playwright", self._stop_playwright),
        ):
            try:
                await closer()
            except Exception as error:  # noqa: BLE001 - always continue teardown
                logger.warning("Error releasing browser resource", extra={"resource": label, "reason": str(error)})

        self._status = BrowserStatus.CLOSED
        logger.info("Browser resources released")

    async def _close_page(self) -> None:
        if not self._page.is_closed():
            await self._page.close()

    async def _close_context(self) -> None:
        await self._context.close()

    async def _close_browser(self) -> None:
        if self._browser is not None:
            await self._browser.close()

    async def _stop_playwright(self) -> None:
        await self._playwright.stop()
