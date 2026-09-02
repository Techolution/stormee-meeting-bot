const ENVIRONMENTS = {
  local: 'http://localhost:5000/api/meet',
  development: 'https://dev.appmod.ai/api/meet',
  qa: 'https://qa.appmod.ai/api/meet',
  production: 'https://appmod.ai/api/meet'
};

const CW_API_BASE_URL = globalThis.CW_CONFIG?.CW_API_BASE_URL?.replace(/\/$/, '');

let API_BASE_URL = ENVIRONMENTS.local;
const REQUEST_TIMEOUT = 30000; // 30 seconds timeout for fetch requests
const STORAGE_DEBOUNCE_DELAY = 500; // Debounce storage writes by 500ms
const ACTION_THROTTLE_MS = 1500; // Prevent duplicate clicks while a request is in flight

// DOM Element Cache to reduce repeated getElementById() calls
const DOM_CACHE = {};

const BUTTON_LOCKS = new Map();
const SELECTED_MODE_IDS = new Set();

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
  DOM_CACHE.environmentDropdown = document.getElementById('environment-dropdown');
  DOM_CACHE.environmentDropdownTrigger = document.getElementById('environment-dropdown-trigger');
  DOM_CACHE.environmentSearch = document.getElementById('environment-search');
  DOM_CACHE.environmentOptions = document.getElementById('environment-options');
  DOM_CACHE.environmentEmpty = document.getElementById('environment-empty');
  DOM_CACHE.mode = document.getElementById('mode');
  DOM_CACHE.modeDropdown = document.getElementById('mode-dropdown');
  DOM_CACHE.modeDropdownTrigger = document.getElementById('mode-dropdown-trigger');
  DOM_CACHE.modeDropdownMenu = document.getElementById('mode-dropdown-menu');
  DOM_CACHE.modeSearch = document.getElementById('mode-search');
  DOM_CACHE.modeOptions = document.getElementById('mode-options');
  DOM_CACHE.modeEmpty = document.getElementById('mode-empty');
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

function closeEnvironmentDropdown() {
  DOM_CACHE.environmentDropdown?.classList.remove('open');
  DOM_CACHE.environmentDropdownTrigger?.setAttribute('aria-expanded', 'false');
}

function filterEnvironments(searchTerm) {
  const normalizedSearch = searchTerm.trim().toLocaleLowerCase();
  let visibleCount = 0;

  DOM_CACHE.environmentOptions?.querySelectorAll('.mode-option').forEach((option) => {
    const isVisible = option.dataset.environmentName.includes(normalizedSearch);
    option.hidden = !isVisible;
    if (isVisible) visibleCount += 1;
  });

  DOM_CACHE.environmentEmpty.style.display = visibleCount === 0 ? 'block' : 'none';
}

function getVisibleOptions(container) {
  return Array.from(container?.querySelectorAll('.mode-option') || [])
    .filter((option) => !option.hidden);
}

function moveOptionFocus(event, container) {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return false;

  const options = getVisibleOptions(container);
  if (options.length === 0) return true;

  event.preventDefault();
  const currentIndex = options.indexOf(document.activeElement);
  const direction = event.key === 'ArrowDown' ? 1 : -1;
  const nextIndex = currentIndex === -1
    ? (direction === 1 ? 0 : options.length - 1)
    : (currentIndex + direction + options.length) % options.length;
  options[nextIndex].focus();
  return true;
}

function selectEnvironment(environment, announce = true, persist = true) {
  DOM_CACHE.environment.value = environment;
  API_BASE_URL = ENVIRONMENTS[environment] || ENVIRONMENTS.local;
  DOM_CACHE.environmentDropdownTrigger.textContent =
    DOM_CACHE.environment.selectedOptions[0]?.textContent || 'Select an environment';
  DOM_CACHE.environmentOptions.querySelectorAll('.mode-option').forEach((option) => {
    const isSelected = option.dataset.environment === environment;
    option.classList.toggle('selected', isSelected);
    option.setAttribute('aria-selected', String(isSelected));
  });
  updateApiUrlDisplay();
  if (persist) chrome.storage.local.set({ environment });
  closeEnvironmentDropdown();
  if (announce) showStatus(`Environment changed to ${environment}`);
}

function setupEnvironmentDropdown() {
  DOM_CACHE.environmentOptions.replaceChildren();
  Array.from(DOM_CACHE.environment.options).forEach((environmentOption) => {
    const option = document.createElement('div');
    option.className = 'mode-option';
    option.dataset.environment = environmentOption.value;
    option.dataset.environmentName = environmentOption.textContent.toLocaleLowerCase();
    option.textContent = environmentOption.textContent;
    option.setAttribute('role', 'option');
    option.setAttribute('tabindex', '0');
    option.addEventListener('click', () => selectEnvironment(environmentOption.value));
    option.addEventListener('keydown', (event) => {
      if (moveOptionFocus(event, DOM_CACHE.environmentOptions)) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectEnvironment(environmentOption.value);
      }
    });
    DOM_CACHE.environmentOptions.append(option);
  });
  selectEnvironment(DOM_CACHE.environment.value, false, false);
}

function closeModeDropdown() {
  DOM_CACHE.modeDropdown?.classList.remove('open');
  DOM_CACHE.modeDropdownTrigger?.setAttribute('aria-expanded', 'false');
}

function filterModes(searchTerm) {
  const normalizedSearch = searchTerm.trim().toLocaleLowerCase();
  let visibleCount = 0;

  DOM_CACHE.modeOptions?.querySelectorAll('.mode-option').forEach((option) => {
    const isVisible = option.dataset.modeName.includes(normalizedSearch);
    option.hidden = !isVisible;
    if (isVisible) visibleCount += 1;
  });

  if (DOM_CACHE.modeEmpty) {
    DOM_CACHE.modeEmpty.style.display = visibleCount === 0 ? 'block' : 'none';
  }
}

function updateModeSelectionUI() {
  if (!DOM_CACHE.mode) return;

  Array.from(DOM_CACHE.mode.options).forEach((option) => {
    option.selected = SELECTED_MODE_IDS.has(option.value);
  });
  DOM_CACHE.modeOptions.querySelectorAll('.mode-option').forEach((option) => {
    const isSelected = SELECTED_MODE_IDS.has(option.dataset.modeId);
    option.classList.toggle('selected', isSelected);
    option.setAttribute('aria-selected', String(isSelected));
    option.querySelector('.mode-option-check').textContent = isSelected ? '✓' : '';
  });

  const names = Array.from(DOM_CACHE.mode.selectedOptions).map((option) => option.textContent);
  DOM_CACHE.modeDropdownTrigger.textContent = names.length === 0
    ? 'Select modes'
    : names.length === 1
      ? names[0]
      : `${names.length} modes selected`;
}

function toggleMode(modeId) {
  if (SELECTED_MODE_IDS.has(modeId)) SELECTED_MODE_IDS.delete(modeId);
  else SELECTED_MODE_IDS.add(modeId);
  updateModeSelectionUI();
  saveUserSettings(true);
}

async function loadModes(savedModeIds = []) {
  if (!DOM_CACHE.mode) return;

  if (!CW_API_BASE_URL) {
    DOM_CACHE.mode.innerHTML = '<option value="">Modes configuration missing</option>';
    showStatus('CW_API_BASE_URL is required.', true);
    return;
  }

  DOM_CACHE.mode.disabled = true;
  DOM_CACHE.mode.innerHTML = '<option value="">Loading modes...</option>';
  DOM_CACHE.modeDropdownTrigger.disabled = true;
  DOM_CACHE.modeDropdownTrigger.textContent = 'Loading modes...';
  DOM_CACHE.modeOptions.replaceChildren();

  try {
    const response = await fetchWithTimeout(`${CW_API_BASE_URL}/audio_mode/modes`, {
      method: 'GET',
      headers: { Accept: 'application/json' }
    });

    if (!response.ok) {
      throw new Error(`Fetching modes failed (${response.status}): ${await response.text()}`);
    }

    const modes = await response.json();
    if (!Array.isArray(modes)) {
      throw new Error('Modes API returned an unexpected response');
    }

    DOM_CACHE.mode.replaceChildren();
    DOM_CACHE.modeOptions.replaceChildren();
    const validModes = modes
      .map((mode) => ({
        modeId: mode?.mode_id ?? mode?.modeId,
        modeName: mode?.mode_name ?? mode?.modeName
      }))
      .filter((mode) => mode.modeId && mode.modeName);

    if (validModes.length === 0) {
      DOM_CACHE.mode.append(new Option('No modes available', ''));
      DOM_CACHE.modeDropdownTrigger.textContent = 'No modes available';
      return;
    }

    DOM_CACHE.mode.append(new Option('Select a mode', ''));
    validModes.forEach((mode) => {
      const option = new Option(mode.modeName, mode.modeId);
      DOM_CACHE.mode.append(option);

      const menuOption = document.createElement('div');
      menuOption.className = 'mode-option';
      menuOption.dataset.modeId = mode.modeId;
      menuOption.dataset.modeName = mode.modeName.toLocaleLowerCase();
      menuOption.setAttribute('role', 'option');
      menuOption.setAttribute('tabindex', '0');

      const check = document.createElement('span');
      check.className = 'mode-option-check';
      check.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.className = 'mode-option-text';
      label.textContent = mode.modeName;
      menuOption.append(check, label);

      menuOption.addEventListener('click', () => toggleMode(mode.modeId));
      menuOption.addEventListener('keydown', (event) => {
        if (event.target !== menuOption) return;
        if (moveOptionFocus(event, DOM_CACHE.modeOptions)) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          toggleMode(mode.modeId);
        }
      });
      DOM_CACHE.modeOptions.append(menuOption);
    });

    const validModeIds = new Set(validModes.map((mode) => mode.modeId));
    SELECTED_MODE_IDS.clear();
    savedModeIds
      .filter((modeId) => validModeIds.has(modeId))
      .forEach((modeId) => SELECTED_MODE_IDS.add(modeId));

    DOM_CACHE.mode.disabled = false;
    DOM_CACHE.modeDropdownTrigger.disabled = false;
    updateModeSelectionUI();
  } catch (error) {
    DOM_CACHE.mode.innerHTML = '<option value="">Unable to load modes</option>';
    DOM_CACHE.modeDropdownTrigger.textContent = 'Unable to load modes';
    DOM_CACHE.modeDropdownTrigger.disabled = true;
    showStatus(error.message, true);
  }
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
  setupEnvironmentDropdown();

  DOM_CACHE.environmentDropdownTrigger?.addEventListener('click', () => {
    const isOpen = DOM_CACHE.environmentDropdown.classList.toggle('open');
    DOM_CACHE.environmentDropdownTrigger.setAttribute('aria-expanded', String(isOpen));
    closeModeDropdown();
    if (isOpen) {
      DOM_CACHE.environmentSearch.value = '';
      filterEnvironments('');
      DOM_CACHE.environmentSearch.focus();
    }
  });

  DOM_CACHE.environmentDropdownTrigger?.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    if (!DOM_CACHE.environmentDropdown.classList.contains('open')) {
      DOM_CACHE.environmentDropdownTrigger.click();
    }
    const options = getVisibleOptions(DOM_CACHE.environmentOptions);
    (event.key === 'ArrowDown' ? options[0] : options.at(-1))?.focus();
  });

  DOM_CACHE.environmentSearch?.addEventListener('input', (event) => {
    filterEnvironments(event.target.value);
  });

  DOM_CACHE.environmentSearch?.addEventListener('keydown', (event) => {
    const options = getVisibleOptions(DOM_CACHE.environmentOptions);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      (event.key === 'ArrowDown' ? options[0] : options.at(-1))?.focus();
      return;
    }
    if (event.key === 'Enter' && options[0]) {
      event.preventDefault();
      selectEnvironment(options[0].dataset.environment);
      DOM_CACHE.environmentDropdownTrigger.focus();
      return;
    }
    if (event.key === 'Escape') {
      closeEnvironmentDropdown();
      DOM_CACHE.environmentDropdownTrigger.focus();
    }
  });

  DOM_CACHE.mode?.addEventListener('change', () => {
    saveUserSettings(true);
  });

  DOM_CACHE.modeDropdownTrigger?.addEventListener('click', () => {
    const isOpen = DOM_CACHE.modeDropdown.classList.toggle('open');
    DOM_CACHE.modeDropdownTrigger.setAttribute('aria-expanded', String(isOpen));
    closeEnvironmentDropdown();
    if (isOpen) {
      DOM_CACHE.modeSearch.value = '';
      filterModes('');
      DOM_CACHE.modeSearch.focus();
    }
  });

  DOM_CACHE.modeDropdownTrigger?.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    if (!DOM_CACHE.modeDropdown.classList.contains('open')) {
      DOM_CACHE.modeDropdownTrigger.click();
    }
    const options = getVisibleOptions(DOM_CACHE.modeOptions);
    (event.key === 'ArrowDown' ? options[0] : options.at(-1))?.focus();
  });

  DOM_CACHE.modeSearch?.addEventListener('input', (event) => {
    filterModes(event.target.value);
  });

  DOM_CACHE.modeSearch?.addEventListener('keydown', (event) => {
    const options = getVisibleOptions(DOM_CACHE.modeOptions);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      (event.key === 'ArrowDown' ? options[0] : options.at(-1))?.focus();
      return;
    }
    if (event.key === 'Enter' && options[0]) {
      event.preventDefault();
      toggleMode(options[0].dataset.modeId);
      return;
    }
    if (event.key === 'Escape') {
      closeModeDropdown();
      DOM_CACHE.modeDropdownTrigger.focus();
    }
  });

  document.addEventListener('click', (event) => {
    if (!DOM_CACHE.modeDropdown?.contains(event.target)) closeModeDropdown();
    if (!DOM_CACHE.environmentDropdown?.contains(event.target)) closeEnvironmentDropdown();
  });

  // Display current API URL
  updateApiUrlDisplay();

  // Load saved user config from local storage
  chrome.storage.local.get(
    ['userName', 'userEmail', 'projectId', 'projectName', 'environment', 'meetingUrl', 'meetingTitle', 'meetingId', 'maxDurationSeconds', 'generateIncrementalHighlights', 'modeId', 'modeIds'],
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
      } else if (DOM_CACHE.generateIncrementalHighlights) {
        // Default to true if no stored value exists
        DOM_CACHE.generateIncrementalHighlights.checked = true;
      }

      if (stored.environment) {
        selectEnvironment(stored.environment, false);
      }

      if (!DOM_CACHE.meetingId.value.trim() && DOM_CACHE.meetingUrl.value.trim()) {
        syncMeetingIdFromUrl();
      }

      const savedModeIds = Array.isArray(stored.modeIds)
        ? stored.modeIds
        : stored.modeId
          ? [stored.modeId]
          : [];
      loadModes(savedModeIds);

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
      environment: DOM_CACHE.environment ? DOM_CACHE.environment.value : 'local',
      modeIds: Array.from(SELECTED_MODE_IDS),
      modeId: SELECTED_MODE_IDS.values().next().value || ''
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
  const modeIds = Array.from(SELECTED_MODE_IDS);

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
    meetingTitle: meetingTitle || "Test Meet",
    ...(modeIds.length ? { modeId: modeIds[0], modeIds } : {})
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

  const payload = {
    meetingId,
    modeIds: Array.from(SELECTED_MODE_IDS)
  };

  const maxDurationSecondsInput = (DOM_CACHE.maxDurationSeconds?.value || '').trim();
  if (maxDurationSecondsInput !== '') {
    const maxDurationSecondsValue = Number.parseInt(maxDurationSecondsInput, 10);
    if (Number.isFinite(maxDurationSecondsValue) && maxDurationSecondsValue > 0) {
      payload.maxDurationSeconds = maxDurationSecondsValue;
    }
  }

  // Always send generateIncrementalHighlights - true by default, false if unchecked
  payload.generateIncrementalHighlights = DOM_CACHE.generateIncrementalHighlights ? DOM_CACHE.generateIncrementalHighlights.checked : true;

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
