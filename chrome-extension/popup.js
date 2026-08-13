const ENVIRONMENTS = {
  local: 'http://localhost:5000/api/meet',
  development: 'https://dev.appmod.ai/api/meet',
  qa: 'https://qa.appmod.ai/api/meet',
  production: 'https://appmod.ai/api/meet'
};

let API_BASE_URL = ENVIRONMENTS.local;

// Helper to set UI status messages
function showStatus(text, isError = false) {
  const statusEl = document.getElementById('status');
  statusEl.textContent = text;
  statusEl.className = isError ? 'status-error' : 'status-success';
}

// Utility: Extract meetingId from URL (e.g., https://meet.google.com/abc-defg-hij -> abc-defg-hij)
function extractMeetingId(url) {
  try {
    const parsedUrl = new URL(url.trim());
    const pathname = parsedUrl.pathname.replace(/^\//, ''); // remove leading slash
    return pathname || `meeting-${Date.now()}`;
  } catch (e) {
    // If user provided raw string without protocol
    const cleanUrl = url.trim().replace(/^https?:\/\//, '');
    const parts = cleanUrl.split('/');
    return parts[parts.length - 1] || `meeting-${Date.now()}`;
  }
}

// Auto-fill active tab URL if it is a Google Meet URL
document.addEventListener('DOMContentLoaded', () => {
  // Load saved user config from local storage
  chrome.storage.local.get(
  ['userName', 'userEmail', 'projectId', 'projectName', 'environment'],
  (stored) => {
    if (stored.userName) {
      document.getElementById('userName').value = stored.userName;
    }

    if (stored.userEmail) {
      document.getElementById('userEmail').value = stored.userEmail;
    }

    if (stored.projectId) {
      document.getElementById('projectId').value = stored.projectId;
    }

    if (stored.projectName) {
      document.getElementById('projectName').value = stored.projectName;
    }

    if (stored.environment) {
      document.getElementById('environment').value = stored.environment;
      API_BASE_URL = ENVIRONMENTS[stored.environment] || ENVIRONMENTS.local;
    }
  }
);

  // Query active tab URL
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.url && tabs[0].url.includes('meet.google.com')) {
      document.getElementById('meetingUrl').value = tabs[0].url;
    }
  });
});

// Helper to persist standard settings across browser sessions
function saveUserSettings() {
  const settings = {
    userName: document.getElementById('userName').value,
    userEmail: document.getElementById('userEmail').value,
    projectId: document.getElementById('projectId').value,
    projectName: document.getElementById('projectName').value,
    environment: document.getElementById('environment').value
  };
  chrome.storage.local.set(settings);
}

document.getElementById('environment').addEventListener('change', (event) => {
  const environment = event.target.value;

  API_BASE_URL = ENVIRONMENTS[environment] || ENVIRONMENTS.local;

  chrome.storage.local.set({
    environment
  });

  showStatus(`Environment changed to ${environment}`);
});

// Handler: Start Bot
document.getElementById('start-btn').addEventListener('click', async () => {
  const meetingUrl = document.getElementById('meetingUrl').value.trim();
  const meetingTitle = document.getElementById('meetingTitle').value.trim();
  const userName = document.getElementById('userName').value.trim();
  const userEmail = document.getElementById('userEmail').value.trim();
  const projectId = document.getElementById('projectId').value.trim();
  const projectName = document.getElementById('projectName').value.trim();

  if (!meetingUrl) {
    showStatus('Please provide a valid Meeting URL.', true);
    return;
  }

  saveUserSettings();
  const meetingId = extractMeetingId(meetingUrl);

  const payload = {
    meetingUrl,
    meetingId,
    userName: userName || "Swikrit Shukla",
    userEmail: userEmail || "swikrit.shukla@techolution.com",
    projectId: projectId || "6a78bbb3dfeb370713b22c8d",
    projectName: projectName || "MeetBot Test",
    meetingTitle: meetingTitle || "Test Meet"
  };

  showStatus('Sending join request...');

  try {
    const response = await fetch(`${API_BASE_URL}/signin`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      showStatus('Bot requested to join successfully!');
    } else {
      const errData = await response.json().catch(() => ({}));
      showStatus(`Error: ${errData.message || response.statusText}`, true);
    }
  } catch (error) {
    showStatus(`Network Error: ${error.message}`, true);
  }
});

// Handler: Stop Bot
document.getElementById('stop-btn').addEventListener('click', async () => {
  const meetingUrl = document.getElementById('meetingUrl').value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    return;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const payload = { meetingId };

  showStatus('Sending exit request...');

  try {
    const response = await fetch(`${API_BASE_URL}/exit`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      showStatus('Bot exit command sent!');
    } else {
      const errData = await response.json().catch(() => ({}));
      showStatus(`Error: ${errData.message || response.statusText}`, true);
    }
  } catch (error) {
    showStatus(`Network Error: ${error.message}`, true);
  }
});

document.getElementById('start-rec-btn').addEventListener('click', async () => {
  const meetingUrl = document.getElementById('meetingUrl').value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    return;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const payload = { meetingId };

  showStatus('Starting recording...');

  try {
    const response = await fetch(`${API_BASE_URL}/record/start`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      showStatus('Bot started recording!');
    } else {
      const errData = await response.json().catch(() => ({}));
      showStatus(`Error: ${errData.message || response.statusText}`, true);
    }
  } catch (error) {
    showStatus(`Network Error: ${error.message}`, true);
  }
});

document.getElementById('stop-rec-btn').addEventListener('click', async () => {
  const meetingUrl = document.getElementById('meetingUrl').value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    return;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const payload = { meetingId };

  showStatus('Stopping recording...');

  try {
    const response = await fetch(`${API_BASE_URL}/record/stop`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      showStatus('Bot stopped recording');
    } else {
      const errData = await response.json().catch(() => ({}));
      showStatus(`Error: ${errData.message || response.statusText}`, true);
    }
  } catch (error) {
    showStatus(`Network Error: ${error.message}`, true);
  }
});

function updateApiUrlDisplay() {
  document.getElementById('api-url').textContent =
    `API: ${API_BASE_URL}`;
}