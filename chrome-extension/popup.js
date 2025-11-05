document.addEventListener("DOMContentLoaded", () => {
  // ---------- DOM references ----------
  const startBtn = document.getElementById("start-btn");
  const stopBtn = document.getElementById("stop-btn");
  const statusEl = document.getElementById("status");
  const meetUrlIn = document.getElementById("meetingUrl");
  const recipientEmailIn = document.getElementById("recipientEmail");
  const addRecipientBtn = document.getElementById("add-recipient-btn");
  const modal = document.getElementById("confirmModal");
  const confirmEmailSpan = document.getElementById("confirmEmail");
  const confirmYesBtn = document.getElementById("confirmYes");
  const confirmNoBtn = document.getElementById("confirmNo");

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

      if (response.status == 201) {
        statusEl.textContent = "Bot stopped successfully!";
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to stop"}`;
      }
    } catch (err) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Stop error:", err);
    }
  });

  // ---------- Add Recipient functionality ----------
  addRecipientBtn.addEventListener("click", () => {
    const email = recipientEmailIn.value.trim();
    if (!email) {
      statusEl.textContent = "Error: Please enter an email address.";
      return;
    }

    if (!email.includes("@")) {
      statusEl.textContent = "Error: Please enter a valid email address.";
      return;
    }

    confirmEmailSpan.textContent = email;
    modal.style.display = "block";
  });

  // Modal confirmation handlers
  confirmYesBtn.addEventListener("click", async () => {
    const email = recipientEmailIn.value.trim();
    
    try {
      const response = await fetch(
        `${BASE_URL}/meeting_recorder_stormee/recipient/add`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        }
      );

      const data = await response.json();

      if (response.status === 201) {
        statusEl.textContent = "Recipient added successfully!";
        recipientEmailIn.value = ""; // Clear the input
      } else {
        statusEl.textContent = `Error: ${data.message || "Failed to add recipient"}`;
      }
    } catch (err) {
      statusEl.textContent = "Error: Could not connect to server.";
      console.error("Add recipient error:", err);
    }

    modal.style.display = "none";
  });

  confirmNoBtn.addEventListener("click", () => {
    modal.style.display = "none";
  });

  // Close modal when clicking outside
  window.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.style.display = "none";
    }
  });
});
