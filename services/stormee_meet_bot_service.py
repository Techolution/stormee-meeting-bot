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

AUTH_PATH = Path("auth.json")

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

    async def ensure_auth_session(self, meeting_url: str, as_guest: bool = True):
        """Initialize browser"""
        print("🔐 Ensuring authentication session...")
        
        self.playwright = await async_playwright().start()
        
        # Launch with fallback
        await self._launch_browser_with_fallback()
        
        storage_state = None
        if not as_guest and AUTH_PATH.exists():
            storage_state = str(AUTH_PATH)
        
        self.context = await self.browser.new_context(
            permissions=["microphone", "camera"],
            storage_state=storage_state
        )
        
        self.page = await self.context.new_page()
        
        # Audio stream capture
        await self.page.add_init_script("""
            window.remoteAudioStreams = [];
            const OriginalRTCPeerConnection = window.RTCPeerConnection;
            window.RTCPeerConnection = function (...args) {
                const pc = new OriginalRTCPeerConnection(...args);
                pc.addEventListener('track', (event) => {
                    console.log('Global ontrack event:', event);
                    if (event.track.kind === 'audio') {
                        const remoteStream = event.streams[0];
                        const audio = document.createElement('audio');
                        audio.srcObject = remoteStream;
                        audio.autoplay = true;
                        audio.muted = true;
                        document.body.appendChild(audio);
                        audio.play().catch(e => console.error('Audio play failed:', e));
                        window.remoteAudioStreams.push(remoteStream);
                        console.log('Added remote audio stream to global list.');
                    }
                });
                return pc;
            };
        """)
        
        if not as_guest and not AUTH_PATH.exists():
            login_url = (
                "https://accounts.google.com/ServiceLogin"
                "?service=wise&passive=true&continue=https%3A%2F%2Fmeet.google.com%2F"
            )
            await self.page.goto(login_url)
            print("🧑‍💻 Please log in manually.")
            await self.page.wait_for_url("https://meet.google.com/**", timeout=0)
            await self.context.storage_state(path=str(AUTH_PATH))
            print("✅ Login successful. Saved session.")
        else:
            await self.page.goto(meeting_url)
            print("✅ Joining as guest." if as_guest else "✅ Using existing auth session.")

    # ... rest of the methods remain exactly the same as the simple version ...
    # (Copy all other methods from the simple version above)

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

    async def join_meeting(self, meeting_url: str, as_guest: bool = True):
        print(f"🚀 Joining meeting: {meeting_url}")
        
        await self.ensure_auth_session(meeting_url, as_guest)
        await self.page.wait_for_load_state('networkidle')
        
        guest_name = "Stormee.Ai"
        
        if as_guest:
            try:
                await self.pause_audio()
                cam_button = self.page.locator('[aria-label*="camera"]').first
                if await cam_button.count() > 0:
                    await cam_button.click()
                    print("📹 Camera paused.")
            except Exception as e:
                print(f"⚠️ Error pausing media: {e}")
            
            name_input = self.page.locator('input[aria-label="Your name"], input[placeholder="Your name"]')
            try:
                await name_input.wait_for(timeout=10000)
                if await name_input.count() > 0:
                    await name_input.fill(guest_name)
                    print(f"📝 Entered name: {guest_name}")
            except:
                print("⚠️ Name input not found")
            
            ask_button = self.page.locator('[jsname="UywwFc-RLmnJb"], button:has(span:has-text("Ask to join"))')
            await ask_button.wait_for(timeout=10000)
            await ask_button.click()
            print("🚀 Clicked 'Ask to join'")
        else:
            join_button = self.page.locator('button:has-text("Join now")')
            await join_button.wait_for(timeout=10000)
            await join_button.click()
            print("🚀 Clicked 'Join now'")
        
        await self.page.wait_for_selector('button[aria-label*="microphone"]', timeout=60000)
        
        if await self.is_mic_on():
            await self.pause_audio()
        
        await self.start_chat_scraping()
        print(f"🎥 Joined meeting using {self.browser_type}")
        
        self.participant_count = await self.get_participant_count()
        await self.start_participant_monitoring()
        print(f"Participant count: {self.participant_count}")
        
    async def start_captions(self):
        """Start caption scraping"""
        self.captions_segments = []
        self.scraping_active = True
        await self.turn_captions_on()
        self.caption_task = asyncio.create_task(self.scrape_captions())
        print("🟢 Caption scraping started")

    async def stop_captions(self) -> List[Dict]:
        """Stop caption scraping"""
        self.scraping_active = False
        if self.caption_task:
            self.caption_task.cancel()
            try:
                await self.caption_task
            except asyncio.CancelledError:
                pass
        print("🔴 Caption scraping stopped")
        return self.captions_segments

    async def scrape_captions(self):
        """Scrape captions continuously"""
        selector = '[data-testid="caption-text"], .captions-text, .closed-captions-text'
        while self.scraping_active:
            try:
                elements = await self.page.locator(selector).all()
                for element in elements:
                    text = await element.text_content()
                    if text and text.strip():
                        self.captions_segments.append({
                            "text": text.strip(),
                            "timestamp": datetime.now().isoformat()
                        })
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error scraping captions: {e}")
                await asyncio.sleep(5)

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
                ws_url = os.getenv("WS_URL","http://localhost:5000")
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
        """Start monitoring chat"""
        self.chat_segments = []
        self.chat_scraping_active = True
        
        for attempt in range(1, 9):
            try:
                chat_button = self.page.locator('[aria-label="Show chat"], button:has-text("Chat")').first
                
                if await chat_button.count() > 0:
                    await chat_button.click()
                    print("💬 Chat opened")
                    
                    await self.page.locator('.Ge9Kpc, [aria-live="polite"]').first.wait_for(state='visible', timeout=10000)
                    break
                else:
                    if attempt < 8:
                        print(f"⚠️ Chat button not found, retry {attempt}/8")
                        await asyncio.sleep(5)
                    else:
                        print("❌ Chat button not found")
                        return
            except Exception as e:
                print(f"Error opening chat: {e}")
                if attempt == 8:
                    return
                await asyncio.sleep(5)
        
        # Handle chat messages
        async def handle_message(msg: Dict):
            self.chat_segments.append(msg)
            print(f"💬 {msg['sender']}: {msg['text']}")
            
            text = msg['text'].lower()
            
            if "stormee start recording" in text:
                # FIX: Check if already recording
                if self.current_meeting_id:
                    print(f"ℹ️ Recording already in progress: {self.current_meeting_id}")
                    return
                
                # FIX: Use better meeting ID format
                mid = f"meeting-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                print(f"🚀 Starting recording: {mid}")
                await self.start_audio_recording(mid)
                
            elif "stormee start caption recording" in text:
                if self.scraping_active:
                    print("ℹ️ Caption recording already in progress")
                else:
                    print("🚀 Starting caption recording")
                    await self.start_captions()
                    
            elif "stormee stop recording" in text:
                if not self.current_meeting_id:
                    print("ℹ️ No recording in progress")
                else:
                    print(f"🛑 Stopping recording: {self.current_meeting_id}")
                    await self.stop_audio_recording()
        
        await self.page.expose_function(
            'sendChatMessageToPython',
            lambda msg: asyncio.create_task(handle_message(msg))
        )
        
        # Observer
        await self.page.evaluate("""
            () => {
                const container = document.querySelector('.Ge9Kpc, [aria-live="polite"]');
                if (!container) return;
                
                const processed = new Set();
                
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        mutation.addedNodes.forEach((node) => {
                            if (node.nodeType === Node.ELEMENT_NODE && node.matches('div.RLrADb')) {
                                const id = node.getAttribute('data-message-id') || 'unknown';
                                if (processed.has(id)) return;
                                processed.add(id);
                                
                                const sender = node.querySelector('.poVWob')?.textContent?.trim() || 'Unknown';
                                const text = node.querySelector('div[jsname="dTKtvb"] > div')?.textContent?.trim() || '';
                                const timestamp = node.querySelector('.MuzmKe')?.textContent?.trim() || new Date().toISOString();
                                
                                if (text) {
                                    window.sendChatMessageToPython({sender, text, timestamp, messageId: id});
                                }
                            }
                        });
                    });
                });
                
                observer.observe(container, {childList: true, subtree: true});
                
                // Existing messages
                container.querySelectorAll('div.RLrADb').forEach((node) => {
                    const id = node.getAttribute('data-message-id') || 'unknown';
                    if (processed.has(id)) return;
                    processed.add(id);
                    
                    const sender = node.querySelector('.poVWob')?.textContent?.trim() || 'Unknown';
                    const text = node.querySelector('div[jsname="dTKtvb"] > div')?.textContent?.trim() || '';
                    const timestamp = node.querySelector('.MuzmKe')?.textContent?.trim() || new Date().toISOString();
                    
                    if (text) {
                        window.sendChatMessageToPython({sender, text, timestamp, messageId: id});
                    }
                });
            }
        """)
        
        print("🟢 Chat monitoring started")

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
                    
                    if new == 1:
                        print("⚠️ Only bot remains, leaving")
                        await self.leave_meeting()
                        break
                    
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