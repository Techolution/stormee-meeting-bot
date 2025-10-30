document.addEventListener("DOMContentLoaded", () => {
  // ---------- DOM references ----------
  const startBtn = document.getElementById("start-btn");
  const stopBtn = document.getElementById("stop-btn");
  const statusEl = document.getElementById("status");
  const meetUrlIn = document.getElementById("meetingUrl");

  // ---------- FIXED BASE URL ----------
  const BASE_URL = "https://dev.appmod.ai"; // Fixed, no input, no storage

  // ---------- Load only meetingUrl from storage ----------
  chrome.storage.sync.get(["meetingUrl"], (data) => {
    meetUrlIn.value = data.meetingUrl || "";
  });

  // Save meeting URL when changed
  meetUrlIn.addEventListener("change", () => {
    chrome.storage.sync.set({ meetingUrl: meetUrlIn.value.trim() });
  });

  // ---------- Helper ----------
  const getMeetingUrl = () => meetUrlIn.value.trim();

  // ---------- Start button ----------
  startBtn.addEventListener("click", async () => {
    const meetingUrl = getMeetingUrl();

    if (!meetingUrl) {
      statusEl.textContent = "Error: Please enter a meeting URL.";
      return;
    }

    statusEl.textContent = "Starting bot…";

    try {
      const response = await fetch(
        `${BASE_URL}/meeting_recorder_stormee/signin`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ meetingUrl }),
        }
      );

      const data = await response.json();

      if (response.status == 200) {
        statusEl.textContent = "Bot started successfully!";
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to start"}`;
      }
    } catch (err) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Start error:", err);
    }
  });

  // ---------- Stop button ----------
  stopBtn.addEventListener("click", async () => {
    statusEl.textContent = "Stopping bot…";

    try {
      const response = await fetch(
        `${BASE_URL}/meeting_recorder_stormee/exit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        }
      );

      const data = await response.json();

      if (response.status == 200) {
        statusEl.textContent = "Bot stopped successfully!";
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to stop"}`;
      }
    } catch (err) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Stop error:", err);
    }
  });
});
