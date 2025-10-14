import fs from "fs";
import path from "path";
import { chromium } from "playwright";

const AUTH_PATH = path.resolve("auth.json");

let browser, context, page;
let captionsSegments = [];
let scrapingActive = false;

async function ensureAuthSession(meetingUrl) {
  browser = await chromium.launch({
    headless: false,
    args: ["--disable-blink-features=AutomationControlled", "--start-maximized",
        '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream', 
    '--use-file-for-fake-audio-capture=/Users/deepanshgupta/Desktop/bot-poc/file_example_WAV_1MG.wav'
    ],
  });

  context = fs.existsSync(AUTH_PATH)
    ? await browser.newContext({ storageState: AUTH_PATH , permissions:['microphone','camera'] })
    : await browser.newContext();

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
//     async function playAudio(filePath) {
//     if (!fs.existsSync(filePath)) {
//       console.error(`❌ Audio file not found at ${filePath}`);
//       return;
//     }
  
//     if (!page) {
//       console.error("❌ No meeting page available. Call startCaptions() or joinMeeting() first.");
//       return;
//     }
  
//     console.log(`🎵 Playing audio: ${filePath}`);
  
//     // Inject Web Audio API to play audio into the meeting
//     await page.evaluate(
//       async (fileUrl) => {
//         const response = await fetch(fileUrl);
//         const arrayBuffer = await response.arrayBuffer();
//         const context = new AudioContext();
//         const buffer = await context.decodeAudioData(arrayBuffer);
//         const source = context.createBufferSource();
//         source.buffer = buffer;
//         source.connect(context.destination);
//         source.start();
//       },
//       `file://${path.resolve(filePath)}`
//     );
//   }
async function isMicOn() {
    if (!page) return false;
  
    const micButton = page.locator('button[aria-label*="microphone"]');
    if ((await micButton.count()) === 0) return false;
  
    const label = await micButton.getAttribute('aria-label');
    // If the label says "Turn off microphone", it means mic is currently ON
    return label?.toLowerCase().includes("turn off microphone");
  }
  
  async function playAudio() {
    if (!page) return;
  
    const micOn = await isMicOn();
    if (micOn) {
      console.log("🎤 Mic is already on, skipping playAudio.");
      return;
    }
  
    console.log("🎤 Enabling mic...");
    await page.keyboard.down('Meta'); // Cmd on Mac
    await page.keyboard.press('KeyD');
    await page.keyboard.up('Meta');
  }
  
  async function pauseAudio() {
    if (!page) return;
  
    const micOn = await isMicOn();
    if (!micOn) {
      console.log("🔇 Mic is already off, skipping pauseAudio.");
      return;
    }
  
    console.log("🔇 Disabling mic...");
    await page.keyboard.down('Meta'); // Cmd on Mac
    await page.keyboard.press('KeyD');
    await page.keyboard.up('Meta');
  }
  
async function joinMeeting(meetingUrl) {
    await ensureAuthSession(meetingUrl);
    const guestName = "Guest User";
  // Wait for the name input if it exists (guest flow)
  const nameInput = page.locator('input[aria-label="Your name"]');
  if ((await nameInput.count()) > 0) {
    await nameInput.fill(guestName);
    console.log(`📝 Entered guest name: ${guestName}`);

    const askToJoinButton = page.locator('button:has-text("Ask to join")');
    await askToJoinButton.click();
    console.log("🚀 Clicked 'Ask to join'");
  } else {
    // Already logged in user
    const joinNowButton = page.locator('button:has-text("Join now")');
    const askToJoinButton = page.locator('button:has-text("Ask to join")');
    await Promise.race([
      joinNowButton.waitFor({ timeout: 30000 }),
      askToJoinButton.waitFor({ timeout: 30000 }),
    ]);

    if ((await joinNowButton.count()) > 0) {
      await joinNowButton.click();
    } else if ((await askToJoinButton.count()) > 0) {
      await askToJoinButton.click();
    }
  }

 

}

async function startCaptions(meetingUrl) {
  captionsSegments = [];
  scrapingActive = true;
  await turnCaptionsOn(page);
  await scrapeCaptions(page);
//   await joinMeeting(meetingUrl);
  
  console.log("🟢 Caption scraping started.");
}

async function stopCaptions() {
  scrapingActive = false;
  if (browser) await browser.close();
  console.log("🔴 Caption scraping stopped.");
  return captionsSegments;
}

async function scrapeCaptions(page) {
    console.log("🕵️ Starting to scrape captions...");
  
    let index = 0;
    let captionsLastSeenAt = Date.now();
    const segments = [];
  
    await page.exposeFunction("onCaption", (speaker, text) => {
      const trimmedCaption = text.trim();
      if (trimmedCaption) {
        const segment = {
          speaker,
          text: trimmedCaption,
          start: index,
          end: index + 1,
        };
        console.log(`🗣️ ${JSON.stringify(segment, null, 2)}`);
        segments.push(segment);
        index++;
        captionsLastSeenAt = Date.now();
      }
    });
  
    await page.evaluate(() => {
      console.log("Setting up caption MutationObserver...");
  
      const captionRegion = document.querySelector(
        '[role="region"][aria-label*="Captions"]'
      );
  
      if (!captionRegion) {
        console.warn("⚠️ Caption region not found.");
        return;
      }
  
      let lastKnownSpeaker = "Unknown Speaker";
      const seenCaptions = new Set();
  
      const handleNode = (node) => {
        const speakerElem = node.querySelector(".NWpY1d");
        let speaker = speakerElem?.textContent?.trim() || lastKnownSpeaker;
        if (speaker !== "Unknown Speaker") {
          lastKnownSpeaker = speaker;
        }
        const clone = node.cloneNode(true);
        const speakerLabel = clone.querySelector(".NWpY1d");
        if (speakerLabel) speakerLabel.remove();
        const caption = clone.textContent?.trim() || "";
        if (
          caption &&
          caption.toLowerCase() !== speaker.toLowerCase() &&
          !seenCaptions.has(caption)
        ) {
          seenCaptions.add(caption);
          // @ts-expect-error: injected function
          window.onCaption?.(speaker, caption);
        }
      };
  
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          const nodes = Array.from(mutation.addedNodes);
          if (nodes.length > 0) {
            nodes.forEach((node) => {
              if (node instanceof HTMLElement) handleNode(node);
            });
          } else if (
            mutation.type === "characterData" &&
            mutation.target.parentElement instanceof HTMLElement
          ) {
            handleNode(mutation.target.parentElement);
          }
        }
      });
  
      observer.observe(captionRegion, {
        childList: true,
        subtree: true,
        characterData: true,
        characterDataOldValue: true,
      });
    });
  
    await page.waitForSelector('[role="region"][aria-label*="Captions"]', {
      timeout: 30000,
      state: "visible",
    });
  
    const MAX_IDLE_TIME = 30000;
    const MAX_TOTAL_TIME = 6000000;
    const startTime = Date.now();
  
    return new Promise((resolve) => {
      const interval = setInterval(() => {
        const now = Date.now();
        const idleTime = now - captionsLastSeenAt;
        const totalTime = now - startTime;
  
        if (idleTime > MAX_IDLE_TIME || totalTime > MAX_TOTAL_TIME) {
          clearInterval(interval);
          console.log("⌛ Caption scraping finished.");
          console.log(`🧾 Total segments captured: ${segments.length}`);
          resolve(segments);
        }
      }, 3000);
    });
  }
async function turnCaptionsOn(page) {
    // Enable captions if not already on
    // Ensure the meeting is fully loaded
    console.log("⏳ Waiting for Google Meet interface to load...");
    await page.waitForSelector(
      'button[aria-label*="Turn on captions"], button[aria-label*="Show captions"], [aria-label*="More options"]',
      {
        timeout: 60000,
      }
    );
    console.log("✅ Meeting UI loaded.");
  
    // Try enabling captions
    try {
      const captionsButton = await page.$(
        'button[aria-label*="Turn on captions"], button[aria-label*="Show captions"]'
      );
  
      if (captionsButton) {
        console.log("🎯 Found captions button, clicking...");
        await captionsButton.click();
      } else {
        console.log(
          "⚠️ Captions button not found, trying keyboard shortcut (Shift+C)"
        );
        await page.focus("body");
        await page.keyboard.down("Shift");
        await page.keyboard.press("KeyC");
        await page.keyboard.up("Shift");
        console.log("⌨️ Sent Shift+C to toggle captions.");
      }
  
      // Wait dynamically for captions region to appear
      console.log("⏳ Waiting for captions to load in DOM...");
      await page.waitForFunction(
        () => {
          const captionsRegions = Array.from(
            document.querySelectorAll('[role="region"]')
          );
          return captionsRegions.some((r) =>
            r.getAttribute("aria-label")?.toLowerCase().includes("captions")
          );
        },
        { timeout: 45000 }
      );
  
      console.log("✅ Captions region found and active.");
    } catch (e) {
      console.warn("⚠️ Could not enable captions automatically:", e.message);
    }
  }

export { startCaptions, stopCaptions,playAudio,joinMeeting ,pauseAudio};
