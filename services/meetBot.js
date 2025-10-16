import fs from "fs";
import path from "path";
import { chromium } from "playwright";
import { io } from "socket.io-client"; // Import socket.io-client
import { promisify } from "util";
import { exec } from "child_process";

const execAsync = promisify(exec);

const AUTH_PATH = path.resolve("auth.json");

let browser, context, page;
let captionsSegments = [];
let scrapingActive = false;
let mediaRecorder = null; // To store the MediaRecorder instance
let audioChunks = {}; // To store recorded audio data per meetingId: {meetingId: [{chunkId, audioBlob, timestamp}, ...]}
let recordingInterval = null; // To manage 1-minute chunking
let socket = null; // To store the WebSocket client instance
let currentMeetingId = null; // To track the current recording meetingId

async function ensureAuthSession(meetingUrl, asGuest = true) {
  console.log("🔐 Ensuring authentication session...");

  browser = await chromium.launch({
    headless: false,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--start-maximized",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  });

  // Hook into browser close to save audio if recording
  const originalClose = browser.close;
  browser.close = async () => {
    if (currentMeetingId) {
      console.log("🛡️ Browser closing detected. Saving audio...");
      await saveAudio(currentMeetingId);
    }
    return originalClose.call(browser);
  };

  context = await browser.newContext({
    permissions: ["microphone", "camera"],
    storageState: asGuest ? undefined : (fs.existsSync(AUTH_PATH) ? AUTH_PATH : undefined),
  });

  page = await context.newPage();

  // Inject script to override RTCPeerConnection for capturing remote streams early
  await page.addInitScript(() => {
    window.remoteAudioStreams = [];
    const OriginalRTCPeerConnection = window.RTCPeerConnection;
    window.RTCPeerConnection = function (...args) {
      const pc = new OriginalRTCPeerConnection(...args);
      pc.addEventListener('track', (event) => {
        console.log('Global ontrack event:', event);
        if (event.track.kind === 'audio') {
          const remoteStream = event.streams[0];
          // Create audio element to activate the stream
          const audio = document.createElement('audio');
          audio.srcObject = remoteStream;
          audio.autoplay = true;
          audio.muted = true; // Prevent actual playback
          document.body.appendChild(audio);
          audio.play().catch(e => console.error('Audio play failed:', e));
          window.remoteAudioStreams.push(remoteStream);
          console.log('Added remote audio stream to global list.');
        }
      });
      return pc;
    };
  });

  if (!asGuest && !fs.existsSync(AUTH_PATH)) {
    const LOGIN_URL =
      "https://accounts.google.com/ServiceLogin" +
      "?service=wise&passive=true&continue=https%3A%2F%2Fmeet.google.com%2F";

    await page.goto(LOGIN_URL);
    console.log("🧑‍💻 Please log in manually.");
    await page.waitForURL(/https:\/\/meet\.google\.com\/.*/, { timeout: 0 });
    await context.storageState({ path: AUTH_PATH });
    console.log("✅ Login successful. Saved session.");
  } else {
    await page.goto(meetingUrl);
    console.log(asGuest ? "✅ Joining as guest." : "✅ Using existing auth session.");
  }

  return { browser, context, page };
}

async function isMicOn() {
  if (!page) {
    console.error("❌ No meeting page available.");
    return false;
  }

  try {
    const micButton = await page.locator('[data-is-muted="false"]').first();
    const isMuted = (await micButton.count()) === 0;
    return !isMuted;
  } catch (error) {
    console.error("❌ Error checking microphone status:", error);
    return false;
  }
}

async function playAudio() {
  try {
    const micButton = await page
      .locator('[aria-label*="microphone"], [aria-label*="mic"]')
      .first();
    if ((await micButton.count()) > 0) {
      await micButton.click();
      console.log("🎤 Audio enabled.");
    }
  } catch (error) {
    console.error("❌ Error enabling audio:", error);
  }
}

async function pauseAudio() {
  try {
    const micButton = await page
      .locator('[aria-label*="microphone"], [aria-label*="mic"]')
      .first();
    if ((await micButton.count()) > 0) {
      await micButton.click();
      console.log("🔇 Audio paused.");
    }
  } catch (error) {
    console.error("❌ Error pausing audio:", error);
  }
}

async function joinMeeting(meetingUrl, asGuest = true) {
  console.log("🚀 Joining meeting:", meetingUrl);

  await ensureAuthSession(meetingUrl, asGuest);

  // Wait for the page to load
  await page.waitForLoadState('networkidle');

  const guestName = "Stormee.Ai";

  // If guest mode, handle name input and ask to join
  if (asGuest) {
    // Turn off mic and cam if preview shows
    try {
      await pauseAudio();
      // Similarly for camera if needed
      const camButton = await page.locator('[aria-label*="camera"]').first();
      if (await camButton.count() > 0) {
        await camButton.click();
        console.log("📹 Camera paused.");
      }
    } catch (error) {
      console.error("⚠️ Error pausing media in preview:", error);
    }

    const nameInput = page.locator('input[aria-label="Your name"], input[placeholder="Your name"]');
    await nameInput.waitFor({ timeout: 10000 }).catch(() => console.log("⚠️ Name input not found; may be logged in."));

    if (await nameInput.count() > 0) {
      await nameInput.fill(guestName);
      console.log(`📝 Entered guest name: ${guestName}`);
    }

    // Use more reliable selector for Ask to join
    const askToJoinButton = page.locator('[jsname="UywwFc-RLmnJb"], button:has(span:has-text("Ask to join"))');
    await askToJoinButton.waitFor({ timeout: 10000 });
    await askToJoinButton.click();
    console.log("🚀 Clicked 'Ask to join'");
  } else {
    // For logged in, click Join now
    const joinNowButton = page.locator('button:has-text("Join now")');
    await joinNowButton.waitFor({ timeout: 10000 });
    await joinNowButton.click();
    console.log("🚀 Clicked 'Join now'");
  }

  // Wait for meeting interface
  await page.waitForSelector('button[aria-label*="microphone"]', { timeout: 60000 });

  // Ensure mic is off by default
  if (await isMicOn()) {
    await pauseAudio();
  } else {
    console.log("✅ Mic already off.");
  }

  console.log("🎥 Joined meeting with mic OFF by default.");
}

async function startCaptions() {
  captionsSegments = [];
  scrapingActive = true;
  await turnCaptionsOn(page);
  await scrapeCaptions(page);
  console.log("🟢 Caption scraping started.");
}

async function stopCaptions() {
  scrapingActive = false;
  if (browser) await browser.close();
  console.log("🔴 Caption scraping stopped.");
  return captionsSegments;
}

async function scrapeCaptions(page) {
  const captionSelector =
    '[data-testid="caption-text"], .captions-text, .closed-captions-text';

  while (scrapingActive) {
    try {
      const captionElements = await page.locator(captionSelector).all();

      for (const element of captionElements) {
        const text = await element.textContent();
        if (text && text.trim()) {
          captionsSegments.push({
            text: text.trim(),
            timestamp: new Date().toISOString(),
          });
        }
      }

      await page.waitForTimeout(1000); // Check every second
    } catch (error) {
      console.error("❌ Error scraping captions:", error);
      await page.waitForTimeout(5000); // Wait longer on error
    }
  }
}

async function turnCaptionsOn(page) {
  try {
    const captionsButton = await page
      .locator('[aria-label*="caption"], button:has-text("Turn on captions")')
      .first();
    if ((await captionsButton.count()) > 0) {
      await captionsButton.click();
      console.log("📝 Captions enabled.");
    }
  } catch (error) {
    console.error("❌ Error enabling captions:", error);
  }
}

async function startAudioRecording(meetingId) {
  if (!page) {
    console.error("❌ No meeting page available. Join a meeting first.");
    return;
  }

  currentMeetingId = meetingId;
  audioChunks[meetingId] = [];

  console.log("🎙️ Starting full meeting audio recording...");

  // Initialize WebSocket connection
  socket = io("http://localhost:3000");
  socket.on("connect", () =>
    console.log("✅ Connected to WebSocket server for audio streaming.")
  );
  socket.on("disconnect", () =>
    console.log("🔌 Disconnected from WebSocket server.")
  );
  socket.on("error", (error) => console.error("❌ WebSocket error:", error));

  // Expose function to send audio chunks from browser to Node.js
  await page.exposeFunction("sendAudioChunkToNode", (chunk) => {
    console.log(`📥 Received audio chunk from browser: ${chunk.chunkId}, size: ${chunk.audioBlob.length} bytes, timestamp: ${chunk.timestamp}`);
    if (socket && socket.connected) {
      socket.emit("audioChunk", chunk, (response) => {
        if (response && response.success) {
          console.log(`✅ Server acknowledged chunk: ${chunk.chunkId}`);
        } else {
          console.error(`❌ Server failed to acknowledge chunk: ${chunk.chunkId}`);
        }
      });
    } else {
      console.warn(`⚠️ Socket not connected; chunk ${chunk.chunkId} not sent to server.`);
    }
    audioChunks[chunk.meetingId].push(chunk);
  });

  // Start recording in browser
  await page.evaluate(async (meetingId) => {
    try {
      const audioCtx = new AudioContext();
      const destination = audioCtx.createMediaStreamDestination();

      // // Add local stream (optional, can omit if no local audio needed)
      // const localStream = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(e => {
      //   console.warn('Local mic access denied or error:', e);
      //   return new MediaStream(); // Empty stream if failed
      // });
      // const localSource = audioCtx.createMediaStreamSource(localStream);
      // localSource.connect(destination);

      // Add all captured remote streams
      if (window.remoteAudioStreams && window.remoteAudioStreams.length > 0) {
        window.remoteAudioStreams.forEach(stream => {
          const remoteSource = audioCtx.createMediaStreamSource(stream);
          remoteSource.connect(destination);
          console.log('Connected remote stream to mixer.');
        });
      } else {
        console.warn('⚠️ No remote audio streams captured yet.');
      }

      // Listen for future streams (in case more participants join)
      window.addEventListener('remoteStreamAdded', (event) => {
        const stream = event.detail;
        const remoteSource = audioCtx.createMediaStreamSource(stream);
        remoteSource.connect(destination);
        console.log('Connected new remote stream to mixer.');
      });

      const mixedStream = destination.stream;
      const mediaRecorder = new MediaRecorder(mixedStream, {
        mimeType: "audio/webm; codecs=opus",
      });

      window.mediaRecorder = mediaRecorder;

      let chunkCounter = 0;

      mediaRecorder.ondataavailable = async (event) => {
        console.log(`📤 Browser: Audio data available for chunk ${meetingId}-${chunkCounter}, size: ${event.data.size} bytes`);
        if (event.data.size > 0) {
          const chunkId = `${meetingId}-${chunkCounter++}`;
          const timestamp = new Date().toISOString();
          const arrayBuffer = await event.data.arrayBuffer();
          const audioBlob = Array.from(new Uint8Array(arrayBuffer));
          window.sendAudioChunkToNode({
            meetingId,
            chunkId,
            timestamp,
            audioBlob,
          });
        }
      };

      mediaRecorder.onerror = (event) => console.error("MediaRecorder error:", event.error);
      mediaRecorder.onstop = () => {
        console.log("MediaRecorder stopped");
        // localStream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start(600);
      console.log("🎤 MediaRecorder started with 1-minute chunks for full meeting audio");
    } catch (error) {
      console.error("❌ Error starting audio recording:", error);
    }
  }, meetingId);

  console.log("✅ Full audio recording started successfully.");
}

async function saveAudio(meetingId) {
  if (!audioChunks[meetingId] || audioChunks[meetingId].length === 0) {
    console.log(`⚠️ No audio chunks to save for meeting ${meetingId}.`);
    return;
  }

  console.log(`💾 Saving audio for meeting ${meetingId}...`);

  const sortedChunks = audioChunks[meetingId].sort((a, b) => {
    const aNum = parseInt(a.chunkId.split('-')[1]);
    const bNum = parseInt(b.chunkId.split('-')[1]);
    return aNum - bNum;
  });

  const buffers = sortedChunks.map(chunk => Buffer.from(chunk.audioBlob));
  const concatenated = Buffer.concat(buffers);

  const webmPath = `${meetingId}.webm`;
  fs.writeFileSync(webmPath, concatenated);
  console.log(`✅ Saved concatenated WebM file: ${webmPath}, size: ${concatenated.length} bytes`);

  const wavPath = `${meetingId}.wav`;
  try {
    await execAsync(`ffmpeg -i ${webmPath} -acodec pcm_s16le -ar 48000 -ac 2 ${wavPath}`);
    console.log(`✅ Converted to WAV: ${wavPath}`);
    fs.unlinkSync(webmPath);
  } catch (error) {
    console.error(`❌ Error converting WebM to WAV: ${error.message}`);
    console.log(`ℹ️ You can manually convert ${webmPath} to WAV using ffmpeg.`);
  }

  delete audioChunks[meetingId];
}

async function stopAudioRecording() {
  if (!page) {
    console.error("❌ No meeting page available. Cannot stop recording.");
    return;
  }

  console.log("⏹️ Stopping audio recording...");

  await page.evaluate(() => {
    if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
      window.mediaRecorder.stop();
      console.log("🛑 MediaRecorder stopped");
    }
  });

  if (currentMeetingId) {
    await saveAudio(currentMeetingId);
    currentMeetingId = null;
  }

  if (socket) {
    socket.disconnect();
    socket = null;
    console.log("🔌 WebSocket disconnected.");
  }

  console.log("✅ Audio recording stopped successfully.");
}

export {
  startCaptions,
  stopCaptions,
  playAudio,
  joinMeeting,
  pauseAudio,
  startAudioRecording,
  stopAudioRecording,
  isMicOn,
};