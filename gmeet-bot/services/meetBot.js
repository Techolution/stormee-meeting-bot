const { chromium } = require("playwright");

class MeetBot {
  constructor() {
    this.browser = null;
    this.context = null;
    this.page = null;
    this.audioStreamTrack = null;
    this.meetingUrl = null;
    this.isInitialized = false;
  }

  async launchBrowser() {
    try {
      this.browser = await chromium.launch({
        headless: false,
        args: [
          "--use-fake-ui-for-media-stream",
          "--use-fake-device-for-media-stream",
          "--disable-web-security",
          "--disable-features=VizDisplayCompositor",
          "--allow-running-insecure-content",
          "--autoplay-policy=no-user-gesture-required",
        ],
      });

      this.context = await this.browser.newContext({
        permissions: ["microphone", "camera"],
      });

      this.page = await this.context.newPage();
      this.isInitialized = true;

      console.log("Browser launched successfully");
      return true;
    } catch (error) {
      console.error("Error launching browser:", error);
      throw error;
    }
  }

  async loadAuthCookies() {
    try {
      const fs = require("fs");
      const path = require("path");
      const authPath = path.join(__dirname, "..", "auth.json");

      if (fs.existsSync(authPath)) {
        const cookies = JSON.parse(fs.readFileSync(authPath, "utf8"));
        await this.context.addCookies(cookies);
        console.log("Authentication cookies loaded");
        return true;
      } else {
        console.log("No auth.json file found");
        return false;
      }
    } catch (error) {
      console.error("Error loading auth cookies:", error);
      return false;
    }
  }

  async joinMeeting(meetingUrl) {
    if (!this.page) {
      throw new Error("Browser not initialized. Call launchBrowser() first.");
    }

    try {
      this.meetingUrl = meetingUrl;
      await this.page.goto(meetingUrl);

      // Wait for the page to load
      await this.page.waitForTimeout(3000);

      // Click join button if present
      const joinButton = await this.page.$('button[jsname="Qx7uuf"]');
      if (joinButton) {
        await joinButton.click();
        await this.page.waitForTimeout(2000);
      }

      console.log("Joined meeting successfully");
      return true;
    } catch (error) {
      console.error("Error joining meeting:", error);
      throw error;
    }
  }

  async speak(text) {
    if (!this.page) {
      throw new Error("Page not initialized.");
    }

    try {
      this.audioStreamTrack = await this.page.evaluate(async (txt) => {
        return new Promise((resolve, reject) => {
          try {
            // Create speech synthesis utterance
            const utterance = new SpeechSynthesisUtterance(txt);
            utterance.lang = "en-US";
            utterance.rate = 1.0;
            utterance.pitch = 1.0;
            utterance.volume = 1.0;

            // Create audio context and destination
            const audioContext = new (window.AudioContext ||
              window.webkitAudioContext)();
            const destination = audioContext.createMediaStreamDestination();

            // Create oscillator as a workaround for speech synthesis audio capture
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(destination);

            // Configure oscillator for speech-like frequency
            oscillator.frequency.setValueAtTime(440, audioContext.currentTime);
            oscillator.type = "sine";
            gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);

            oscillator.start();

            // Get the audio stream
            const stream = destination.stream;
            const [track] = stream.getAudioTracks();

            // Find and replace the audio track in RTCPeerConnection
            const rtcConnections = Object.values(window).filter(
              (obj) =>
                obj &&
                obj.constructor &&
                obj.constructor.name === "RTCPeerConnection"
            );

            if (rtcConnections.length > 0) {
              const pc = rtcConnections[0];
              const sender = pc
                .getSenders()
                .find((s) => s.track && s.track.kind === "audio");

              if (sender) {
                sender
                  .replaceTrack(track)
                  .then(() => {
                    console.log("Audio track replaced successfully");
                    resolve(track);
                  })
                  .catch(reject);
              } else {
                resolve(track);
              }
            } else {
              resolve(track);
            }

            // Speak the text
            window.speechSynthesis.speak(utterance);

            utterance.onend = () => {
              oscillator.stop();
            };

            utterance.onerror = (event) => {
              console.error("Speech synthesis error:", event);
              oscillator.stop();
              reject(event);
            };
          } catch (error) {
            console.error("Error in speech synthesis:", error);
            reject(error);
          }
        });
      }, text);

      console.log("Speech synthesis completed");
      return true;
    } catch (error) {
      console.error("Error in speak method:", error);
      throw error;
    }
  }

  async isMicOn() {
    try {
      // Check dynamic audio track first
      if (this.audioStreamTrack) {
        return this.audioStreamTrack.enabled;
      }

      // Fallback to UI check
      if (!this.page) {
        return false;
      }

      const micButton = await this.page.$(
        'button[data-tooltip*="microphone" i], button[aria-label*="microphone" i]'
      );
      if (micButton) {
        const isPressed = await micButton.getAttribute("aria-pressed");
        return isPressed === "true";
      }

      return false;
    } catch (error) {
      console.error("Error checking microphone status:", error);
      return false;
    }
  }

  async playAudio() {
    try {
      // Control dynamic audio track
      if (this.audioStreamTrack) {
        this.audioStreamTrack.enabled = true;
        console.log("Dynamic audio track enabled");
        return true;
      }

      // Fallback to UI control
      if (!this.page) {
        throw new Error("Page not initialized");
      }

      const micButton = await this.page.$(
        'button[data-tooltip*="microphone" i], button[aria-label*="microphone" i]'
      );
      if (micButton) {
        const isPressed = await micButton.getAttribute("aria-pressed");
        if (isPressed === "false") {
          await micButton.click();
          console.log("Microphone turned on via UI");
        }
        return true;
      }

      return false;
    } catch (error) {
      console.error("Error enabling audio:", error);
      throw error;
    }
  }

  async pauseAudio() {
    try {
      // Control dynamic audio track
      if (this.audioStreamTrack) {
        this.audioStreamTrack.enabled = false;
        console.log("Dynamic audio track disabled");
        return true;
      }

      // Fallback to UI control
      if (!this.page) {
        throw new Error("Page not initialized");
      }

      const micButton = await this.page.$(
        'button[data-tooltip*="microphone" i], button[aria-label*="microphone" i]'
      );
      if (micButton) {
        const isPressed = await micButton.getAttribute("aria-pressed");
        if (isPressed === "true") {
          await micButton.click();
          console.log("Microphone turned off via UI");
        }
        return true;
      }

      return false;
    } catch (error) {
      console.error("Error disabling audio:", error);
      throw error;
    }
  }

  async startCaptions() {
    try {
      if (!this.page) {
        throw new Error("Page not initialized");
      }

      const captionsButton = await this.page.$(
        'button[data-tooltip*="captions" i], button[aria-label*="captions" i]'
      );
      if (captionsButton) {
        await captionsButton.click();
        console.log("Captions started");
        return true;
      }

      return false;
    } catch (error) {
      console.error("Error starting captions:", error);
      throw error;
    }
  }

  async stopCaptions() {
    try {
      if (!this.page) {
        throw new Error("Page not initialized");
      }

      const captionsButton = await this.page.$(
        'button[data-tooltip*="captions" i], button[aria-label*="captions" i]'
      );
      if (captionsButton) {
        const isPressed = await captionsButton.getAttribute("aria-pressed");
        if (isPressed === "true") {
          await captionsButton.click();
          console.log("Captions stopped");
        }
        return true;
      }

      return false;
    } catch (error) {
      console.error("Error stopping captions:", error);
      throw error;
    }
  }

  async leaveMeeting() {
    try {
      if (!this.page) {
        throw new Error("Page not initialized");
      }

      const leaveButton = await this.page.$(
        'button[data-tooltip*="leave" i], button[aria-label*="leave" i]'
      );
      if (leaveButton) {
        await leaveButton.click();
        console.log("Left meeting");
        return true;
      }

      return false;
    } catch (error) {
      console.error("Error leaving meeting:", error);
      throw error;
    }
  }

  async closeBrowser() {
    try {
      if (this.browser) {
        await this.browser.close();
        this.browser = null;
        this.context = null;
        this.page = null;
        this.audioStreamTrack = null;
        this.isInitialized = false;
        console.log("Browser closed");
      }
      return true;
    } catch (error) {
      console.error("Error closing browser:", error);
      throw error;
    }
  }

  async getStatus() {
    return {
      isInitialized: this.isInitialized,
      meetingUrl: this.meetingUrl,
      hasAudioTrack: !!this.audioStreamTrack,
      micEnabled: await this.isMicOn(),
    };
  }
}

module.exports = new MeetBot();
