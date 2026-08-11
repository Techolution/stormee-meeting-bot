import asyncio
import os
import logging
import platform
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import uuid
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import socketio
from dotenv import load_dotenv
import re

# Get module-level logger
logger = logging.getLogger(__name__)

from utilities.doc_utils import save_captions_to_docx
from utilities.cw_utils import cw_caller
from utilities.mail_utils import email_sender
from utilities.meet_utils.google_meet.meet_action_controller import ActionController
from utilities.env_config import config
from services.websocket_manager import WebSocketManager
from services.audio_queue_manager import AudioQueueManager
from utilities.error_handler import (
    log_exception,
    handle_browser_error,
    handle_websocket_error,
    handle_audio_error,
    handle_file_error,
)

load_dotenv()

PROFILE_DIR = Path(config.get('PROFILE_DIR'))
project_id = config.get('PROJECT_ID')
project_name = config.get('PROJECT_NAME')

class MeetBot:
    def __init__(self):
        self.action_controller = ActionController(lambda: self.page)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.browser_type = "chromium"  # Track which browser is being used
        
        # State management
        self.captions_segments: List[Dict] = []
        self.scraping_active = False
        self.chat_segments: List[Dict] = []
        self.live_caption_buffer: List[Dict] = []
        self.chat_scraping_active = False
        self.participant_count = 0
        self.current_meeting_id: Optional[str] = None
        self.audio_chunks: Dict[str, List] = {}
        
        # Tasks
        self.caption_task: Optional[asyncio.Task] = None
        self.participant_task: Optional[asyncio.Task] = None
        
        # WebSocket and Audio Buffering
        self.websocket_manager = WebSocketManager()
        self.audio_queue_manager = AudioQueueManager.get_instance(
            max_chunks=config.get('AUDIO_QUEUE_MAX_CHUNKS'),
            max_memory_bytes=config.get('AUDIO_QUEUE_MAX_MEMORY_MB') * 1024 * 1024
        )
        
        # Register reconnection success callback
        self.websocket_manager.set_on_reconnect_success(self._on_websocket_reconnect)

    async def ensure_auth_session(self, meeting_url: str):
        """Initialize browser with a persistent Google Chrome profile"""
        logger.info("Initializing browser with persistent profile")

        self.playwright = await async_playwright().start()

        # Ensure the profile directory exists
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        # Set headless based on environment (Headless=True inside Docker/Production)
        try:
            is_headless = config.get_bool('HEADLESS')
        except ValueError:
            is_headless = True  # Default to False if not set

        # Launch browser with persistent storage directory
        self.context = (
            await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR.resolve()),
                headless=is_headless,
                channel="chromium",  # Uses local Chromium installation
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
                viewport=None,  # Matches window size
            )
        )
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Persistent contexts open with an existing page by default
        if len(self.context.pages) > 0:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        # Audio stream capture hook
        await self.page.add_init_script("""
            window.remoteAudioStreams = [];
            const OriginalRTCPeerConnection = window.RTCPeerConnection;
            window.RTCPeerConnection = function (...args) {
                const pc = new OriginalRTCPeerConnection(...args);
                pc.addEventListener('track', (event) => {
                    if (event.track.kind === 'audio') {
                        const remoteStream = event.streams[0];
                        const audio = document.createElement('audio');
                        audio.srcObject = remoteStream;
                        audio.autoplay = true;
                        audio.muted = true;
                        document.body.appendChild(audio);
                        window.remoteAudioStreams.push(remoteStream);
                    }
                });
                return pc;
            };
        """)

        logger.debug(f"Navigating to meeting URL: {meeting_url}")
        await self.page.goto(meeting_url)


    async def pause_camera_in_meet(self):
        try:
            # Target aria-label specifically for turning OFF the camera (case-insensitive)
            cam_button = self.page.locator(
                '[aria-label*="Turn off camera" i], [aria-label*="turn off camera" i]'
            ).first

            logger.debug("Checking for camera button")

            # 1. Wait for element to be visible (Replaces count > 0)
            await cam_button.wait_for(state="visible", timeout=8000)

            # 2. Click with force=True to bypass any overlay or animation backdrop
            await cam_button.click(force=True)
            logger.debug("Camera paused using aria-label")

        except Exception as e:
            logger.warning(f"Could not pause camera via aria-label: {e}")

    async def check_meeting_status(self) -> str:
        """Detects whether the bot is in the LOBBY or IN_MEETING, handling auto-hidden control bars."""
        if not self.page or self.page.is_closed():
            return "UNKNOWN"

        try:
            # Step 1: Wiggle mouse slightly to wake up auto-hidden control bars
            try:
                await self.page.mouse.move(100, 100)
            except Exception:
                pass

            status = await self.page.evaluate("""
                () => {
                    // 1. CHECK LOBBY / WAITING ROOM
                    const lobbyText = document.querySelector('.U0e0y');
                    const progressBar = document.querySelector('[aria-label*="Please wait" i]');
                    const waitingNotice = Array.from(document.querySelectorAll('div')).find(
                        el => el.textContent && el.textContent.includes('Please wait until a meeting host brings you into the call')
                    );

                    if (lobbyText || progressBar || waitingNotice) {
                        return "LOBBY";
                    }

                    // 2. CHECK IN-MEETING INDICATORS (Fixed JS comment syntax)
                    // A. Leave/End Call Button
                    const leaveBtn = document.querySelector('[aria-label*="Leave call" i]') || 
                                    document.querySelector('[aria-label*="End call" i]') ||
                                    document.querySelector('[jsname="CQylK"]');
                    
                    // B. Participant Tiles / Grid View
                    const participantTile = document.querySelector('[data-participant-id]') || 
                                            document.querySelector('[data-requested-participant-id]') ||
                                            document.querySelector('.Gv138b') ||
                                            document.querySelector('video');

                    // C. Top/Bottom Action Bar or Chat/People Toggle
                    const chatToggle = document.querySelector('[aria-label*="Chat with everyone" i]') ||
                                       document.querySelector('[aria-label*="Show chat" i]');
                    const peopleToggle = document.querySelector('[aria-label*="People" i]') ||
                                         document.querySelector('[aria-label*="Show everyone" i]');

                    if (leaveBtn || participantTile || chatToggle || peopleToggle) {
                        return "IN_MEETING";
                    }

                    return "UNKNOWN";
                }
            """)
            return status

        except Exception as e:
            return "UNKNOWN"

    async def join_meeting(self, meeting_url: str):
        logger.info(f"Joining meeting: {meeting_url}")
        
        await self.ensure_auth_session(meeting_url)
        guest_name = "Stormee.Ai"

        try:
            as_guest = config.get_bool('JOIN_AS_GUEST')
        except ValueError:
            as_guest = False  # Default to False if not set
        if as_guest:
            logger.debug("Waiting for preview interface to stabilize")
            await asyncio.sleep(4)
            await self.join_as_guest(guest_name)
            await self.pause_camera_in_meet()

        else:
            await self.action_controller.pause_audio()
            await self.action_controller.pause_camera()
            await self.action_controller.click_join_meet_button()
        
        # --- FIXED LOBBY & ADMISSION WAIT LOGIC ---
        max_admission_wait = 300  # Wait up to 5 minutes for host to admit
        waited = 0
        is_admitted = False

        logger.debug("Polling meeting status, waiting for host admission")
        while waited < max_admission_wait:
            status = await self.check_meeting_status()

            if status == "IN_MEETING":
                logger.info("Bot admitted to meeting room")
                is_admitted = True
                break
            elif status == "LOBBY":
                if waited % 10 == 0:
                    logger.debug("Still in lobby, waiting for host admission")

            await asyncio.sleep(2)
            waited += 2

        if not is_admitted:
            logger.error("Timed out or failed to enter meeting room. Aborting post-join actions")
            return

        # Ensure mic is muted once inside the active meeting
        try:
            if await self.action_controller.is_mic_on():
                await self.action_controller.pause_audio()
        except Exception as e:
            logger.warning(f"Warning checking mic status: {e}")

        # Start post-admission services
        # await self.start_chat_scraping()
        # logger.info(f"Joined meeting using {self.browser_type}")
        # await self.start_captions()

        self.participant_count = await self.get_participant_count()
        await self.start_participant_monitoring()
        logger.debug(f"Participant count: {self.participant_count}")
        
    async def start_captions(self):
        """Start caption scraping"""
        self.captions_segments = []
        self.scraping_active = True
        await self.turn_captions_on()
        self.caption_task = asyncio.create_task(self.scrape_captions())
        logger.info("Caption scraping started")

    async def scrape_captions(self):
        """Monitors live captions and maintains only active speaker blocks."""
        captions_container_selector = '[aria-label="Captions"]'

        while self.scraping_active:
            try:
                container = self.page.locator(captions_container_selector).first

                if await container.count() > 0:
                    rows = await container.locator("> div").all()

                    # Temporary storage for the current snapshot of the DOM
                    current_snapshot = []

                    for row in rows:
                        row_text = await row.inner_text()
                        if not row_text or "Jump to bottom" in row_text:
                            continue

                        lines = [
                            line.strip()
                            for line in row_text.split("\n")
                            if line.strip()
                        ]

                        if len(lines) >= 2:
                            speaker = lines[0]
                            text = " ".join(lines[1:])

                            current_snapshot.append(
                                {
                                    "speaker": speaker,
                                    "text": text,
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )

                    # Keep only the latest live DOM state in buffer
                    self.live_caption_buffer = current_snapshot

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error scraping captions: {e}")
                await asyncio.sleep(2)

    async def stop_captions(self) -> List[Dict]:
        """Stops caption scraping and returns the deduplicated final transcript."""
        self.scraping_active = False

        if self.caption_task:
            self.caption_task.cancel()
            try:
                await self.caption_task
            except asyncio.CancelledError:
                pass

        # Post-process to remove identical adjacent duplicate turns
        final_captions = []
        for entry in getattr(self, "live_caption_buffer", []):
            # Prevent exact duplicate phrases from appearing twice
            if not final_captions or final_captions[-1]["text"] != entry["text"]:
                final_captions.append(entry)

        self.captions_segments = final_captions
        logger.info(f"Caption scraping stopped, {len(final_captions)} blocks saved")
        return self.captions_segments
        
    async def turn_captions_on(self):
        """Enable captions"""
        try:
            button = self.page.locator('[aria-label*="caption"], button:has-text("Turn on captions")').first
            if await button.count() > 0:
                await button.click()
                logger.debug("Captions enabled")
            else:
                await self.page.keyboard.press("c")
                logger.debug("Could not find captions, trying keyboard shortcut")
        except Exception as e:
            logger.error(f"Error enabling captions: {e}")

    async def start_chat_scraping(self):
        """Hard-fix chat scraper using continuous Python-side polling"""
        self.chat_segments = []
        self.chat_scraping_active = True

        # 1. Open the Chat Panel explicitly
        logger.debug("Ensuring chat panel is open")
        for _ in range(5):
            try:
                chat_button = self.page.locator(
                    '[aria-label="Show chat"], [aria-label*="chat" i], button:has-text("Chat")'
                ).first
                if await chat_button.count() > 0:
                    await chat_button.click()
                    await asyncio.sleep(1.5)
                    break
            except Exception:
                await asyncio.sleep(1)

        # Background task that polls Google Meet chat directly
        async def poll_chat():
            processed_ids = set()
            logger.info("Chat polling loop started")

            while self.chat_scraping_active:
                try:
                    if not self.page or self.page.is_closed():
                        break

                    # Raw JS execution that extracts all current messages directly from DOM
                    messages = await self.page.evaluate("""
                        () => {
                            const results = [];
                            // Find all elements with data-message-id anywhere on page
                            const msgNodes = document.querySelectorAll('[data-message-id]');

                            msgNodes.forEach(node => {
                                const id = node.getAttribute('data-message-id');
                                if (!id || !id.includes('messages/')) return;

                                // Extract Text: Try jsname="dTKtvb", fallback to innerText
                                const textEl = node.querySelector('[jsname="dTKtvb"]') || node;
                                const text = textEl ? textEl.innerText.trim() : '';

                                if (!text) return;

                                // Extract Sender: Walk up to parent block wrapper
                                let sender = 'Unknown';
                                let parent = node.parentElement;

                                for (let i = 0; i < 8 && parent; i++) {
                                    const nameEl = parent.querySelector('.poVWob');
                                    if (nameEl && nameEl.innerText.trim()) {
                                        sender = nameEl.innerText.trim();
                                        break;
                                    }
                                    const imgEl = parent.querySelector('img[alt]');
                                    if (imgEl && imgEl.getAttribute('alt')) {
                                        sender = imgEl.getAttribute('alt').trim();
                                        break;
                                    }
                                    parent = parent.parentElement;
                                }

                                results.push({ id, sender, text });
                            });

                            return results;
                        }
                    """)

                    # Process new messages found during this poll tick
                    for msg in messages:
                        msg_id = msg["id"]
                        if msg_id not in processed_ids:
                            processed_ids.add(msg_id)

                            formatted_msg = {
                                "sender": msg["sender"],
                                "text": msg["text"],
                                "timestamp": datetime.now().isoformat(),
                                "messageId": msg_id,
                            }

                            self.chat_segments.append(formatted_msg)
                            logger.debug(
                                f"CHAT [{msg['sender']}]: {msg['text']}"
                            )

                            # Handle Commands
                            text_lower = msg["text"].lower()

                            if "stormee start recording" in text_lower:
                                if not self.current_meeting_id:
                                    mid = f"meeting-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                                    logger.info(
                                        f"Executing command: Start Audio Recording -> {mid}"
                                    )
                                    asyncio.create_task(
                                        self.start_audio_recording(mid)
                                    )

                            elif "stormee start caption recording" in text_lower:
                                if not self.scraping_active:
                                    logger.info(
                                        "Executing command: Start Captions"
                                    )
                                    asyncio.create_task(self.start_captions())

                            elif "stormee stop recording" in text_lower:
                                if self.current_meeting_id:
                                    logger.info(
                                        f"Executing command: Stop Recording -> {self.current_meeting_id}"
                                    )
                                    asyncio.create_task(
                                        self.stop_audio_recording()
                                    )

                    await asyncio.sleep(1)  # Poll every 1 second

                except Exception as e:
                    # Ignore minor navigation/evaluation glitches during screen changes
                    await asyncio.sleep(2)

        # Start the polling task
        asyncio.create_task(poll_chat())

    async def stop_chat_scraping(self) -> List[Dict]:
        """Stop chat monitoring"""
        self.chat_scraping_active = False
        logger.info("Chat monitoring stopped")
        return self.chat_segments

    async def get_participant_count(self) -> int:
        """Get participant count"""
        if not self.page:
            return 0
        
        for attempt in range(1, 9):
            try:
                await self.page.wait_for_selector('[data-participant-id]', timeout=10000)
                elements = await self.page.query_selector_all('[data-participant-id]')
                count = len(elements)
                logger.debug(f"Participants: {count}")
                return count
            except:
                if attempt < 8:
                    await asyncio.sleep(5)
                else:
                    return 0
        return 0

    async def start_participant_monitoring(self):
        """Monitor participants"""
        if self.participant_task:
            return
        
        async def monitor():
            last = self.participant_count
            while self.chat_scraping_active:
                try:
                    new = await self.get_participant_count()
                    if new != last:
                        logger.debug(f"Participants changed: {last} to {new}")
                        self.participant_count = new
                    last = new
                    
                    # if new == 1:
                    #     print("⚠️ Only bot remains, leaving")
                    #     await self.leave_meeting()
                    #     break
                    
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Monitor error: {e}")
                    await asyncio.sleep(2)
        
        self.participant_task = asyncio.create_task(monitor())

    async def stop_participant_monitoring(self):
        """Stop monitoring"""
        if self.participant_task:
            self.participant_task.cancel()
            try:
                await self.participant_task
            except asyncio.CancelledError:
                pass

    async def leave_meeting(self):
        """Safely leaves the meeting room and closes browser contexts."""
        if not self.page or self.page.is_closed():
            logger.warning("Page is already closed")
            return

        logger.info("Leaving meeting")

        try:
            # 1. Stop background scraping tasks gracefully
            for task_fn in [
                self.stop_chat_scraping,
                self.stop_audio_recording,
                self.stop_captions,
                self.stop_participant_monitoring,
            ]:
                try:
                    if callable(task_fn):
                        await task_fn()
                except Exception as task_err:
                    logger.warning(f"Non-fatal error stopping background task: {task_err}")

            # try:
            #     # Use per-bot metadata if available, otherwise fall back to environment/defaults
            #     if hasattr(self, 'user_name') and self.user_name:
            #         user_name = self.user_name
            #     else:
            #         try:
            #             user_name = config.get('DEFAULT_USER_NAME')
            #         except ValueError:
            #             user_name = 'Unknown User'
                
            #     if hasattr(self, 'user_email') and self.user_email:
            #         user_email = self.user_email
            #     else:
            #         try:
            #             user_email = config.get('DEFAULT_USER_EMAIL')
            #         except ValueError:
            #             user_email = 'no-reply@example.com'
            #     proj_name = getattr(self, 'project_name', project_name)
            #     proj_id = getattr(self, 'project_id', project_id)
            #     meeting_title = getattr(self, 'meeting_title', f"Meeting {datetime.now().strftime('%Y-%m-%d')}")

            #     filename = await save_captions_to_docx(captions_segments=self.captions_segments, title = meeting_title)
            #     if filename:
            #         response_json = await cw_caller.upload_file(
            #             file_path=filename,
            #             project_id=project_id,
            #             display_name=meeting_title
            #         )
            #         if len(response_json.get("uploaded")) > 0:
            #             logger.info(f"Captions uploaded to CW: {response_json['uploaded'][0].get('name')}")
            #             cleanup_path = Path(filename)
            #             if cleanup_path.exists():
            #                 cleanup_path.unlink()
            #                 logger.debug(f"Deleted local file: {cleanup_path}")

            #             await email_sender.send_meeting_file_uploaded_email(
            #                         user_name=user_name,
            #                         user_email=user_email,
            #                         project_name=proj_name,
            #                         project_url=f"https://dev.appmod.ai/mode/Project%20Mode/projects/{proj_id}",
            #                         meeting_title=meeting_title,
            #                         file_type="transcript"
            #                     )
            # except Exception as docx_err:
            #     logger.warning(f"Failed to save captions to DOCX: {docx_err}")
            
            # 2. Wake up hidden bottom control bar by wiggling mouse
            try:
                await self.page.mouse.move(200, 200)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # 3. Target Leave Button using jsname="CQylAd" or wildcard aria-label
            logger.debug("Clicking Leave call button")
            leave_clicked = await self.page.evaluate("""
                () => {
                    const btn = document.querySelector('[aria-label*="Leave call" i]') ||
                                document.querySelector('[aria-label*="End call" i]');
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    return false;
                }
            """)

            if not leave_clicked:
                # Playwright Force Click Fallback
                leave_button = self.page.locator(
                    'button[aria-label*="Leave call" i]'
                ).first
                if await leave_button.count() > 0:
                    await leave_button.click(force=True)

            logger.info("Successfully clicked Leave Call button")
            await asyncio.sleep(1.5)

        except Exception as e:
            logger.warning(f"Error clicking leave button: {e}")

        # 4. Clean up Playwright Contexts safely
        finally:
            try:
                if self.page and not self.page.is_closed():
                    await self.page.close()
                if self.context:
                    await self.context.close()
                if hasattr(self, "playwright") and self.playwright:
                    await self.playwright.stop()
            except Exception as cleanup_err:
                logger.warning(f"Cleanup warning: {cleanup_err}")

            # Reset state variables
            self.page = None
            self.context = None
            self.browser = None
            logger.info("Left meeting and cleaned up browser resources")

    async def play_audio(self):
        try:
            mic_button = self.page.locator('[aria-label*="microphone"], [aria-label*="mic"]').first
            if await mic_button.count() > 0:
                await mic_button.click()
                logger.info("Audio enabled")
        except Exception as e:
            logger.error(f"Error enabling audio: {e}")

    async def start_audio_recording(self, meeting_id: str):
        """Start recording audio"""
        if not self.page:
            logger.error("No page available")
            return
        
        self.current_meeting_id = meeting_id
        if meeting_id not in self.audio_chunks:
            self.audio_chunks[meeting_id] = []
        
        logger.info(f"Starting audio recording for meeting: {meeting_id}")
        
        # WebSocket connection - establish connection with configured URL
        ws_url = config.get('WEBSOCKET_URL')
        await self.websocket_manager.connect(ws_url)
        
        # Log connection state
        connection_state = self.websocket_manager.get_connection_state()
        if connection_state == "active":
            logger.info(f"WebSocket connected with state: {connection_state}")
        else:
            logger.warning(f"WebSocket not connected; state: {connection_state}")
            logger.warning("Audio will be saved locally, no real-time streaming")
        
        # Check if function is already exposed
        is_function_exposed = await self.page.evaluate("""
            () => typeof window.sendAudioChunkToPython === 'function'
        """)
        
        if not is_function_exposed:
            async def handle_chunk_wrapper(chunk):
                await self._handle_audio_chunk(chunk)
            
            await self.page.expose_function(
                'sendAudioChunkToPython',
                handle_chunk_wrapper
            )
            logger.debug("Exposed sendAudioChunkToPython function")
        else:
            logger.debug("sendAudioChunkToPython already exposed, skipping")
        
        # Start recording with SMALLER chunk interval
        await self.page.evaluate("""
            async (meetingId) => {
                try {
                    if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
                        window.mediaRecorder.stop();
                        console.log("🛑 Stopped existing recorder");
                    }
                    
                    const audioCtx = new AudioContext();
                    const destination = audioCtx.createMediaStreamDestination();
                    
                    if (window.remoteAudioStreams && window.remoteAudioStreams.length > 0) {
                        window.remoteAudioStreams.forEach((stream) => {
                            const remoteSource = audioCtx.createMediaStreamSource(stream);
                            remoteSource.connect(destination);
                            console.log("🔊 Connected remote stream");
                        });
                    } else {
                        console.warn("⚠️ No remote audio streams yet");
                    }
                    
                    window.addEventListener("remoteStreamAdded", (event) => {
                        const stream = event.detail;
                        const remoteSource = audioCtx.createMediaStreamSource(stream);
                        remoteSource.connect(destination);
                        console.log("🔊 Connected new remote stream");
                    });
                    
                    const mixedStream = destination.stream;
                    const mediaRecorder = new MediaRecorder(mixedStream, {
                        mimeType: "audio/webm; codecs=opus"
                    });
                    
                    window.mediaRecorder = mediaRecorder;
                    window.chunkCounter = 0;
                    
                    mediaRecorder.ondataavailable = async (event) => {
                        if (event.data.size > 0) {
                            const chunkId = `${meetingId}-${window.chunkCounter++}`;
                            const timestamp = new Date().toISOString();
                            const arrayBuffer = await event.data.arrayBuffer();
                            const audioBlob = Array.from(new Uint8Array(arrayBuffer));
                            
                            console.log(`📤 Chunk ready: ${chunkId}, size: ${event.data.size} bytes`);
                            
                            if (window.sendAudioChunkToPython) {
                                try {
                                    await window.sendAudioChunkToPython({
                                        meetingId: meetingId,
                                        chunkId: chunkId,
                                        timestamp: timestamp,
                                        audioBlob: audioBlob
                                    });
                                } catch (error) {
                                    console.error("❌ Error sending chunk:", error);
                                }
                            } else {
                                console.error("❌ sendAudioChunkToPython not available");
                            }
                        }
                    };
                    
                    mediaRecorder.onerror = (event) => {
                        console.error("❌ MediaRecorder error:", event.error);
                    };
                    
                    mediaRecorder.onstop = () => {
                        console.log("🛑 MediaRecorder stopped");
                    };
                    
                    // ✅ FIX: Use 5-second chunks instead of 60 seconds for faster feedback
                    mediaRecorder.start(5000);
                    console.log("✅ Recording started for:", meetingId);
                } catch (error) {
                    console.error("❌ Error starting recording:", error);
                }
            }
        """, meeting_id)
        
        logger.info(f"Recording started for {meeting_id}")

    async def _handle_audio_chunk(self, chunk: dict):
        """Handle audio chunk"""
        meeting_id = chunk.get('meetingId')
        chunk_id = chunk.get('chunkId')
        audio_blob = chunk.get('audioBlob', [])
        
        logger.debug(f"Chunk: {chunk_id}, size: {len(audio_blob)} bytes")
        
        # Store chunk locally
        if meeting_id not in self.audio_chunks:
            self.audio_chunks[meeting_id] = []
        
        self.audio_chunks[meeting_id].append(chunk)
        
        # Send via WebSocket if connected; otherwise queue for later transmission
        if self.websocket_manager.is_connected():
            try:
                sio = self.websocket_manager.get_instance()
                await sio.emit('audioChunk', chunk)
                logger.debug(f"Sent to WebSocket: {chunk_id}")
            except Exception as e:
                logger.warning(f"WebSocket send failed: {e}")
                # Enqueue for retry on reconnection
                self.audio_queue_manager.enqueue(chunk)
                logger.debug(f"Chunk queued for later transmission: {chunk_id}")
        else:
            # WebSocket not connected; enqueue chunk for transmission on reconnect
            self.audio_queue_manager.enqueue(chunk)
            queue_stats = self.audio_queue_manager.get_stats()
            logger.debug(
                f"WebSocket not connected, chunk queued: {chunk_id}; "
                f"queue size={queue_stats['queue_size']}, memory={queue_stats['memory_bytes']} bytes"
            )
    
    async def _on_websocket_reconnect(self) -> None:
        """Callback invoked on successful WebSocket reconnection.
        
        Drains all buffered audio chunks from the queue and transmits them
        via the re-established WebSocket connection.
        """
        logger.info("WebSocket reconnected; draining buffered audio chunks")
        
        buffered_chunks = self.audio_queue_manager.dequeue_all()
        if not buffered_chunks:
            logger.debug("No buffered chunks to drain")
            return
        
        logger.info(f"Draining {len(buffered_chunks)} buffered chunks")
        sio = self.websocket_manager.get_instance()
        
        for chunk in buffered_chunks:
            try:
                chunk_id = chunk.get('chunkId')
                await sio.emit('audioChunk', chunk)
                logger.debug(f"Drained buffered chunk: {chunk_id}")
            except Exception as e:
                logger.error(f"Failed to drain buffered chunk {chunk.get('chunkId')}: {e}")
                # Re-queue chunk if transmission fails
                self.audio_queue_manager.enqueue(chunk)
        
        logger.info(f"Audio queue drain complete; {self.audio_queue_manager.get_queue_size()} chunks remaining")
    
    async def save_audio(self, meeting_id: str):
        """Save audio to file"""
        if not self.audio_chunks.get(meeting_id):
            logger.warning(f"No audio chunks received for {meeting_id}")
            return
        
        chunk_count = len(self.audio_chunks[meeting_id])
        logger.info(f"Saving audio for {meeting_id} ({chunk_count} chunks)")
        
        # Sort chunks by their numeric ID
        sorted_chunks = sorted(
            self.audio_chunks[meeting_id],
            key=lambda x: int(x['chunkId'].split('-')[-1])
        )
        
        # Combine all audio chunks
        audio_data = b''.join(bytes(chunk['audioBlob']) for chunk in sorted_chunks)
        
        if len(audio_data) == 0:
            logger.warning(f"No audio data in chunks for {meeting_id}")
            return
        rec_id = uuid.uuid4()
        # Save as WebM
        webm_path = f"{meeting_id.replace('/', '_').replace(':', '_')}_{rec_id}.webm"
        with open(webm_path, 'wb') as f:
            f.write(audio_data)
        logger.info(f"Saved {webm_path} ({len(audio_data)} bytes)")
        
        # Convert to MP3 using ffmpeg
        mp3_path = f"{meeting_id.replace('/', '_').replace(':', '_')}_{rec_id}.mp3"
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y',
                '-i', webm_path,
                '-acodec', 'libmp3lame',
                '-b:a', '64k',
                '-ar', '16000',
                '-ac', '1',
                mp3_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Converted to {mp3_path}")
                if hasattr(self, 'user_name') and self.user_name:
                    user_name = self.user_name
                else:
                    try:
                        user_name = config.get('DEFAULT_USER_NAME')
                    except ValueError:
                        user_name = 'Unknown User'
                
                if hasattr(self, 'user_email') and self.user_email:
                    user_email = self.user_email
                else:
                    try:
                        user_email = config.get('DEFAULT_USER_EMAIL')
                    except ValueError:
                        user_email = 'no-reply@example.com'
                proj_name = getattr(self, 'project_name', project_name)
                proj_id = getattr(self, 'project_id', project_id)
                meeting_title = getattr(self, 'meeting_title', f"Meeting {datetime.now().strftime('%Y-%m-%d')}")

                response_json = await cw_caller.upload_file(
                        file_path=mp3_path,
                        project_id=proj_id,
                        # display_name=meeting_title
                    )
                if len(response_json.get("uploaded")) > 0:
                    logger.info(f"Recording uploaded to CW: {response_json['uploaded'][0].get('name')}")
                    cleanup_path = Path(mp3_path)
                    if cleanup_path.exists():
                        cleanup_path.unlink()
                        logger.info(f"Deleted local mp3 file: {cleanup_path}")
                    await email_sender.send_meeting_file_uploaded_email(
                                    user_name=user_name,
                                    user_email=user_email,
                                    project_name=proj_name,
                                    project_url=f"https://dev.appmod.ai/mode/Project%20Mode/projects/{proj_id}",
                                    meeting_title=meeting_title,
                                    file_type = "recording"
                                )
                os.remove(webm_path)
                logger.debug(f"Removed temporary {webm_path}")
            else:
                logger.warning(f"FFmpeg conversion failed (exit code {process.returncode})")
                logger.warning(f"FFmpeg stderr: {stderr.decode()[:200]}")
        except FileNotFoundError:
            logger.warning("FFmpeg not found. Install with: sudo apt-get install ffmpeg")
        except Exception as e:
            logger.warning(f"Conversion failed: {e}")
        
        # Clean up chunks from memory
        del self.audio_chunks[meeting_id]
        logger.debug(f"Cleaned up chunks for {meeting_id}")

    async def stop_audio_recording(self):
        """Stop recording and emit recordingEnded event for streaming storage systems"""
        if not self.page:
            return
        
        meeting_id = self.current_meeting_id
        logger.info(f"Stopping recording for meeting: {meeting_id}")
        
        # Stop the MediaRecorder
        await self.page.evaluate("""
            () => {
                if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
                    window.mediaRecorder.stop();
                    console.log("🛑 MediaRecorder stopped");
                }
            }
        """)
        
        # ✅ FIX: Wait for final chunk to arrive
        logger.debug("Waiting for final audio chunks")
        await asyncio.sleep(2)  # Give time for final chunk to process
        
        # Emit recordingEnded event via WebSocket to notify external streaming storage systems
        # This allows streaming storage backends to finalize chunk processing and close file handles
        if self.websocket_manager.is_connected():
            try:
                sio = self.websocket_manager.get_instance()
                queued_chunks = self.audio_queue_manager.get_queue_size()
                event_data = {
                    'meetingId': meeting_id,
                    'timestamp': asyncio.get_event_loop().time(),
                    'eventType': 'recordingEnded',
                    'status': 'stopped',
                    'queuedChunks': queued_chunks
                }
                await sio.emit('recordingEnded', event_data)
                logger.info(
                    f"Emitted recordingEnded event for {meeting_id}; "
                    f"queued chunks: {queued_chunks}"
                )
            except Exception as e:
                logger.warning(f"Failed to emit recordingEnded event: {e}")
        else:
            logger.debug(
                f"WebSocket not connected; recordingEnded event not sent for {meeting_id}"
            )
        
        # Save audio
        if self.current_meeting_id:
            await self.save_audio(self.current_meeting_id)
            self.current_meeting_id = None
        
        # Disconnect WebSocket
        if self.websocket_manager.is_connected():
            try:
                sio = self.websocket_manager.get_instance()
                await sio.disconnect()
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.warning(f"Failed to disconnect WebSocket: {e}")
            

    async def join_as_guest(self, guest_name: str):
        # 1. Dismiss "Sign in with your Google account" popup
        logger.debug("Checking for popup modal")
        await self.page.evaluate("""
            () => {
                const gotItBtn = document.querySelector('button[jsname="EszDEe"]') || 
                                Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Got it'));
                if (gotItBtn) gotItBtn.click();
                const modal = document.querySelector('.KJktIb');
                if (modal) modal.remove();
            }
        """)
        await asyncio.sleep(1)

        # 2. Wait for Name Input to exist in DOM
        logger.debug("Locating guest name input")
        input_found = False
        for _ in range(10):  # Retry up to 10 seconds
            input_found = await self.page.evaluate("""
                () => {
                    const el = document.querySelector('input[jsname="YPqjbf"]') || 
                            document.querySelector('input[aria-label="Your name"]') ||
                            document.querySelector('input[placeholder="Your name"]');
                    return el !== null;
                }
            """)
            if input_found:
                break
            await asyncio.sleep(1)

        if not input_found:
            logger.warning("Could not locate Guest Name input field")
            await self.page.screenshot(path="error_no_input.png")
            return False

        # 3. Focus, Clear, Type Name, and Trigger React State
        logger.debug(f"Typing guest name: {guest_name}")

        # Focus the input element via Playwright
        name_input = self.page.locator(
            'input[jsname="YPqjbf"], input[aria-label="Your name"]'
        ).first
        await name_input.focus()
        await asyncio.sleep(0.3)

        # Clear field
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")

        # Type sequentially character by character to trigger trusted native events
        await self.page.keyboard.type(guest_name, delay=60)
        await asyncio.sleep(0.5)

        # Dispatch final blur/change events via JS to be 100% sure React updates
        await self.page.evaluate("""
            () => {
                const el = document.querySelector('input[jsname="YPqjbf"]') || 
                        document.querySelector('input[aria-label="Your name"]');
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }
            }
        """)
        await asyncio.sleep(1)

        # 4. Click the Join / Ask to join Button
        logger.debug("Attempting to click Join button")
        clicked = await self.page.evaluate("""
            () => {
                const joinBtn = document.querySelector('button[aria-label*="Ask to join"]') ||
                                document.querySelector('button[aria-label*="Join now"]') ||
                                Array.from(document.querySelectorAll('button')).find(b => {
                                    const txt = b.textContent.trim().toLowerCase();
                                    return txt.includes('ask to join') || txt.includes('join now');
                                });

                if (joinBtn) {
                    joinBtn.disabled = false;
                    joinBtn.removeAttribute('disabled');
                    joinBtn.click();
                    return true;
                }
                return false;
            }
        """)

        if not clicked:
            logger.debug("JS click failed, attempting Playwright locator click")
            join_btn = self.page.locator(
                'button:has-text("Ask to join"), button:has-text("Join now")'
            ).first
            await join_btn.click(force=True)

        logger.info("Guest join sequence executed successfully")
        await self.page.screenshot(path="join_attempt.png")
        return True

    async def dismiss_sign_in_popup(self):
        """Dismisses the 'Sign in with your Google account' popup modal in Google Meet."""
        logger.debug("Checking for 'Sign in with your Google account' popup")

        # Selector strategies targeting this exact modal structure
        got_it_button = self.page.locator(
            'button[jsname="EszDEe"], '  # Exact jsname from your HTML
            ".KJktIb button:has-text('Got it'), "  # Scoped button inside popup wrapper
            'button:has-text("Got it")'  # Fallback text locator
        ).first

        try:
            # 1. Wait briefly for the button to appear
            if await got_it_button.is_visible(timeout=3000):
                logger.debug("Found 'Got it' popup, clicking button")
                # Click with force=True in case another transparent element overlays it slightly
                await got_it_button.click(force=True)
                await asyncio.sleep(0.5)
                logger.info("Dismissed 'Got it' popup")
                return True
        except Exception as e:
            logger.warning(f"Standard click on 'Got it' button skipped: {e}")

        # 2. Fallback: If button click fails or modal persists, remove via direct DOM script
        try:
            await self.page.evaluate("""
                () => {
                    // Find container with class .KJktIb or containing 'Sign in with your Google account'
                    const popup = document.querySelector('.KJktIb');
                    if (popup) {
                        // Try finding and clicking 'Got it' button via pure JS
                        const btn = popup.querySelector('button');
                        if (btn) btn.click();
                        
                        // Remove container and any parent dialog/overlay elements
                        const parentModal = popup.closest('[role="dialog"]') || popup.parentElement;
                        if (parentModal) parentModal.remove();
                    }
                }
            """)
            logger.debug("Cleaned up modal elements via JS injection")
        except Exception as e:
            logger.warning(f"JS cleanup error: {e}")

    async def _launch_browser_with_fallback(self):
        """Launch browser with automatic fallback to Chrome on failure"""
        is_macos = platform.system() == "Darwin"
        meeting_id = getattr(self, 'current_meeting_id', 'unknown')
        
        # Try Chromium first
        try:
            logger.info("Attempting to launch Chromium with automation flags")
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--use-fake-device-for-media-stream",
                    "--use-fake-ui-for-media-stream",
                ],
                timeout=10000  # 10 second timeout
            )
            self.browser_type = "chromium"
            logger.info(f"Chromium launched successfully for meeting {meeting_id}")
            return
        except Exception as e:
            context = {
                'browser_type': 'chromium',
                'platform': platform.system(),
                'meeting_id': meeting_id,
            }
            logger.warning(
                f"Chromium launch failed, attempting fallback [browser=chromium, platform={platform.system()}]"
            )
            log_exception(logger, logging.DEBUG, "Chromium launch error details", e, context)
            
            # On macOS, try system Chrome
            if is_macos:
                try:
                    logger.info("Attempting system Chrome as fallback")
                    self.browser = await self.playwright.chromium.launch(
                        channel="chrome",
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--start-maximized",
                            "--use-fake-device-for-media-stream",
                            "--use-fake-ui-for-media-stream",
                            "--disable-gpu",
                        ],
                        timeout=10000
                    )
                    self.browser_type = "chrome"
                    logger.info(f"System Chrome launched successfully for meeting {meeting_id}")
                    return
                except Exception as chrome_error:
                    chrome_context = {
                        'browser_type': 'chrome',
                        'platform': 'macOS',
                        'meeting_id': meeting_id,
                    }
                    logger.error(
                        f"Chrome launch also failed for meeting {meeting_id} "
                        "[browser=chrome, platform=macOS]"
                    )
                    log_exception(logger, logging.DEBUG, "Chrome launch error details", chrome_error, chrome_context)
                    logger.error(
                        "Both Chromium and Chrome failed. Install Chrome from: "
                        "https://www.google.com/chrome/"
                    )
            
            # Last resort: raise the original error with comprehensive context
            context = {
                'chromium_error': str(e),
                'chrome_error': str(chrome_error) if is_macos else 'N/A',
                'platform': platform.system(),
                'meeting_id': meeting_id,
            }
            logger.error(
                f"Failed to launch any browser variant for meeting {meeting_id} "
                "[context: chromium_failed, chrome_failed_or_skipped]"
            )
            log_exception(
                logger,
                logging.ERROR,
                f"Browser launch failed for all variants",
                e,
                context
            )
            raise Exception(
                f"Failed to launch browser for meeting {meeting_id}. "
                f"Tried: Chromium (failed), Chrome (failed/skipped). "
                f"Please ensure a supported browser is installed."
            )

    
# Global instance
# Manager for multiple MeetBot instances keyed by meeting ID
meet_bots: Dict[str, MeetBot] = {}

async def create_bot_for(meeting_id: str, meeting_url: str, *, user_name: Optional[str]=None, user_email: Optional[str]=None, project_id: Optional[str]=None, project_name: Optional[str]=None, meeting_title: Optional[str]=None) -> MeetBot:
    """Create and register a MeetBot for a specific meeting_id. Starts join in background."""
    try:
        if meeting_id in meet_bots:
            logger.debug(f"Bot already exists for meeting {meeting_id}, returning existing instance")
            return meet_bots[meeting_id]

        logger.info(f"Creating new bot for meeting {meeting_id}")
        bot = MeetBot()
        
        # Attach metadata to the bot instance for later use (emails, uploads, etc.)
        bot.user_name = user_name
        bot.user_email = user_email
        bot.project_id = project_id or config.get('PROJECT_ID')
        bot.project_name = project_name or config.get('PROJECT_NAME')
        bot.meeting_title = meeting_title

        meet_bots[meeting_id] = bot
        logger.info(f"Bot registered for meeting {meeting_id}")

        # Start join in background so API can return quickly
        try:
            asyncio.create_task(bot.join_meeting(meeting_url))
            logger.info(f"Join task created for meeting {meeting_id}")
        except Exception as task_error:
            context = {
                'meeting_id': meeting_id,
                'meeting_url': meeting_url,
            }
            logger.error(
                f"Failed to create join task for meeting {meeting_id}"
            )
            log_exception(logger, logging.ERROR, "Task creation failed", task_error, context)
            # Don't re-raise here - let the main join_meeting handle errors
        
        return bot
    except Exception as e:
        context = {
            'meeting_id': meeting_id,
            'user_name': user_name,
            'user_email': user_email,
        }
        logger.error(
            f"Failed to create bot for meeting {meeting_id}"
        )
        log_exception(logger, logging.ERROR, "Bot creation failed", e, context)
        raise


def get_bot(meeting_id: str) -> Optional[MeetBot]:
    return meet_bots.get(meeting_id)


async def remove_bot(meeting_id: str):
    bot = meet_bots.get(meeting_id)
    if not bot:
        return
    try:
        await bot.leave_meeting()
    except Exception as e:
        logger.error(f"Error removing bot for {meeting_id}: {e}")
    finally:
        if meeting_id in meet_bots:
            del meet_bots[meeting_id]