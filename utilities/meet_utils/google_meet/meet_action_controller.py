import asyncio
import logging
import re
from typing import Optional
from playwright.async_api import Page, ElementHandle

logger = logging.getLogger(__name__)

class ActionController:
    """Utility class to encapsulate DOM interactions, wiggles, clicks, and state checks."""

    def __init__(self, get_page_fn):
        """
        Pass a dynamic function that returns the active Playwright page instance,
        ensuring the handler always operates on the latest page state.
        """
        self._get_page = get_page_fn

    @property
    def page(self) -> Optional[Page]:
        return self._get_page()

    async def wake_controls(self) -> None:
        """Move mouse slightly to trigger auto-hidden Google Meet top/bottom control bars."""
        if not self.page or self.page.is_closed():
            return
        try:
            await self.page.mouse.move(100, 100)
        except Exception:
            pass

    async def safe_click(self, selector: str, timeout: int = 5000, force: bool = False) -> bool:
        """Wait for an element and attempt a click; returns True if successful."""
        if not self.page:
            return False
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.click(force=force)
            return True
        except Exception as e:
            logger.warning(f"Click failed on '{selector}': {e}")
            return False

    async def fill_input_natively(self, selector: str, text: str) -> bool:
        """Clear and type into an input using native character keyboard events (bypasses bot detection)."""
        if not self.page:
            return False
        try:
            input_el = self.page.locator(selector).first
            await input_el.focus()
            await asyncio.sleep(0.2)

            # Clear existing input
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")

            # Native character typing delay to trigger input events dynamically
            await self.page.keyboard.type(text, delay=60)
            await asyncio.sleep(0.3)

            # Explicitly emit DOM events so React internal state synchronizes
            await self.page.evaluate(
                f"""
                (sel) => {{
                    const el = document.querySelector(sel);
                    if (el) {{
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    }}
                }}
            """,
                selector,
            )
            return True
        except Exception as e:
            logger.warning(f"Error typing into '{selector}': {e}")
            return False

    async def _set_device_state(
        self,
        device: str,
        enabled: bool,
        keyboard_shortcut: str,
    ):
        """
        Set microphone/camera to the requested state.

        enabled=True  -> device should be ON
        enabled=False -> device should be OFF

        keyboard_shortcut:
            Playwright keyboard shortcut, e.g.
            "Meta+d" / "Control+d" for microphone
            "Meta+e" / "Control+e" for camera
        """

        if device not in {"camera", "microphone"}:
            raise ValueError(f"Unsupported device: {device}")

        try:
            # ---------------------------------------------------------
            # 1. Locate the device button semantically
            # ---------------------------------------------------------
            pattern = re.compile(
                rf"turn (on|off) {device}",
                re.I,
            )

            button = self.page.get_by_role(
                "button",
                name=pattern,
            ).first

            button_found = await button.count() > 0

            if button_found:
                try:
                    aria_label = await button.get_attribute("aria-label")

                    if aria_label:
                        # "Turn on microphone"  => currently OFF
                        # "Turn off microphone" => currently ON
                        currently_enabled = bool(
                            re.search(r"turn off", aria_label, re.I)
                        )

                        if currently_enabled == enabled:
                            logger.debug(
                                f"{device.capitalize()} already "
                                f"{'enabled' if enabled else 'disabled'}"
                            )
                            return True

                        # -------------------------------------------------
                        # 2. Click the UI button
                        # -------------------------------------------------
                        logger.debug(
                            f"Clicking {device} button "
                            f"to {'enable' if enabled else 'disable'}"
                        )

                        await button.click()

                        # -------------------------------------------------
                        # 3. Verify UI state after click
                        # -------------------------------------------------
                        expected = re.compile(
                            rf"turn {'off' if enabled else 'on'} {device}",
                            re.I,
                        )

                        await self.page.get_by_role(
                            "button",
                            name=expected,
                        ).first.wait_for(
                            state="visible",
                            timeout=3000,
                        )

                        logger.info(
                            f"{device.capitalize()} "
                            f"{'enabled' if enabled else 'disabled'} via UI button"
                        )
                        return True

                except Exception as e:
                    logger.warning(
                        f"UI interaction failed for {device}: {e}"
                    )

            else:
                logger.debug(
                    f"Could not find {device} button. "
                    f"Trying keyboard shortcut..."
                )

        except Exception as e:
            logger.debug(
                f"Error locating/interacting with {device}: {e}"
            )

        # =============================================================
        # 4. Keyboard shortcut fallback
        # =============================================================
        try:
            logger.debug(
                f"Trying keyboard shortcut "
                f"'{keyboard_shortcut}' for {device}"
            )

            await self.page.keyboard.press(keyboard_shortcut)

            # ---------------------------------------------------------
            # 5. Verify state after keyboard shortcut
            # ---------------------------------------------------------
            expected = re.compile(
                rf"turn {'off' if enabled else 'on'} {device}",
                re.I,
            )

            await self.page.get_by_role(
                "button",
                name=expected,
            ).first.wait_for(
                state="visible",
                timeout=3000,
            )

            logger.info(
                f"{device.capitalize()} "
                f"{'enabled' if enabled else 'disabled'} "
                f"via keyboard shortcut"
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to set {device} state using "
                f"keyboard shortcut '{keyboard_shortcut}': {e}"
            )
            return False

    async def pause_audio(self):
        return await self._set_device_state(
            "microphone",
            enabled=False,
            keyboard_shortcut="Control+d",
        )

    async def pause_camera(self):
        return await self._set_device_state(
            "camera",
            enabled=False,
            keyboard_shortcut="Control+e",
        )
    
    async def is_mic_on(self) -> bool:
        if not self.page:
            return False
        try:
            count = await self.page.locator('[data-is-muted="false"]').first.count()
            return count > 0
        except:
            return False

    async def click_join_meet_button(self) -> bool:
        """Click the 'Join now' or 'Switch here' button."""
        try:
            join_button = self.page.locator('button:has-text("Join now")')
            switch_here_button = self.page.locator('button:has-text("Switch here")')
            if await join_button.count() == 0 and await switch_here_button.count() > 0:
                join_button = switch_here_button
                logger.debug("Using 'Switch here' button instead of 'Join now'")
            await join_button.wait_for(timeout=10000)
            await join_button.click()
            logger.info("Successfully clicked 'Join now' button")
            return True
        except Exception as e:
            logger.error(f"Failed to click 'Join now' button: {e}")
            return False