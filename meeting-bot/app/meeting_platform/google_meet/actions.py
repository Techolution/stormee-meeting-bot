"""Low-level Google Meet UI operations.

One concern per layer: this module knows how to *press things* in Meet's
interface, while :mod:`app.meeting_platform.google_meet.platform` knows what
sequence of presses constitutes joining, leaving or recording.

Splitting them keeps both readable. It also isolates the part that breaks:
when Meet redesigns a control, the change lands here and in
:mod:`app.meeting_platform.google_meet.selectors`, not in meeting logic.

Every method degrades rather than raising. A missed click on an optional
control should not end a meeting, and the caller can check the returned bool
where it matters.
"""

from __future__ import annotations

import asyncio
import logging
import re

from playwright.async_api import Error as PlaywrightError

from app.browser.browser import Browser
from app.meeting_platform.google_meet import selectors
from app.meeting_platform.google_meet.scripts import load_script
from app.meeting_platform.models import DeviceState

logger = logging.getLogger(__name__)

#: Meet labels a toggle by the action it performs, so "Turn off microphone"
#: means the microphone is currently ON. State is read from the label.
_DEVICE_LABEL = re.compile(r"turn (on|off) (microphone|camera)", re.IGNORECASE)

_STATE_VERIFY_TIMEOUT_MS = 3_000


class GoogleMeetActions:
    """Presses buttons in the Google Meet UI."""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser
        self._click_first = load_script("click_first.js")
        self._dismiss_popup = load_script("dismiss_popup.js")

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    async def click_any(
        self,
        candidates: tuple[str, ...],
        *,
        wake_first: bool = True,
        enable_first: bool = False,
    ) -> bool:
        """Click the first candidate that exists, via a direct DOM click.

        Falls back to a Playwright forced click, which handles cases a DOM
        click cannot — a control inside a shadow root, or one that only responds
        to a trusted event.
        """
        if wake_first:
            await self._browser.wake_controls()

        clicked = await self._browser.try_evaluate(
            self._click_first,
            {"selectors": list(candidates), "enableFirst": enable_first},
            default=False,
        )
        if clicked:
            return True

        for selector in candidates:
            if await self._browser.click(selector, timeout_ms=2_000, force=True):
                return True

        logger.debug("No candidate element was clickable", extra={"candidates": list(candidates)})
        return False

    async def dismiss_sign_in_popup(self) -> bool:
        """Clear the account interstitial that covers the pre-join controls."""
        dismissed = await self._browser.try_evaluate(
            self._dismiss_popup,
            {
                "buttonSelectors": list(selectors.SIGN_IN_POPUP_DISMISS),
                "containerSelector": selectors.SIGN_IN_POPUP_CONTAINER,
            },
            default=False,
        )
        if dismissed:
            logger.debug("Dismissed sign-in interstitial")
        return bool(dismissed)

    # ------------------------------------------------------------------
    # Joining
    # ------------------------------------------------------------------

    async def fill_guest_name(self, name: str, *, timeout_seconds: float = 10.0) -> bool:
        """Type the bot's display name into the guest-join field.

        The field is a controlled React input: a programmatic value assignment
        is discarded on the next render, so the name is typed as real key
        events and then confirmed with explicit input/change/blur events.
        """
        selector = await self._wait_for_any(selectors.GUEST_NAME_INPUT, timeout_seconds=timeout_seconds)
        if selector is None:
            logger.warning("Guest name field never appeared")
            await self._browser.screenshot("guest-name-input-missing")
            return False

        if not await self._browser.type_text(selector, name):
            return False

        await self._browser.try_evaluate(
            """
            (selector) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                for (const type of ['input', 'change', 'blur']) {
                    el.dispatchEvent(new Event(type, { bubbles: true }));
                }
                return true;
            }
            """,
            selector,
            default=False,
        )
        logger.debug("Filled guest name", extra={"display_name": name})
        return True

    async def submit_join(self) -> bool:
        """Press whichever join control this meeting is showing."""
        clicked = await self.click_any(selectors.JOIN_BUTTONS, enable_first=True)
        if clicked:
            logger.info("Submitted join request")
        else:
            logger.error("Could not find a join control")
            await self._browser.screenshot("join-button-missing")
        return clicked

    async def leave_call(self) -> bool:
        """Press the leave-call control."""
        return await self.click_any(selectors.LEAVE_BUTTONS)

    # ------------------------------------------------------------------
    # Media controls
    # ------------------------------------------------------------------

    async def set_microphone(self, *, enabled: bool) -> bool:
        """Drive the microphone to a state. Returns True if it ends up there."""
        return await self._set_device("microphone", enabled=enabled, shortcut=selectors.MIC_SHORTCUT)

    async def set_camera(self, *, enabled: bool) -> bool:
        """Drive the camera to a state. Returns True if it ends up there."""
        return await self._set_device("camera", enabled=enabled, shortcut=selectors.CAMERA_SHORTCUT)

    async def microphone_state(self) -> DeviceState:
        """Read the microphone state from the DOM."""
        if not self._browser.is_available:
            return DeviceState.UNKNOWN
        try:
            unmuted = await self._browser.count(selectors.MIC_UNMUTED_MARKER)
            return DeviceState.ON if unmuted > 0 else DeviceState.OFF
        except Exception:  # noqa: BLE001 - a probe, not an action
            return DeviceState.UNKNOWN

    async def _set_device(self, device: str, *, enabled: bool, shortcut: str) -> bool:
        """Toggle a media device, verifying the result.

        Two mechanisms, in order: the labelled button, then the keyboard
        shortcut. Both are verified by waiting for the label to flip, because a
        click that lands on an overlay reports success while changing nothing.
        """
        desired = "on" if enabled else "off"

        if await self._toggle_via_button(device, enabled=enabled):
            logger.debug("%s turned %s via button", device.capitalize(), desired)
            return True

        # The button is absent on some screens (notably pre-join) and Meet's own
        # shortcut works there.
        if not await self._browser.press_key(shortcut):
            return False

        if await self._verify_device_state(device, enabled=enabled):
            logger.debug("%s turned %s via keyboard shortcut", device.capitalize(), desired)
            return True

        logger.warning(
            "Could not confirm device state",
            extra={"device": device, "desired": desired},
        )
        return False

    async def _toggle_via_button(self, device: str, *, enabled: bool) -> bool:
        """Click the labelled toggle if it exists and is not already correct."""
        try:
            button = self._browser.page.get_by_role(
                "button", name=re.compile(rf"turn (on|off) {device}", re.IGNORECASE)
            ).first
            if await button.count() == 0:
                return False

            label = await button.get_attribute("aria-label") or ""
            # "Turn off X" is offered when X is on.
            currently_enabled = bool(re.search(r"turn off", label, re.IGNORECASE))
            if currently_enabled == enabled:
                return True

            await button.click()
            return await self._verify_device_state(device, enabled=enabled)

        except (PlaywrightError, Exception) as error:  # noqa: BLE001 - fall through to shortcut
            logger.debug("Device button interaction failed", extra={"device": device, "reason": str(error)})
            return False

    async def _verify_device_state(self, device: str, *, enabled: bool) -> bool:
        """Wait for the toggle's label to reflect the requested state."""
        expected = re.compile(rf"turn {'off' if enabled else 'on'} {device}", re.IGNORECASE)
        try:
            await self._browser.page.get_by_role("button", name=expected).first.wait_for(
                state="visible", timeout=_STATE_VERIFY_TIMEOUT_MS
            )
            return True
        except Exception:  # noqa: BLE001 - unverified is treated as failed
            return False

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------

    async def enable_captions(self) -> bool:
        """Switch captions on, by button or by keyboard shortcut."""
        if await self.click_any(selectors.CAPTION_TOGGLE):
            await asyncio.sleep(0.5)
            return True

        logger.debug("Caption button not found; using keyboard shortcut")
        return await self._browser.press_key(selectors.CAPTION_SHORTCUT)

    async def open_chat_panel(self, *, attempts: int = 5) -> bool:
        """Open the chat side panel.

        Retried because the toggle is part of the auto-hiding control bar and
        may not be rendered on the first pass.
        """
        for attempt in range(1, attempts + 1):
            if await self.click_any(selectors.CHAT_TOGGLE):
                # Give the panel time to mount before anything reads from it.
                await asyncio.sleep(1.5)
                logger.debug("Chat panel opened", extra={"attempt": attempt})
                return True
            await asyncio.sleep(1.0)

        logger.warning("Could not open the chat panel")
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _wait_for_any(
        self,
        candidates: tuple[str, ...],
        *,
        timeout_seconds: float,
        poll_seconds: float = 1.0,
    ) -> str | None:
        """Return the first candidate selector that matches within the budget."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            for selector in candidates:
                if await self._browser.count(selector) > 0:
                    return selector
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(poll_seconds)
