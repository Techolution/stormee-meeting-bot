document.addEventListener("DOMContentLoaded", () => {
  // Get references to DOM elements
  const startBtn = document.getElementById("start-btn");
  const stopBtn = document.getElementById("stop-btn");
  const statusEl = document.getElementById("status");

  // Configuration constants
  const BASE_URL = "http://localhost:5000";
  const API_KEY = "YOUR_SECRET_API_KEY"; // This should be securely managed
  const MEETING_URL = "https://meet.google.com/abc-defg-hij"; // Hardcoded meeting URL

  // Start button click event listener
  startBtn.addEventListener("click", async () => {
    statusEl.textContent = "Starting bot...";
    try {
      const response = await fetch(`${BASE_URL}/api/start-meeting`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": API_KEY,
        },
        body: JSON.stringify({ meetingUrl: MEETING_URL }),
      });

      const data = await response.json();
      if (response.ok && data.status === "success") {
        statusEl.textContent = "Bot started successfully!";
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to start"}`;
      }
    } catch (error) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Start error:", error);
    }
  });

  // Stop button click event listener
  stopBtn.addEventListener("click", async () => {
    statusEl.textContent = "Stopping bot...";
    try {
      const response = await fetch(`${BASE_URL}/api/stop-meeting`, {
        method: "POST",
        headers: {
          "x-api-key": API_KEY,
        },
      });

      const data = await response.json();
      if (response.ok && data.status === "success") {
        statusEl.textContent = "Bot stopped successfully!";
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to stop"}`;
      }
    } catch (error) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Stop error:", error);
    }
  });
});
