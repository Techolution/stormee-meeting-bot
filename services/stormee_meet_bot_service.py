import asyncio
import os
import platform
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import socketio
from dotenv import load_dotenv
load_dotenv()

PROFILE_DIR = Path("chrome_profile")

class MeetBot:
    def __init__(self):
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
        
        # WebSocket
        self.sio: Optional[socketio.AsyncClient] = None

    async def _launch_browser_with_fallback(self):
        """Launch browser with automatic fallback to Chrome on failure"""
        is_macos = platform.system() == "Darwin"
        
        # Try Chromium first
        try:
            print("🌐 Attempting to launch Chromium...")
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
            print("✅ Chromium launched successfully")
            return
        except Exception as e:
            print(f"⚠️ Chromium failed: {e}")
            
            # On macOS, try system Chrome
            if is_macos:
                try:
                    print("🍎 Trying system Chrome...")
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
                    print("✅ System Chrome launched successfully")
                    return
                except Exception as chrome_error:
                    print(f"❌ Chrome also failed: {chrome_error}")
                    print("💡 Install Chrome from: https://www.google.com/chrome/")
            
            # Last resort: raise the original error
            raise Exception(f"Failed to launch browser: {e}")

    async def ensure_auth_session(self, meeting_url: str):
        """Initialize browser with a persistent Google Chrome profile"""
        print("🔐 Initializing browser with persistent profile...")

        self.playwright = await async_playwright().start()

        # Ensure the profile directory exists
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        # Set headless based on environment (Headless=True inside Docker/Production)
        is_headless = os.getenv("HEADLESS", "false").lower() == "true"

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

        print(f"🚀 Navigating to meeting URL: {meeting_url}")
        await self.page.goto(meeting_url)

    async def is_mic_on(self) -> bool:
        if not self.page:
            return False
        try:
            count = await self.page.locator('[data-is-muted="false"]').first.count()
            return count > 0
        except:
            return False

    async def play_audio(self):
        try:
            mic_button = self.page.locator('[aria-label*="microphone"], [aria-label*="mic"]').first
            if await mic_button.count() > 0:
                await mic_button.click()
                print("🎤 Audio enabled.")
        except Exception as e:
            print(f"❌ Error enabling audio: {e}")

    async def pause_audio(self):
        try:
            mic_button = self.page.locator('[aria-label*="microphone"], [aria-label*="mic"]').first
            if await mic_button.count() > 0:
                await mic_button.click()
                print("🔇 Audio paused.")
        except Exception as e:
            print(f"❌ Error pausing audio: {e}")

    async def pause_camera(self, aria_label="camera"):
        try:
            cam_button = self.page.locator(f'[aria-label*="{aria_label}"]').first
            print(f"🔍 Checking for camera button with aria-label containing '{aria_label}'...")
            if await cam_button.count() > 0:
                await cam_button.click()
                print("📹 Camera paused.")
        except Exception as e:
            print(f"❌ Error pausing camera: {e}")

    async def pause_camera_in_meet(self):
        try:
            # Target aria-label specifically for turning OFF the camera (case-insensitive)
            cam_button = self.page.locator(
                '[aria-label*="Turn off camera" i], [aria-label*="turn off camera" i]'
            ).first

            print("🔍 Checking for camera button...")

            # 1. Wait for element to be visible (Replaces count > 0)
            await cam_button.wait_for(state="visible", timeout=8000)

            # 2. Click with force=True to bypass any overlay or animation backdrop
            await cam_button.click(force=True)
            print("📹 Camera paused using aria-label!")

        except Exception as e:
            print(f"⚠️ Could not pause camera via aria-label: {e}")

    async def join_as_guest(self, guest_name: str):
        # 1. Dismiss "Sign in with your Google account" popup
        print("1️⃣ Checking for popup modal...")
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
        print("2️⃣ Locating guest name input...")
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
            print("❌ Could not locate Guest Name input field.")
            await self.page.screenshot(path="error_no_input.png")
            return False

        # 3. Focus, Clear, Type Name, and Trigger React State
        print(f"3️⃣ Typing guest name: '{guest_name}'...")

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
        print("4️⃣ Attempting to click Join button...")
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
            print("⚠️ JS click failed, attempting Playwright locator click...")
            join_btn = self.page.locator(
                'button:has-text("Ask to join"), button:has-text("Join now")'
            ).first
            await join_btn.click(force=True)

        print("✅ Guest join sequence executed successfully!")
        await self.page.screenshot(path="join_attempt.png")
        return True


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
        print(f"🚀 Joining meeting: {meeting_url}")
        
        await self.ensure_auth_session(meeting_url)
        guest_name = "Stormee.Ai"

        as_guest = os.getenv("JOIN_AS_GUEST", "false").lower() == "true"
        if as_guest:
            print("⏳ Waiting for Meet preview interface to stabilize...")
            await asyncio.sleep(4)
            await self.join_as_guest(guest_name)
            await self.pause_camera_in_meet()

        else:
            join_button = self.page.locator('button:has-text("Join now")')
            switch_here_button = self.page.locator('button:has-text("Switch here")')
            await self.pause_audio()
            await self.pause_camera()
            if await join_button.count() == 0 and await switch_here_button.count() > 0:
                join_button = switch_here_button
            await join_button.wait_for(timeout=10000)
            await join_button.click()
            print("🚀 Clicked 'Join now'")
        
        # --- FIXED LOBBY & ADMISSION WAIT LOGIC ---
        max_admission_wait = 300  # Wait up to 5 minutes for host to admit
        waited = 0
        is_admitted = False

        print("⏳ Polling meeting status (Waiting for host admission)...")
        while waited < max_admission_wait:
            status = await self.check_meeting_status()

            if status == "IN_MEETING":
                print("🎉 Bot has been admitted into the meeting room!")
                is_admitted = True
                break
            elif status == "LOBBY":
                if waited % 10 == 0:
                    print("⌛ Still in lobby waiting for host admission...")

            await asyncio.sleep(2)
            waited += 2

        if not is_admitted:
            print("❌ Timed out or failed to enter meeting room. Aborting post-join actions.")
            return

        # Ensure mic is muted once inside the active meeting
        try:
            if await self.is_mic_on():
                await self.pause_audio()
        except Exception as e:
            print(f"⚠️ Warning checking mic status: {e}")

        # Start post-admission services
        await self.start_chat_scraping()
        print(f"🎥 Joined meeting using {self.browser_type}")
        
        self.participant_count = await self.get_participant_count()
        await self.start_participant_monitoring()
        print(f"Participant count: {self.participant_count}")

    async def dismiss_sign_in_popup(self):
        """Dismisses the 'Sign in with your Google account' popup modal in Google Meet."""
        print("🔍 Checking for 'Sign in with your Google account' popup...")

        # Selector strategies targeting this exact modal structure
        got_it_button = self.page.locator(
            'button[jsname="EszDEe"], '  # Exact jsname from your HTML
            ".KJktIb button:has-text('Got it'), "  # Scoped button inside popup wrapper
            'button:has-text("Got it")'  # Fallback text locator
        ).first

        try:
            # 1. Wait briefly for the button to appear
            if await got_it_button.is_visible(timeout=3000):
                print("💡 Found 'Got it' popup! Clicking button...")
                # Click with force=True in case another transparent element overlays it slightly
                await got_it_button.click(force=True)
                await asyncio.sleep(0.5)
                print("✅ Dismissed 'Got it' popup.")
                return True
        except Exception as e:
            print(f"⚠️ Standard click on 'Got it' button skipped: {e}")

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
            print("🧹 Cleaned up modal elements via JS injection.")
        except Exception as e:
            print(f"⚠️ JS cleanup error: {e}")
            
    async def start_captions(self):
        """Start caption scraping"""
        self.captions_segments = []
        self.scraping_active = True
        await self.turn_captions_on()
        self.caption_task = asyncio.create_task(self.scrape_captions())
        print("🟢 Caption scraping started")

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
                print(f"Error scraping captions: {e}")
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
        print(f"🔴 Caption scraping stopped ({len(final_captions)} blocks saved)")
        return self.captions_segments
        
    async def turn_captions_on(self):
        """Enable captions"""
        try:
            button = self.page.locator('[aria-label*="caption"], button:has-text("Turn on captions")').first
            if await button.count() > 0:
                await button.click()
                print("📝 Captions enabled")
        except Exception as e:
            print(f"Error enabling captions: {e}")

    async def start_audio_recording(self, meeting_id: str):
        """Start recording audio"""
        if not self.page:
            print("❌ No page available")
            return
        
        self.current_meeting_id = meeting_id
        if meeting_id not in self.audio_chunks:
            self.audio_chunks[meeting_id] = []
        
        print(f"🎙️ Starting audio recording for meeting: {meeting_id}")
        
        # WebSocket connection
        if not self.sio or not self.sio.connected:
            self.sio = socketio.AsyncClient(
                logger=False,
                engineio_logger=False,
                reconnection=True,
                reconnection_attempts=5,
                reconnection_delay=1
            )
            
            @self.sio.event
            async def connect():
                print("✅ WebSocket connected")
            
            @self.sio.event
            async def disconnect():
                print("🔌 WebSocket disconnected")
            
            @self.sio.event
            async def connect_error(data):
                print(f"❌ WebSocket connection error: {data}")
            
            try:
                ws_url = "http://localhost:5000"
                print(f"🔌 Connecting to WebSocket at {ws_url}...")
                await self.sio.connect(ws_url)
                await asyncio.sleep(0.5)
                print(f"✅ WebSocket connected successfully")
            except Exception as e:
                print(f"⚠️ WebSocket connection failed: {e}")
                print("⚠️ Audio will be saved locally (no real-time streaming)")
        
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
            print("✅ Exposed sendAudioChunkToPython function")
        else:
            print("ℹ️ sendAudioChunkToPython already exposed, skipping")
        
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
        
        print(f"✅ Recording started for {meeting_id}")

    async def _handle_audio_chunk(self, chunk: dict):
        """Handle audio chunk"""
        meeting_id = chunk.get('meetingId')
        chunk_id = chunk.get('chunkId')
        audio_blob = chunk.get('audioBlob', [])
        
        print(f"📥 Chunk: {chunk_id}, size: {len(audio_blob)} bytes")
        
        # Store chunk locally
        if meeting_id not in self.audio_chunks:
            self.audio_chunks[meeting_id] = []
        
        self.audio_chunks[meeting_id].append(chunk)
        
        # Send via WebSocket if connected
        if self.sio and self.sio.connected:
            try:
                await self.sio.emit('audioChunk', chunk)
                print(f"✅ Sent to WebSocket: {chunk_id}")
            except Exception as e:
                print(f"⚠️ WebSocket send failed: {e}")
                print(f"⚠️ Chunk stored locally only")
        else:
            print(f"⚠️ WebSocket not connected, storing locally only")
    
    async def save_audio(self, meeting_id: str):
        """Save audio to file"""
        if not self.audio_chunks.get(meeting_id):
            print(f"⚠️ No audio chunks received for {meeting_id}")
            return
        
        chunk_count = len(self.audio_chunks[meeting_id])
        print(f"💾 Saving audio for {meeting_id} ({chunk_count} chunks)")
        
        # Sort chunks by their numeric ID
        sorted_chunks = sorted(
            self.audio_chunks[meeting_id],
            key=lambda x: int(x['chunkId'].split('-')[-1])
        )
        
        # Combine all audio chunks
        audio_data = b''.join(bytes(chunk['audioBlob']) for chunk in sorted_chunks)
        
        if len(audio_data) == 0:
            print(f"⚠️ No audio data in chunks for {meeting_id}")
            return
        
        # Save as WebM
        webm_path = f"{meeting_id.replace('/', '_').replace(':', '_')}.webm"
        with open(webm_path, 'wb') as f:
            f.write(audio_data)
        print(f"✅ Saved {webm_path} ({len(audio_data)} bytes)")
        
        # Convert to WAV using ffmpeg
        wav_path = f"{meeting_id.replace('/', '_').replace(':', '_')}.wav"
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', webm_path, 
                '-acodec', 'pcm_s16le',
                '-ar', '48000', 
                '-ac', '2', 
                wav_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                print(f"✅ Converted to {wav_path}")
                os.remove(webm_path)
                print(f"🗑️ Removed temporary {webm_path}")
            else:
                print(f"⚠️ FFmpeg conversion failed (exit code {process.returncode})")
                print(f"stderr: {stderr.decode()[:200]}")
        except FileNotFoundError:
            print(f"⚠️ FFmpeg not found. Install it with: sudo apt-get install ffmpeg")
        except Exception as e:
            print(f"⚠️ Conversion failed: {e}")
        
        # Clean up chunks from memory
        del self.audio_chunks[meeting_id]
        print(f"🧹 Cleaned up chunks for {meeting_id}")

    async def stop_audio_recording(self):
        """Stop recording"""
        if not self.page:
            return
        
        print("⏹️ Stopping recording")
        
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
        print("⏳ Waiting for final audio chunks...")
        await asyncio.sleep(2)  # Give time for final chunk to process
        
        # Save audio
        if self.current_meeting_id:
            await self.save_audio(self.current_meeting_id)
            self.current_meeting_id = None
        
        # Disconnect WebSocket
        if self.sio and self.sio.connected:
            await self.sio.disconnect()
            print("🔌 WebSocket disconnected")
            self.sio = None
            
    async def start_chat_scraping(self):
        """Hard-fix chat scraper using continuous Python-side polling"""
        self.chat_segments = []
        self.chat_scraping_active = True

        # 1. Open the Chat Panel explicitly
        print("💬 Ensuring chat panel is open...")
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
            print("🟢 Hard-fix chat polling loop started!")

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
                            print(
                                f"💬 CHAT [{msg['sender']}]: {msg['text']}"
                            )

                            # Handle Commands
                            text_lower = msg["text"].lower()

                            if "stormee start recording" in text_lower:
                                if not self.current_meeting_id:
                                    mid = f"meeting-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                                    print(
                                        f"🚀 Executing Command: Start Audio Recording -> {mid}"
                                    )
                                    asyncio.create_task(
                                        self.start_audio_recording(mid)
                                    )

                            elif "stormee start caption recording" in text_lower:
                                if not self.scraping_active:
                                    print(
                                        "🚀 Executing Command: Start Captions"
                                    )
                                    asyncio.create_task(self.start_captions())

                            elif "stormee stop recording" in text_lower:
                                if self.current_meeting_id:
                                    print(
                                        f"🛑 Executing Command: Stop Recording -> {self.current_meeting_id}"
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
        print("🔴 Chat monitoring stopped")
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
                print(f"👥 Participants: {count}")
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
                        print(f"🔄 Participants: {last} → {new}")
                        self.participant_count = new
                    last = new
                    
                    # if new == 1:
                    #     print("⚠️ Only bot remains, leaving")
                    #     await self.leave_meeting()
                    #     break
                    
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Monitor error: {e}")
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
        """Leave meeting"""
        if not self.page:
            return
        
        print("🚪 Leaving meeting")
        
        try:
            await self.stop_chat_scraping()
            await self.stop_audio_recording()
            await self.stop_captions()
            await self.stop_participant_monitoring()
            
            leave_button = self.page.locator('[aria-label="Leave call"], button:has-text("Leave call")').first
            if await leave_button.count() > 0:
                await leave_button.click()
            
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            self.page = None
            self.context = None
            self.browser = None
            
            print("✅ Left meeting")
        except Exception as e:
            print(f"Error leaving: {e}")

# Global instance
meet_bot = MeetBot()