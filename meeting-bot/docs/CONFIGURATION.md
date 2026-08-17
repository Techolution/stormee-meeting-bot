# Configuration

Every setting the bot reads, with its default and what it affects.

All configuration enters the process through `app/core/config.py` and nowhere
else. No module calls `os.getenv`, which is what keeps the full set of knobs
discoverable in one file.

## How it is organised

Settings are grouped by concern, and each group is an independent settings model
with its own environment prefix:

```python
settings.app.log_level              # APP_LOG_LEVEL, or LOG_LEVEL
settings.browser.headless           # BROWSER_HEADLESS, or HEADLESS
settings.recording.chunk_duration_ms  # RECORDING_CHUNK_DURATION_MS
settings.redis.host                 # REDIS_HOST
```

Where a clearer name exists, **both are accepted and the new one wins**. That is
deliberate: deployments already set the older names, and silently renaming them
would break those deployments on the next release. See
[Legacy names](#legacy-names) for the full mapping.

Invalid configuration fails at **startup**, not at first use. A bad log level or a
malformed email stops the process immediately rather than surfacing minutes into
a meeting.

---

## Required

Only these have no working default.

| Variable | Purpose |
|---|---|
| `CW_UTILS_URL` | Creative Workspace backend. Without it, recordings cannot be stored or registered. |
| `PROJECT_ID` | Default project a recording is filed under when a join request omits `projectId`. |

The bot starts without them and logs a warning naming what is inactive — silent
degradation is the hardest kind of misconfiguration to diagnose.

---

## Application

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `local` | `local` \| `dev` \| `qa` \| `prod`. Sets the default log level. |
| `LOG_LEVEL` | derived | Explicit level. Unset: `DEBUG` locally, `INFO` in dev/qa/prod. |
| `LOG_FORMAT` | `text` | `text` for humans, `json` for aggregators. Use `json` outside local. |
| `APP_HOST` | `0.0.0.0` | Bind address. |
| `APP_PORT` | `5000` | Bind port. |
| `API_PREFIX` | `/api/meet` | Prefix for every route, including docs and probes. |
| `CORS_ORIGINS` | `*` | Comma-separated origins. Narrow this in production. |

---

## Browser

| Variable | Default | Description |
|---|---|---|
| `BROWSER_HEADLESS` | `true` | `false` opens a real window. Needs a display; invaluable for debugging a join. |
| `BROWSER_PROFILE_DIR` | `chrome_profile` | Chromium user-data directory. **When it exists** the bot joins as the account signed in there; otherwise it joins as a guest. No separate flag. |
| `BROWSER_GUEST_DISPLAY_NAME` | `Stormee.Ai` | Name shown in the participant list. |
| `BROWSER_LAUNCH_TIMEOUT_MS` | `30000` | Per-attempt launch timeout. |
| `BROWSER_LAUNCH_MAX_ATTEMPTS` | `3` | Launch attempts before giving up. Container launches fail intermittently. |
| `BROWSER_LAUNCH_RETRY_DELAY_SECONDS` | `3.0` | Delay between attempts. |
| `BROWSER_SCREENSHOT_DIR` | unset | When set, join failures are captured here. |

---

## Meeting behaviour

| Variable | Default | Description |
|---|---|---|
| `MEETING_ADMISSION_TIMEOUT_SECONDS` | `300` | How long to wait in the lobby for a host. Raise it if hosts are habitually late; the bot occupies a pod for the whole wait. |
| `MEETING_ADMISSION_POLL_INTERVAL_SECONDS` | `2.0` | Lobby poll interval. |
| `MEETING_PARTICIPANT_POLL_INTERVAL_SECONDS` | `2.0` | Headcount poll interval. |
| `MEETING_SOLO_GRACE_PERIOD_SECONDS` | `120` | How long the bot stays alone before leaving. Must stay well above a reconnect: a brief drop to one participant is routine, and leaving on it abandons live meetings. |
| `MEETING_AUTO_LEAVE_WHEN_ALONE` | `true` | Set `false` and a forgotten bot occupies its pod until killed. |
| `MEETING_CHAT_COMMANDS_ENABLED` | `true` | Let participants drive the bot from the meeting chat. |
| `MEETING_CHAT_COMMAND_PREFIX` | `stormee` | Prefix a chat command must start with. |

Recognised chat commands: `start recording`, `stop recording`,
`start caption recording`, `stop caption recording`, `leave`.

---

## Recording

| Variable | Default | Description |
|---|---|---|
| `RECORDING_CHUNK_DURATION_MS` | `5000` | MediaRecorder timeslice — one chunk per interval. Lower means finer-grained recovery and more overhead. |
| `RECORDING_UPLOAD_TRANSPORT` | `websocket` | `websocket` streams to the audio service; `direct` uploads from this process. `websocket` falls back to `direct` automatically when `WEBSOCKET_URL` is unset. |
| `RECORDING_RESUMABLE_BLOCK_SIZE_BYTES` | `262144` | Bytes accumulated per resumable PUT. **Must be a multiple of 256 KiB** — object storage rejects a short non-final block. |
| `RECORDING_UPLOAD_TIMEOUT_SECONDS` | `300.0` | Per-block upload timeout. |
| `RECORDING_FINALIZE_GRACE_PERIOD_SECONDS` | `2.0` | Time allowed for in-flight chunks after the recorder stops. Set to zero and the last chunk is lost. |
| `RECORDING_QUEUE_MAX_CHUNKS` | `100` | Chunks buffered while the destination is unreachable. |
| `RECORDING_QUEUE_MAX_MEMORY_MB` | `10` | Memory ceiling for that buffer. |
| `RECORDING_CONTENT_TYPE` | `audio/webm;codecs=opus` | Must match what the browser produces. |

**On the queue limits.** At capacity the oldest audio is dropped. That is a
deliberate trade: unbounded buffering during a long outage exhausts the pod and
loses the entire meeting, whereas a recording with a gap is still useful. At the
defaults, 100 chunks × 5 s covers roughly 8 minutes of outage.

---

## Transcription

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_PROVIDER` | `caption` | Transcript source. Only in-meeting captions are implemented. |
| `TRANSCRIPTION_POLL_INTERVAL_SECONDS` | `1.0` | Caption poll interval. Captions mutate quickly; polling much slower loses text mid-utterance. |
| `TRANSCRIPTION_CONTEXT_BUFFER_MAX_SEGMENTS` | `5000` | Cap on retained context. Beyond it the oldest is discarded. |

---

## Audio service

Optional. When unset, the bot uploads recordings itself.

| Variable | Default | Description |
|---|---|---|
| `WEBSOCKET_URL` | unset | Socket.IO endpoint of the audio service. Empty disables streaming. |
| `WEBSOCKET_PATH` | `api/meet/socket.io` | Socket.IO mount path. |
| `WEBSOCKET_CONNECT_TIMEOUT_SECONDS` | `15.0` | Handshake timeout. |
| `WEBSOCKET_REQUEST_TIMEOUT_SECONDS` | `30.0` | Timeout for acknowledged calls, including `recordingEnded`. |
| `WEBSOCKET_AUTO_RECONNECT` | `true` | Supervise the connection and reconnect in the background. **Turning this off means buffered audio only drains at end of recording.** |
| `WEBSOCKET_MAX_RECONNECT_ATTEMPTS` | `5` | Attempts before giving up. |
| `WEBSOCKET_RECONNECT_DELAY` | `1000` | Initial backoff, ms. |
| `WEBSOCKET_BACKOFF_FACTOR` | `2.0` | Backoff multiplier. |
| `WEBSOCKET_MAX_RECONNECT_DELAY` | `30000` | Backoff ceiling, ms. |

Delays are jittered. Without jitter, every bot pod that lost the audio service
reconnects on the same schedule and lands as a synchronised burst when it returns.

---

## CW backend

| Variable | Default | Description |
|---|---|---|
| `CW_UTILS_URL` | unset | Base URL. Also the default for `MAIL_BASE_URL`. |
| `CW_UTILS_TIMEOUT_SECONDS` | `120.0` | Request timeout. |
| `CW_UTILS_MAX_RETRIES` | `2` | Retries on a transient failure (408, 429, 5xx). |
| `CW_PROJECT_URL_TEMPLATE` | `https://dev.appmod.ai/mode/...` | Deep link used in notification mail. Must contain `{project_id}`. |
| `CW_ARTIFACT_MODEL_TYPE` | `google` | Model family for artifact generation. |
| `CW_ARTIFACT_LLM` | `claude-3.5-sonnet` | Model used for artifact generation. |

---

## Meeting-state persistence

Optional. Redis when configured and reachable, in-memory otherwise; meetings run
either way.

| Variable | Default | Description |
|---|---|---|
| `REDIS_ENABLED` | `true` | `false` uses the in-memory store without attempting a connection. |
| `REDIS_HOST` | `localhost` | Hostname. |
| `REDIS_PORT` | `6379` | Port. |
| `REDIS_DB` | `0` | Database number. |
| `REDIS_PASSWORD` | unset | Password. Reported on `/status` as a boolean, never as a value. |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | `5.0` | Connect and read timeout. |
| `REDIS_STATE_TTL_SECONDS` | `3600` | Expiry on state and history keys, so a killed pod cannot leak them. |
| `REDIS_HISTORY_MAX_ENTRIES` | `500` | History list is trimmed to this on write. |

Availability is rechecked periodically rather than latched at startup, so a bot
launched while Redis is restarting recovers instead of logging nothing for its
entire life.

---

## Upstream Meeting API

| Variable | Default | Description |
|---|---|---|
| `MEETING_API_URL` | unset | When set, the bot posts status callbacks as a meeting progresses. |
| `MEETING_API_TIMEOUT_SECONDS` | `30.0` | Request timeout. |

Callbacks are best-effort: a failure is logged, never raised. The bot's job is to
run the meeting, not to guarantee delivery of telemetry.

---

## Mail

| Variable | Default | Description |
|---|---|---|
| `MAIL_ENABLED` | `true` | Send "your recording is ready" notifications. |
| `MAIL_BASE_URL` | `CW_UTILS_URL` | Mail relay base URL. |
| `MAIL_TIMEOUT_SECONDS` | `30.0` | Request timeout. |

---

## Attribution defaults

Used when a join request omits them.

| Variable | Default | Description |
|---|---|---|
| `PROJECT_ID` | unset | Default project. |
| `PROJECT_NAME` | unset | Default project name, used in mail. |
| `DEFAULT_USER_NAME` | `Unknown User` | Default recipient name. |
| `DEFAULT_USER_EMAIL` | `no-reply@example.com` | Default recipient address. Validated at startup. |

---

## Legacy names

Accepted for compatibility with existing deployments. The new name wins when both
are set.

| Legacy | Current |
|---|---|
| `ENV` | `ENVIRONMENT` |
| `HEADLESS` | `BROWSER_HEADLESS` |
| `PROFILE_DIR` | `BROWSER_PROFILE_DIR` |
| `TIMEOUT_MS` | `BROWSER_LAUNCH_TIMEOUT_MS` |
| `MAX_RETRIES` | `BROWSER_LAUNCH_MAX_ATTEMPTS` |
| `BACKEND_URL` | `CW_UTILS_URL` |
| `WAIT_TIME_FOR_BOT_LAST_PARTICIPANT` | `MEETING_SOLO_GRACE_PERIOD_SECONDS` |
| `AUDIO_QUEUE_MAX_CHUNKS` | `RECORDING_QUEUE_MAX_CHUNKS` |
| `AUDIO_QUEUE_MAX_MEMORY_MB` | `RECORDING_QUEUE_MAX_MEMORY_MB` |
| `MEETING_STATE_TTL` | `REDIS_STATE_TTL_SECONDS` |
| `PORT` | `APP_PORT` |

Two names from the previous implementation are **no longer read**, because the
behaviour they controlled no longer exists in this process:

| Removed | Why |
|---|---|
| `BROWSER_TYPE` | Only Chromium is supported. Firefox and WebKit lack the media flags the audio pipeline needs. |
| `JOIN_AS_GUEST` | Now inferred from whether `BROWSER_PROFILE_DIR` exists, so the flag cannot disagree with reality. |

---

## Inspecting live configuration

```bash
curl -s localhost:5000/api/meet/status | python3 -c \
  'import json,sys; print(json.dumps(json.load(sys.stdin)["configuration"], indent=2))'
```

Secrets are reported as booleans (`password_set: true`), never as values.
