"""
Browser lifecycle management.

Architecture:
    BrowserManager
        └── Chromium browser
              ├── MeetingBrowserSession
              │     ├── BrowserContext
              │     └── Page
              │
              ├── MeetingBrowserSession
              │     ├── BrowserContext
              │     └── Page
              │
              └── ...

One BrowserManager owns one Chromium process.
Each meeting gets its own isolated BrowserContext and Page.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
)

from utilities.env_config import config
from utilities.meet_utils.google_meet.js_helpers import (
    UNSET_WEB_DRIVER,
    INITIALIZE_SEPRATE_AUDIO_CHANNELS_FOR_REMOTE_AND_INPUT,
)

logger = logging.getLogger(__name__)

PROFILE_DIR = Path(config.get('PROFILE_DIR'))

@dataclass
class MeetingBrowserSession:
    """Browser resources belonging to one meeting."""

    meeting_id: str
    context: BrowserContext
    page: Page



class BrowserManager:
    """
    Manages the application's Chromium process and per-meeting sessions.

    One BrowserManager:
        one Playwright instance
        one Chromium browser

    Each meeting:
        one BrowserContext
        one Page
    """

    def __init__(
        self,
        profile_dir: Path = PROFILE_DIR,
        max_retries: int = 3,
        retry_delay: float = 3.0,
        timeout_ms: int = 30_000,
    ):
        self.profile_dir = profile_dir
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout_ms = timeout_ms

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.sessions: Dict[str, MeetingBrowserSession] = {}

        self._startup_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

    # ================================================================
    # Browser lifecycle
    # ================================================================

    async def start(self, use_persistent_context: bool = True) -> bool:
        """Start Playwright and Chromium with conditional persistent profile support.
        
        Args:
            use_persistent_context: If True, attempts to use persistent browser context.
                                   Falls back to ephemeral if profile directory unavailable.
        
        Returns:
            True if persistent context is being used, False if ephemeral session.
        """

        if self._is_browser_alive():
            return use_persistent_context

        async with self._startup_lock:

            if self._is_browser_alive():
                return use_persistent_context

            for attempt in range(1, self.max_retries + 1):

                try:
                    logger.info(
                        f"Starting browser "
                        f"(attempt {attempt}/{self.max_retries})"
                    )

                    self.playwright = await async_playwright().start()

                    headless = self._get_headless()

                    # Check if persistent profile can be used
                    is_persistent = False
                    if use_persistent_context:
                        try:
                            if self.profile_dir.exists():
                                is_persistent = True
                                logger.info(
                                    f"Profile directory exists: {self.profile_dir}. "
                                    "Using persistent context."
                                )
                            else:
                                logger.warning(
                                    f"Profile directory not found: {self.profile_dir}. "
                                    "Using ephemeral session."
                                )
                        except Exception as e:
                            logger.warning(
                                f"Failed to check profile directory: {e}. "
                                "Using ephemeral session."
                            )

                    if is_persistent:
                        # Launch with persistent context
                        self.context = await self.playwright.chromium.launch_persistent_context(
                            user_data_dir=str(self.profile_dir.resolve()),
                            headless=headless,
                            channel="chromium",
                            permissions=["microphone", "camera"],
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--start-maximized",
                                "--use-fake-device-for-media-stream",
                                "--use-fake-ui-for-media-stream",
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage",
                            ],
                            viewport=None,
                            timeout=self.timeout_ms,
                        )
                        logger.info(
                            f"Chromium started with persistent context "
                            f"(headless={headless})"
                        )
                    else:
                        # Launch normal chromium
                        self.browser = await self.playwright.chromium.launch(
                            headless=headless,
                            channel="chromium",
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--start-maximized",
                                "--use-fake-device-for-media-stream",
                                "--use-fake-ui-for-media-stream",
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage",
                            ],
                        )
                        logger.info(
                            f"Chromium started in ephemeral mode "
                            f"(headless={headless})"
                        )

                    return is_persistent

                except Exception:
                    logger.exception(
                        f"Failed to start browser "
                        f"(attempt {attempt}/{self.max_retries})"
                    )

                    await self._cleanup_browser()

                    if attempt >= self.max_retries:
                        raise

                    await asyncio.sleep(self.retry_delay)

    def _get_headless(self) -> bool:
        try:
            return config.get_bool("HEADLESS")
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "Invalid HEADLESS config. "
                "Defaulting to headless=True."
            )
            return True

    def _is_browser_alive(self) -> bool:
        return (
            self.playwright is not None
            and self.browser is not None
            and self.browser.is_connected()
        )

    # ================================================================
    # Meeting sessions
    # ================================================================

    async def initialize_and_navigate(
        self,
        meeting_url: str,
    ) -> bool:
        """Initialize browser and navigate to meeting URL.
        
        Handles both persistent and ephemeral context initialization,
        with fallback logic and JS script injection.
        
        Args:
            meeting_url: URL of the meeting to join.
        
        Returns:
            True if using persistent context, False if ephemeral.
        
        Raises:
            PermissionError: If meeting requires Google Sign-In (anonymous join not allowed).
            RuntimeError: If browser initialization fails after retries.
        """
        use_persistent_context = await self.start(use_persistent_context=True)

        if not self.context:
            raise RuntimeError("Failed to initialize browser context")

        # If using ephemeral context with persistent browser, create context
        if not use_persistent_context and self.browser:
            self.context = await self.browser.new_context(
                permissions=["microphone", "camera"],
                viewport=None,
            )

        await self._configure_context(self.context)

        # Get or create page
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        await self._configure_page(self.page)

        # Inject initialization scripts
        await self.context.add_init_script(UNSET_WEB_DRIVER)
        await self.page.add_init_script(
            INITIALIZE_SEPRATE_AUDIO_CHANNELS_FOR_REMOTE_AND_INPUT
        )

        # Navigate to meeting URL
        logger.debug(f"Navigating to meeting URL: {meeting_url}")

        await self.page.goto(
            meeting_url,
            timeout=self.timeout_ms,
            wait_until="domcontentloaded",
        )

        # Check for Google Sign-In requirement
        if "accounts.google.com" in self.page.url:
            logger.error("Meeting requires Google Sign-In. Aborting anonymous join.")
            raise PermissionError("Meeting requires Google Sign-In.")

        logger.info("Browser initialized and navigated successfully")
        return use_persistent_context

    async def create_meeting_session(
        self,
        meeting_url: str,
        meeting_id: Optional[str] = None,
    ) -> MeetingBrowserSession:
        """
        Create an isolated browser session for a meeting.
        
        Note: For direct initialization with navigation, use initialize_and_navigate().
        This method is for managing separate contexts on an already-running browser.
        """

        async with self._session_lock:

            existing = self.sessions.get(meeting_id)

            if existing:
                logger.info(
                    f"Reusing existing browser session "
                    f"for meeting {meeting_id}"
                )

                return existing

            await self.start(use_persistent_context=False)

            if not self.browser:
                raise RuntimeError(
                    "Browser is not available"
                )

            logger.info(
                f"Creating browser session "
                f"for meeting {meeting_id}"
            )

            self.context = await self.browser.new_context(
                permissions=[
                    "microphone",
                    "camera",
                ],
                viewport=None,
            )

            await self._configure_context(self.context)

            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            await self._configure_page(self.page)

            await self.page.goto(
                meeting_url,
                timeout=self.timeout_ms,
                wait_until="domcontentloaded",
            )

            session = MeetingBrowserSession(
                meeting_id=meeting_id,
                context=self.context,
                page=self.page,
            )

            self.sessions[meeting_id] = session

            logger.info(
                f"Meeting browser session ready: "
                f"{meeting_id}"
            )

            return session

    async def get_meeting_session(
        self,
        meeting_id: str,
    ) -> Optional[MeetingBrowserSession]:
        return self.sessions.get(meeting_id)

    async def close_meeting_session(
        self,
        meeting_id: str,
    ) -> None:
        """Close only the browser resources for one meeting."""

        async with self._session_lock:

            session = self.sessions.pop(
                meeting_id,
                None,
            )

            if not session:
                return

            logger.info(
                f"Closing browser session "
                f"for meeting {meeting_id}"
            )

            try:
                await session.context.close()
            except Exception:
                logger.exception(
                    f"Failed closing browser context "
                    f"for {meeting_id}"
                )

    # ================================================================
    # Browser configuration
    # ================================================================

    async def _configure_context(
        self,
        context: BrowserContext,
    ) -> None:
        """Install context-wide browser configuration."""

        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        )

    async def _configure_page(
        self,
        page: Page,
    ) -> None:
        """
        Configure WebRTC audio stream collection.

        Each meeting page owns its own remoteAudioStreams array.
        """

        await page.add_init_script(
            """
            (() => {
                if (window.__stormeeAudioInitialized) {
                    return;
                }

                window.__stormeeAudioInitialized = true;
                window.remoteAudioStreams = [];

                const OriginalRTCPeerConnection =
                    window.RTCPeerConnection;

                if (!OriginalRTCPeerConnection) {
                    console.warn(
                        "RTCPeerConnection unavailable"
                    );
                    return;
                }

                window.RTCPeerConnection = function (...args) {

                    const pc =
                        new OriginalRTCPeerConnection(...args);

                    pc.addEventListener(
                        "track",
                        (event) => {

                            if (event.track.kind !== "audio") {
                                return;
                            }

                            const stream =
                                event.streams?.[0];

                            if (!stream) {
                                return;
                            }

                            window.remoteAudioStreams.push(
                                stream
                            );

                            try {
                                const audio =
                                    document.createElement(
                                        "audio"
                                    );

                                audio.srcObject = stream;
                                audio.autoplay = true;
                                audio.muted = true;

                                document.body.appendChild(
                                    audio
                                );
                            } catch (error) {
                                console.error(
                                    "Failed to attach remote audio:",
                                    error
                                );
                            }

                            window.dispatchEvent(
                                new CustomEvent(
                                    "remoteStreamAdded",
                                    {
                                        detail: stream
                                    }
                                )
                            );
                        }
                    );

                    return pc;
                };

                window.RTCPeerConnection.prototype =
                    OriginalRTCPeerConnection.prototype;
            })();
            """
        )

    # ================================================================
    # Shutdown
    # ================================================================

    async def close(self) -> None:
        """Close all meeting sessions and Chromium."""

        async with self._session_lock:

            sessions = list(
                self.sessions.items()
            )

            self.sessions.clear()

            for meeting_id, session in sessions:
                try:
                    await session.context.close()
                except Exception:
                    logger.exception(
                        f"Failed closing session "
                        f"for {meeting_id}"
                    )

        await self._cleanup_browser()

    async def _cleanup_browser(self) -> None:

        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                logger.exception(
                    "Failed to close Chromium"
                )

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                logger.exception(
                    "Failed to stop Playwright"
                )

        self.browser = None
        self.playwright = None

        logger.info("Browser manager shut down")