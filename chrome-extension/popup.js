document.addEventListener("DOMContentLoaded", () => {
  // ---------- DOM references ----------
  const startBtn   = document.getElementById("start-btn");
  const stopBtn    = document.getElementById("stop-btn");
  const statusEl   = document.getElementById("status");
  const baseUrlIn  = document.getElementById("baseUrl");
  const meetUrlIn  = document.getElementById("meetingUrl");

  // ---------- Default values ----------
  const DEFAULT_BASE_URL   = "http://dev.appmod.ai";


  // ---------- Load persisted values ----------
  chrome.storage.sync.get(["baseUrl", "meetingUrl"], (data) => {
    baseUrlIn.value  = data.baseUrl  || DEFAULT_BASE_URL;
    meetUrlIn.value  = data.meetingUrl ;
  });

  // Save on any change (optional but handy)
  baseUrlIn.addEventListener("change", () => {
    chrome.storage.sync.set({ baseUrl: baseUrlIn.value.trim() });
  });
  meetUrlIn.addEventListener("change", () => {
    chrome.storage.sync.set({ meetingUrl: meetUrlIn.value.trim() });
  });

  // ---------- Helper ----------
  const getConfig = () => ({
    baseUrl:   baseUrlIn.value.trim() || DEFAULT_BASE_URL,
    meetingUrl: meetUrlIn.value.trim() ,
  });

  // ---------- Start button ----------
  startBtn.addEventListener("click", async () => {
    const { baseUrl, meetingUrl } = getConfig();
    statusEl.textContent = "Starting bot…";

    try {
      const response = await fetch(`${baseUrl}/meeting_recorder_stormee/signin`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // If your backend still expects an API key, put it in storage or a separate field
          // "x-api-key": API_KEY,
        },
        body: JSON.stringify({ meetingUrl }),
      });

      const data = await response.json();
      if (response.ok && data.status === "success") {
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
    const { baseUrl } = getConfig();
    statusEl.textContent = "Stopping bot…";

    try {
      const response = await fetch(`${baseUrl}/meeting_recorder_stormee/exit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // If your backend still expects an API key, put it in storage or a separate field
          // "x-api-key": API_KEY,
        },
      });

      const data = await response.json();
      if (response.ok && data.status === "success") {
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