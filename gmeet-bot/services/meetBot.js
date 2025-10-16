import fs from "fs";
import path from "path";
import { chromium } from "playwright";
import { io } from "socket.io-client"; // Import socket.io-client

const AUTH_PATH = path.resolve("auth.json");

let browser, context, page;
let captionsSegments = [];
let scrapingActive = false;
let mediaRecorder = null; // To store the MediaRecorder instance
let audioChunks = []; // To store recorded audio data
let recordingInterval = null; // To manage 1-minute chunking
let socket = null; // To store the WebSocket client instance

async function ensureAuthSession(meetingUrl) {
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

  context = fs.existsSync(AUTH_PATH)
    ? await browser.newContext({
        storageState: AUTH_PATH,
        permissions: ["microphone", "camera"],
      })
    : await browser.newContext({ permissions: ["microphone", "camera"] });

  page = await context.newPage();

  if (!fs.existsSync(AUTH_PATH)) {
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
    console.log("✅ Using existing auth session.");
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

async function playAudio(meetingUrl) {
  if (!browser || !context || !page) {
    await ensureAuthSession(meetingUrl);
  }

  try {
    // Click the microphone button to unmute
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
  if (!page) {
    console.error("❌ No meeting page available.");
    return;
  }

  try {
    // Click the microphone button to mute
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

async function joinMeeting(meetingUrl) {
  console.log("🚀 Joining meeting:", meetingUrl);

  await ensureAuthSession(meetingUrl);

  try {
    // Wait for the join button and click it
    await page.waitForSelector(
      '[data-testid="join-button"], button:has-text("Join now")',
      { timeout: 10000 }
    );
    await page.click(
      '[data-testid="join-button"], button:has-text("Join now")'
    );
    console.log("✅ Successfully joined the meeting.");
  } catch (error) {
    console.error("❌ Error joining meeting:", error);
  }
}

async function startCaptions(meetingUrl) {
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
    // Look for captions button and enable it
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

  console.log("🎙️ Starting audio recording...");

  // Initialize WebSocket connection
  socket = io("http://localhost:5000");
  socket.on("connect", () =>
    console.log("✅ Connected to WebSocket server for audio streaming.")
  );
  socket.on("disconnect", () =>
    console.log("🔌 Disconnected from WebSocket server.")
  );
  socket.on("error", (error) => console.error("❌ WebSocket error:", error));

  // Expose function to send audio chunks from browser to Node.js
  await page.exposeFunction("sendAudioChunkToNode", (chunk) => {
    if (socket && socket.connected) {
      socket.emit("audioChunk", chunk);
    }
  });

  // Start recording in browser context
  await page.evaluate(async (meetingId) => {
    try {
      // Get user media stream
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm; codecs=opus",
      });

      // Store reference globally for stopping
      window.mediaRecorder = mediaRecorder;

      let chunkCounter = 0;
      const startTime = Date.now();

      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0) {
          const chunkId = `${meetingId}-${chunkCounter++}`;
          const timestamp = new Date().toISOString();
          const arrayBuffer = await event.data.arrayBuffer();
          const audioBlob = Array.from(new Uint8Array(arrayBuffer));

          // Send audio chunk to Node.js context
          window.sendAudioChunkToNode({
            meetingId,
            chunkId,
            timestamp,
            audioBlob,
          });
        }
      };

      mediaRecorder.onerror = (event) => {
        console.error("MediaRecorder error:", event.error);
      };

      mediaRecorder.onstop = () => {
        console.log("MediaRecorder stopped");
        stream.getTracks().forEach((track) => track.stop());
      };

      // Start recording with 1-minute intervals
      mediaRecorder.start(60000); // 60 seconds = 60000 milliseconds
      console.log("🎤 MediaRecorder started with 1-minute chunks");
    } catch (error) {
      console.error("❌ Error starting audio recording:", error);
    }
  }, meetingId);

  console.log("✅ Audio recording started successfully.");
}

async function stopAudioRecording() {
  if (!page) {
    console.error("❌ No meeting page available. Cannot stop recording.");
    return;
  }

  console.log("⏹️ Stopping audio recording...");

  // Stop MediaRecorder in browser context
  await page.evaluate(() => {
    if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
      window.mediaRecorder.stop();
      console.log("🛑 MediaRecorder stopped");
    }
  });

  // Disconnect WebSocket
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
