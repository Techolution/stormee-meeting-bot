const ENVIRONMENTS = {
  local: 'http://localhost:5000/api/meet',
  development: 'https://dev.appmod.ai/api/meet',
  qa: 'https://qa.appmod.ai/api/meet',
  production: 'https://appmod.ai/api/meet'
};

let API_BASE_URL = ENVIRONMENTS.local;
let DEFAULT_AUDIO_URL = "https://storage.googleapis.com/creative-workspace/projects/6a78bbb3dfeb370713b22c8d/output.wav?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=ellm-studio%40proposal-auto-ai-internal.iam.gserviceaccount.com%2F20260814%2Fauto%2Fstorage%2Fgoog4_request&X-Goog-Date=20260814T093311Z&X-Goog-Expires=360000&X-Goog-SignedHeaders=host&X-Goog-Signature=15378f45d8dd29e59f0ccf42c0f6b32f15648d1eed9c293f701a203b838ecab4a6ec1a822ecfe7d4e282cc8d415aa963e635c159d89d89f1e8ebfde10bff5ade7580a49c236f2ac9df38bd6bb53ca7b27155a430bab583039a9aa66b839a36acf8fa23fadd994df43bbc2a3c218e15c388ba5d49a02af2e7f84f2fa2eb19b62164a5d365303b351cfc9b3be632d802362d71716b3bcac8ee6007224b4136de58c30cda06fa966f02b75d8c405999c27f038dc7058c2572b654684bbe935a2ee42f97e68cfc10f3bceeac497b82f48de7c5c785a820d8911b04794be354629d72064766864db7194699a37d6f29ed1c912f3958a773ae93b0c9bbcc795d58fb8e"

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

// Auto-fill active tab URL if it is a Google Meet URL and no saved URL exists
document.addEventListener('DOMContentLoaded', () => {
  // Load saved user config from local storage
  chrome.storage.local.get(
  ['userName', 'userEmail', 'projectId', 'projectName', 'environment', 'meetingUrl', 'meetingTitle'],
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

    if (stored.meetingUrl) {
      document.getElementById('meetingUrl').value = stored.meetingUrl;
    }

    if (stored.meetingTitle) {
      document.getElementById('meetingTitle').value = stored.meetingTitle;
    }

    if (stored.environment) {
      document.getElementById('environment').value = stored.environment;
      API_BASE_URL = ENVIRONMENTS[stored.environment] || ENVIRONMENTS.local;
    }

    // Only auto-fill meeting URL from active tab if no saved URL exists
    if (!stored.meetingUrl) {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]?.url && tabs[0].url.includes('meet.google.com')) {
          document.getElementById('meetingUrl').value = tabs[0].url;
        }
      });
    }
  }
);
});

// Helper to persist standard settings across browser sessions
function saveUserSettings() {
  const settings = {
    userName: document.getElementById('userName').value,
    userEmail: document.getElementById('userEmail').value,
    projectId: document.getElementById('projectId').value,
    projectName: document.getElementById('projectName').value,
    meetingUrl: document.getElementById('meetingUrl').value,
    meetingTitle: document.getElementById('meetingTitle').value,
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

// Add change listeners to meeting-related fields to save on every change
document.getElementById('meetingUrl').addEventListener('change', () => {
  saveUserSettings();
});

document.getElementById('meetingTitle').addEventListener('change', () => {
  saveUserSettings();
});

document.getElementById('userName').addEventListener('change', () => {
  saveUserSettings();
});

document.getElementById('userEmail').addEventListener('change', () => {
  saveUserSettings();
});

document.getElementById('projectId').addEventListener('change', () => {
  saveUserSettings();
});

document.getElementById('projectName').addEventListener('change', () => {
  saveUserSettings();
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

document.getElementById('play-audio-btn').addEventListener('click', async () => {
  const meetingUrl = document.getElementById('meetingUrl').value.trim();
  let audioUrl = document.getElementById('audioUrl').value.trim();
  const volumeValue = document.getElementById('volume').value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    return;
  }

  if (!audioUrl) {
    showStatus('Audio URL is empty to playing default audio.', true);
    // return;
  }
  audioUrl = DEFAULT_AUDIO_URL

  const meetingId = extractMeetingId(meetingUrl);
  const volume = parseFloat(volumeValue) || 0.7;

  // Validate volume is within acceptable range
  if (volume < 0 || volume > 1) {
    showStatus('Volume must be between 0 and 1.', true);
    return;
  }

  const payload = {
    meetingId,
    audioUrl,
    volume
  };

  showStatus('Playing audio...');

  try {
    const response = await fetch(`${API_BASE_URL}/audio/play`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      showStatus('Audio playing successfully!');
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