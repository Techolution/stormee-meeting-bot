const ENVIRONMENTS = {
  local: 'http://localhost:5000/api/meet',
  development: 'https://dev.appmod.ai/api/meet',
  qa: 'https://qa.appmod.ai/api/meet',
  production: 'https://appmod.ai/api/meet'
};

let API_BASE_URL = ENVIRONMENTS.local;
const REQUEST_TIMEOUT = 30000; // 30 seconds timeout for fetch requests
const STORAGE_DEBOUNCE_DELAY = 500; // Debounce storage writes by 500ms
const ACTION_THROTTLE_MS = 1500; // Prevent duplicate clicks while a request is in flight

// DOM Element Cache to reduce repeated getElementById() calls
const DOM_CACHE = {};

const BUTTON_LOCKS = new Map();

function setButtonLocked(button, isLocked, label = null) {
  if (!button) return;

  button.disabled = isLocked;
  if (label && !isLocked) {
    button.textContent = label;
  }
}

function lockButton(button, originalLabel) {
  if (!button || BUTTON_LOCKS.has(button)) return false;

  BUTTON_LOCKS.set(button, true);
  button.disabled = true;
  return true;
}

function unlockButton(button, originalLabel) {
  if (!button) return;

  BUTTON_LOCKS.delete(button);
  button.disabled = false;
  if (originalLabel) {
    button.textContent = originalLabel;
  }
}

function withActionThrottle(button, action, originalLabel) {
  if (!button) return;
  if (!lockButton(button, originalLabel)) {
    return;
  }

  setTimeout(() => {
    unlockButton(button, originalLabel);
  }, ACTION_THROTTLE_MS);

  return action();
}

function cacheDOM() {
  DOM_CACHE.environment = document.getElementById('environment');
  DOM_CACHE.meetingUrl = document.getElementById('meetingUrl');
  DOM_CACHE.meetingId = document.getElementById('meetingId');
  DOM_CACHE.meetingTitle = document.getElementById('meetingTitle');
  DOM_CACHE.userName = document.getElementById('userName');
  DOM_CACHE.userEmail = document.getElementById('userEmail');
  DOM_CACHE.projectId = document.getElementById('projectId');
  DOM_CACHE.projectName = document.getElementById('projectName');
  DOM_CACHE.maxDurationSeconds = document.getElementById('maxDurationSeconds');
  DOM_CACHE.generateIncrementalHighlights = document.getElementById('generateIncrementalHighlights');
  DOM_CACHE.status = document.getElementById('status');
  DOM_CACHE.audioUrl = document.getElementById('audioUrl');
  DOM_CACHE.volume = document.getElementById('volume');
  DOM_CACHE.apiUrl = document.getElementById('api-url');
}

// Debouncing mechanism for storage operations
let storageDebounceTimer = null;
function debounceStorageOperation(callback, delay = STORAGE_DEBOUNCE_DELAY) {
  clearTimeout(storageDebounceTimer);
  storageDebounceTimer = setTimeout(callback, delay);
}

// Fetch with timeout
async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    // Create a new options object with signal to avoid mutating the original
    const fetchOptions = Object.assign({}, options, { signal: controller.signal });
    const response = await fetch(url, fetchOptions);
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error('Request timeout - server took too long to respond');
    }
    throw error;
  }
}
let DEFAULT_AUDIO_URL = "https://storage.googleapis.com/creative-workspace/projects/6a78bbb3dfeb370713b22c8d/output.wav?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=ellm-studio%40proposal-auto-ai-internal.iam.gserviceaccount.com%2F20260814%2Fauto%2Fstorage%2Fgoog4_request&X-Goog-Date=20260814T093311Z&X-Goog-Expires=360000&X-Goog-SignedHeaders=host&X-Goog-Signature=15378f45d8dd29e59f0ccf42c0f6b32f15648d1eed9c293f701a203b838ecab4a6ec1a822ecfe7d4e282cc8d415aa963e635c159d89d89f1e8ebfde10bff5ade7580a49c236f2ac9df38bd6bb53ca7b27155a430bab583039a9aa66b839a36acf8fa23fadd994df43bbc2a3c218e15c388ba5d49a02af2e7f84f2fa2eb19b62164a5d365303b351cfc9b3be632d802362d71716b3bcac8ee6007224b4136de58c30cda06fa966f02b75d8c405999c27f038dc7058c2572b654684bbe935a2ee42f97e68cfc10f3bceeac497b82f48de7c5c785a820d8911b04794be354629d72064766864db7194699a37d6f29ed1c912f3958a773ae93b0c9bbcc795d58fb8e"

// Helper to set UI status messages (uses cached DOM element for performance)
function showStatus(text, isError = false) {
  const statusWrapper = document.getElementById('status-wrapper');

  if (DOM_CACHE.status) {
    DOM_CACHE.status.textContent = text;
    DOM_CACHE.status.className = isError ? 'status-error' : 'status-success';
  }

  if (statusWrapper) {
    const hasMessage = Boolean(text && text.trim());
    statusWrapper.classList.toggle('visible', hasMessage);
  }

  if (!text || !text.trim()) {
    return;
  }

  clearTimeout(window.__statusClearTimer);
  window.__statusClearTimer = setTimeout(() => {
    if (DOM_CACHE.status) {
      DOM_CACHE.status.textContent = '';
      DOM_CACHE.status.className = 'status-success';
    }
    if (statusWrapper) {
      statusWrapper.classList.remove('visible');
    }
  }, 2500);
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

function syncMeetingIdFromUrl() {
  const meetingUrl = DOM_CACHE.meetingUrl?.value.trim();
  if (!meetingUrl) return;

  const extractedMeetingId = extractMeetingId(meetingUrl);
  if (DOM_CACHE.meetingId && !DOM_CACHE.meetingId.value.trim()) {
    DOM_CACHE.meetingId.value = extractedMeetingId;
  }
}

// Auto-fill active tab URL if it is a Google Meet URL and no saved URL exists
document.addEventListener('DOMContentLoaded', () => {
  // Cache DOM elements for better performance
  cacheDOM();

  // Display current API URL
  updateApiUrlDisplay();

  // Load saved user config from local storage
  chrome.storage.local.get(
    ['userName', 'userEmail', 'projectId', 'projectName', 'environment', 'meetingUrl', 'meetingTitle', 'meetingId', 'maxDurationSeconds', 'generateIncrementalHighlights'],
    (stored) => {
      // Batch DOM updates to reduce layout thrashing
      if (stored.userName) DOM_CACHE.userName.value = stored.userName;
      if (stored.userEmail) DOM_CACHE.userEmail.value = stored.userEmail;
      if (stored.projectId) DOM_CACHE.projectId.value = stored.projectId;
      if (stored.projectName) DOM_CACHE.projectName.value = stored.projectName;
      if (stored.meetingUrl) DOM_CACHE.meetingUrl.value = stored.meetingUrl;
      if (stored.meetingId) DOM_CACHE.meetingId.value = stored.meetingId;
      if (stored.meetingTitle) DOM_CACHE.meetingTitle.value = stored.meetingTitle;
      if (stored.maxDurationSeconds !== undefined) DOM_CACHE.maxDurationSeconds.value = stored.maxDurationSeconds;
      if (typeof stored.generateIncrementalHighlights === 'boolean') {
        DOM_CACHE.generateIncrementalHighlights.checked = stored.generateIncrementalHighlights;
      }

      if (stored.environment) {
        DOM_CACHE.environment.value = stored.environment;
        API_BASE_URL = ENVIRONMENTS[stored.environment] || ENVIRONMENTS.local;
        updateApiUrlDisplay();
      }

      if (!DOM_CACHE.meetingId.value.trim() && DOM_CACHE.meetingUrl.value.trim()) {
        syncMeetingIdFromUrl();
      }

      // Only auto-fill meeting URL from active tab if no saved URL exists
      if (!stored.meetingUrl) {
        // Use timeout to prevent chrome.tabs.query from blocking UI if tab access is slow
        const tabQueryTimeout = setTimeout(() => {
          console.warn('chrome.tabs.query took too long, skipping auto-fill');
        }, 3000);

        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          clearTimeout(tabQueryTimeout);
          if (tabs[0]?.url && tabs[0].url.includes('meet.google.com')) {
            DOM_CACHE.meetingUrl.value = tabs[0].url;
          }
        });
      }
    }
  );
});

// Helper to persist standard settings across browser sessions
function saveUserSettings(immediate = false) {
  const persistSettings = () => {
    const settings = {
      userName: DOM_CACHE.userName ? DOM_CACHE.userName.value : '',
      userEmail: DOM_CACHE.userEmail ? DOM_CACHE.userEmail.value : '',
      projectId: DOM_CACHE.projectId ? DOM_CACHE.projectId.value : '',
      projectName: DOM_CACHE.projectName ? DOM_CACHE.projectName.value : '',
      meetingUrl: DOM_CACHE.meetingUrl ? DOM_CACHE.meetingUrl.value : '',
      meetingId: DOM_CACHE.meetingId ? DOM_CACHE.meetingId.value : '',
      meetingTitle: DOM_CACHE.meetingTitle ? DOM_CACHE.meetingTitle.value : '',
      maxDurationSeconds: DOM_CACHE.maxDurationSeconds ? DOM_CACHE.maxDurationSeconds.value : '',
      generateIncrementalHighlights: DOM_CACHE.generateIncrementalHighlights ? DOM_CACHE.generateIncrementalHighlights.checked : false,
      environment: DOM_CACHE.environment ? DOM_CACHE.environment.value : 'local'
    };
    chrome.storage.local.set(settings);
  };

  if (immediate) {
    persistSettings();
    return;
  }

  debounceStorageOperation(persistSettings);
}

DOM_CACHE.environment?.addEventListener('change', (event) => {
  const environment = event.target.value;

  API_BASE_URL = ENVIRONMENTS[environment] || ENVIRONMENTS.local;
  updateApiUrlDisplay();

  debounceStorageOperation(() => {
    chrome.storage.local.set({ environment });
  });

  showStatus(`Environment changed to ${environment}`);
});

DOM_CACHE.meetingUrl?.addEventListener('input', () => {
  syncMeetingIdFromUrl();
  saveUserSettings(true);
});

DOM_CACHE.meetingUrl?.addEventListener('change', () => {
  syncMeetingIdFromUrl();
  saveUserSettings(true);
});

// Save immediately for all user fields so values persist even if the popup is closed quickly
['meetingId', 'meetingTitle', 'userName', 'userEmail', 'projectId', 'projectName', 'maxDurationSeconds'].forEach((fieldId) => {
  const element = DOM_CACHE[fieldId];
  if (element) {
    element.addEventListener('input', () => saveUserSettings(true));
    element.addEventListener('change', () => saveUserSettings(true));
  }
});

if (DOM_CACHE.generateIncrementalHighlights) {
  DOM_CACHE.generateIncrementalHighlights.addEventListener('input', () => saveUserSettings(true));
  DOM_CACHE.generateIncrementalHighlights.addEventListener('change', () => saveUserSettings(true));
}

window.addEventListener('beforeunload', () => {
  saveUserSettings(true);
});

// Handler: Start Bot
document.getElementById('start-btn').addEventListener('click', async () => {
  const button = document.getElementById('start-btn');
  const originalLabel = button.textContent;

  if (!withActionThrottle(button, () => Promise.resolve(), originalLabel)) {
    return;
  }

  const meetingUrl = DOM_CACHE.meetingUrl.value.trim();
  const meetingTitle = DOM_CACHE.meetingTitle.value.trim();
  const userName = DOM_CACHE.userName.value.trim();
  const userEmail = DOM_CACHE.userEmail.value.trim();
  const projectId = DOM_CACHE.projectId.value.trim();
  const projectName = DOM_CACHE.projectName.value.trim();

  if (!meetingUrl) {
    showStatus('Please provide a valid Meeting URL.', true);
    unlockButton(button, originalLabel);
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
    const response = await fetchWithTimeout(`${API_BASE_URL}/meetings/join`, {
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
  } finally {
    unlockButton(button, originalLabel);
  }
});

// Handler: Stop Bot
document.getElementById('stop-btn').addEventListener('click', async () => {
  const button = document.getElementById('stop-btn');
  const originalLabel = button.textContent;

  if (!withActionThrottle(button, () => Promise.resolve(), originalLabel)) {
    return;
  }

  const meetingUrl = DOM_CACHE.meetingUrl.value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    unlockButton(button, originalLabel);
    return;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const payload = { meetingId };

  showStatus('Sending exit request...');

  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/meetings/leave`, {
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
  } finally {
    unlockButton(button, originalLabel);
  }
});

document.getElementById('start-rec-btn').addEventListener('click', async () => {
  const button = document.getElementById('start-rec-btn');
  const originalLabel = button.textContent;

  if (!withActionThrottle(button, () => Promise.resolve(), originalLabel)) {
    return;
  }

  const meetingUrl = DOM_CACHE.meetingUrl.value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    unlockButton(button, originalLabel);
    return;
  }

  const rawMeetingId = (DOM_CACHE.meetingId?.value || '').trim();
  const meetingId = rawMeetingId || extractMeetingId(meetingUrl);

  const payload = { meetingId };

  const maxDurationSecondsInput = (DOM_CACHE.maxDurationSeconds?.value || '').trim();
  if (maxDurationSecondsInput !== '') {
    const maxDurationSecondsValue = Number.parseInt(maxDurationSecondsInput, 10);
    if (Number.isFinite(maxDurationSecondsValue) && maxDurationSecondsValue > 0) {
      payload.maxDurationSeconds = maxDurationSecondsValue;
    }
  }

  if (DOM_CACHE.generateIncrementalHighlights && DOM_CACHE.generateIncrementalHighlights.checked) {
    payload.generateIncrementalHighlights = true;
  }

  showStatus('Starting recording...');

  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/recordings/start`, {
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
  } finally {
    unlockButton(button, originalLabel);
  }
});

document.getElementById('stop-rec-btn').addEventListener('click', async () => {
  const button = document.getElementById('stop-rec-btn');
  const originalLabel = button.textContent;

  if (!withActionThrottle(button, () => Promise.resolve(), originalLabel)) {
    return;
  }

  const meetingUrl = DOM_CACHE.meetingUrl.value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    unlockButton(button, originalLabel);
    return;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const payload = { meetingId };

  showStatus('Stopping recording...');

  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/recordings/stop`, {
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
  } finally {
    unlockButton(button, originalLabel);
  }
});

document.getElementById('play-audio-btn').addEventListener('click', async () => {
  const button = document.getElementById('play-audio-btn');
  const originalLabel = button.textContent;

  if (!withActionThrottle(button, () => Promise.resolve(), originalLabel)) {
    return;
  }

  const meetingUrl = DOM_CACHE.meetingUrl.value.trim();
  let audioUrl = DOM_CACHE.audioUrl.value.trim();
  const volumeValue = DOM_CACHE.volume.value.trim();

  if (!meetingUrl) {
    showStatus('Meeting URL is required to identify the meeting ID.', true);
    unlockButton(button, originalLabel);
    return;
  }

  if (!audioUrl) {
    showStatus('Audio URL is empty, playing default audio.', true);
    audioUrl = DEFAULT_AUDIO_URL;
  }

  const meetingId = extractMeetingId(meetingUrl);
  const volume = parseFloat(volumeValue) || 0.7;

  // Validate volume is within acceptable range
  if (volume < 0 || volume > 1) {
    showStatus('Volume must be between 0 and 1.', true);
    unlockButton(button, originalLabel);
    return;
  }

  const payload = {
    meetingId,
    audioUrl,
    volume
  };

  showStatus('Playing audio...');

  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/meetings/audio/play`, {
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
  } finally {
    unlockButton(button, originalLabel);
  }
});

// Display the current API URL endpoint
function updateApiUrlDisplay() {
  if (DOM_CACHE.apiUrl) {
    DOM_CACHE.apiUrl.textContent = `API: ${API_BASE_URL}`;
  }
}