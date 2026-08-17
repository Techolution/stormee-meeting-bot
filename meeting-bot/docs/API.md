# API reference

Base path: `/api/meet` (configurable via `API_PREFIX`).

Interactive documentation is generated from the code and is the authoritative
schema:

- Swagger UI — `/api/meet/docs`
- ReDoc — `/api/meet/redoc`
- OpenAPI — `/api/meet/openapi.json`

## Contents

- [Conventions](#conventions)
- [Errors](#errors)
- [Typical flow](#typical-flow)
- [Meeting](#meeting)
- [Recording](#recording)
- [Transcription and chat](#transcription-and-chat)
- [Status](#status)
- [Health](#health)

---

## Conventions

**Field names are camelCase.** Requests and responses use `meetingId`,
`audioUrl`, `chunksUploaded`. Internally the code is snake_case; the translation
happens at this boundary.

**A meeting is addressed by the `meetingId` you supply.** It is caller-assigned,
not generated. Every later call uses it.

**`sessionId` identifies one attendance.** The same meeting rejoined after a
failure gets a new `sessionId`, which is what lets logs be correlated across a
retry.

**Joining is asynchronous.** `POST /meetings/join` returns `202` as soon as the
session is registered. Admission depends on a human host and can take minutes, so
progress is reported through `GET /meetings/{meetingId}/status`.

**`X-Request-ID` is honoured and echoed.** Send one and it appears on every log
line for that request; omit it and one is generated. It is returned on every
response, including errors.

---

## Errors

Every failure has the same envelope:

```json
{
  "code": "meeting_not_found",
  "message": "No active session for meeting 'demo-001'",
  "details": { "meeting_id": "demo-001" },
  "requestId": "3f9c2a10-..."
}
```

Branch on `code`, not on `message`.

| Code | Status | Meaning |
|---|---|---|
| `validation_error` | 422 | Malformed request. `details.fields` lists each problem. |
| `meeting_not_found` | 404 | No session on this pod for that `meetingId`. |
| `meeting_already_active` | 409 | Already running, or the pod is at capacity. |
| `authentication_required` | 403 | The meeting forbids anonymous joins; configure a browser profile. |
| `meeting_admission_timeout` | 502 | Reached the lobby, never admitted. |
| `meeting_join_failed` | 502 | Could not enter for another reason. |
| `unsupported_platform` | 400 | The meeting URL matches no implemented platform. |
| `browser_launch_failed` | 500 | Chromium would not start. Check the pod's resources and image. |
| `browser_not_available` | 409 | The operation needs a live page and there is none. |
| `element_not_found` | 502 | An expected control was missing — usually a platform UI change. |
| `recording_already_active` | 409 | A recording is already running. |
| `recording_not_active` | 409 | No recording to stop. |
| `recording_error` | 500 | Capture could not start — typically the page is gone. |
| `chunk_upload_failed` | 502 | Audio could not be persisted. |
| `transcription_not_active` | 409 | Transcription was never started. |
| `transcription_error` | 500 | The transcript source could not be started. |
| `unsupported_transcription_provider` | 500 | `TRANSCRIPTION_PROVIDER` names no registered provider. |
| `websocket_error` | 502 | The audio-service connection failed. |
| `websocket_not_connected` | 409 | A send was attempted while disconnected. Normally handled internally by buffering. |
| `external_service_error` | 502 | A dependency failed. `details.service` names it. |
| `configuration_error` | 500 | Misconfiguration, or startup did not complete. |
| `internal_error` | 500 | Unexpected. Nothing internal is exposed; quote `requestId`. |

`meeting_error`, `browser_error` and `transcription_error` also exist as base
classes. Only `transcription_error` is raised directly; the other two appear only
through their subclasses above.

---

## Typical flow

```
POST /meetings/join                 202  bot begins joining
      │
GET  /meetings/{id}/status          poll until session_state == "in_meeting"
      │
POST /recordings/start              begin capturing audio
POST /transcription/start           begin producing a transcript
      │
      ⋮                             meeting runs
      │
POST /transcription/stop            returns the transcript
POST /meetings/leave                finalizes the recording, releases the browser
```

`leave` finalizes a running recording, so `recordings/stop` is optional if you are
ending the meeting anyway.

---

## Meeting

### `POST /meetings/join`

Send the bot into a meeting. Returns `202`; the join continues in the background.

```json
{
  "meetingId": "demo-001",
  "meetingUrl": "https://meet.google.com/abc-defg-hij",
  "userName": "Alice Smith",
  "userEmail": "alice@example.com",
  "projectId": "project-123",
  "projectName": "Q3 Planning",
  "meetingTitle": "Weekly Sync"
}
```

| Field | Required | Notes |
|---|---|---|
| `meetingId` | yes | Caller-assigned. Must be unique among active sessions. |
| `meetingUrl` | yes | Absolute `http(s)` URL. Currently must be a Google Meet link. |
| `userName` | no | Falls back to `DEFAULT_USER_NAME`. |
| `userEmail` | no | Falls back to `DEFAULT_USER_EMAIL`. Recipient of the ready notification. |
| `projectId` | no | Falls back to `PROJECT_ID`. Determines where the recording is filed. |
| `projectName` | no | Falls back to `PROJECT_NAME`. Used in mail. |
| `meetingTitle` | no | Defaults to `Meeting <date>`. Display name for the artifact. |

**202**

```json
{ "message": "Joining meeting", "meetingId": "demo-001", "sessionId": "a3f9c21054ab8e70" }
```

**409 `meeting_already_active`** — a session for that id exists, or the pod is
already in a meeting. A bot pod handles one meeting at a time.

### `POST /meetings/leave`

Leave and release the browser. Finalizes a running recording first.

```json
{ "meetingId": "demo-001" }
```

**200** `{ "message": "Left meeting", "meetingId": "demo-001" }`

### `POST /meetings/audio/play`

Play audio into the meeting through the bot's virtual microphone. Unmutes first if
needed.

```json
{ "meetingId": "demo-001", "audioUrl": "https://cdn.example.com/reply.wav", "volume": 0.7 }
```

`volume` is `0.0`–`1.0`, default `0.7`. The URL must be reachable from inside the
browser.

### `POST /meetings/audio/mute` · `POST /meetings/audio/unmute`

```json
{ "meetingId": "demo-001" }
```

---

## Recording

### `POST /recordings/start`

Begin capturing the meeting's mixed audio — remote participants plus anything the
bot plays.

```json
{ "meetingId": "demo-001" }
```

Audio is chunked every `RECORDING_CHUNK_DURATION_MS` and streamed continuously, so
an interrupted recording retains everything captured beforehand.

**409 `recording_already_active`** if one is running.

### `POST /recordings/stop`

Stop capturing, flush buffered audio, and finalize the upload. Returns once the
object is closed and downstream processing has been requested — so a `200` means
the recording is durable.

```json
{ "meetingId": "demo-001" }
```

### `GET /recordings/{meetingId}/status`

```json
{
  "meetingId": "demo-001",
  "status": "recording",
  "chunksCaptured": 48,
  "chunksUploaded": 47,
  "chunksPending": 1,
  "bytesUploaded": 3145728,
  "startedAt": "2026-08-17T10:15:00+00:00",
  "stoppedAt": null,
  "transport": "websocket"
}
```

`status` is one of `idle`, `starting`, `recording`, `stopping`, `stopped`,
`failed`.

**`chunksPending` is the number to watch.** Steadily above zero means the
destination is unreachable and audio is buffering; when the buffer's limits are
reached, the oldest audio is dropped.

---

## Transcription and chat

### `POST /transcription/start`

Begin producing a transcript with the configured provider. Enables captions if
they are off.

```json
{ "meetingId": "demo-001" }
```

### `POST /transcription/stop`

Stop and return the full transcript.

```json
{
  "message": "Transcription stopped",
  "meetingId": "demo-001",
  "count": 2,
  "segments": [
    { "speaker": "Alice Smith", "text": "Let us start with the roadmap.",
      "timestamp": "2026-08-17T10:16:04+00:00", "source": "caption" },
    { "speaker": "Bob Jones", "text": "Sounds good.",
      "timestamp": "2026-08-17T10:16:11+00:00", "source": "caption" }
  ]
}
```

`source` records where a segment came from, so a transcript assembled from more
than one source stays attributable.

### `GET /transcription/{meetingId}/transcript`

The transcript so far, without stopping. Same shape as above.

Segments appear only once an utterance is *complete* — captions mutate in place
while someone is still speaking, so the sentence in progress is not yet a segment.

### `GET /transcription/{meetingId}/chat`

In-meeting chat messages collected so far. Chat is monitored for the whole
session, so nothing needs starting.

```json
{
  "message": "Chat messages retrieved",
  "meetingId": "demo-001",
  "count": 1,
  "chatSegments": [
    { "sender": "Bob Jones", "text": "stormee start recording",
      "timestamp": "2026-08-17T10:15:58+00:00", "messageId": "messages/abc123" }
  ]
}
```

---

## Status

### `GET /status`

Everything this pod is doing. Reads in-memory state only, so it is safe to poll
frequently.

```json
{
  "service": "meeting-bot",
  "version": "1.0.0",
  "environment": "prod",
  "uptimeSeconds": 421.3,
  "activeSessions": 1,
  "sessions": [ "…see below…" ],
  "configuration": { "…secrets reported as booleans…" }
}
```

### `GET /meetings/{meetingId}/status`

Runtime status for one session.

```json
{
  "meeting_id": "demo-001",
  "session_id": "a3f9c21054ab8e70",
  "session_state": "in_meeting",
  "uptime_seconds": 305.1,
  "participant_count": 4,
  "healthy": true,
  "last_heartbeat": "2026-08-17T10:20:02+00:00",
  "components": [
    { "name": "browser",       "state": "active" },
    { "name": "platform",      "state": "active" },
    { "name": "recording",     "state": "active", "detail": { "transport": "websocket" } },
    { "name": "transcription", "state": "active", "detail": { "provider": "caption" } },
    { "name": "websocket",     "state": "active" }
  ],
  "websocket": { "state": "connected", "uptime_seconds": 300.0, "reconnect_attempts": 0 }
}
```

`session_state`: `created`, `joining`, `in_meeting`, `leaving`, `ended`, `failed`.
Component `state`: `idle`, `starting`, `active`, `degraded`, `stopping`,
`stopped`, `failed`.

**`healthy` excludes the websocket deliberately.** Audio buffers locally while
streaming is down, so a dropped connection degrades a session rather than breaking
it.

### `GET /meetings/{meetingId}/state`

The most recent **persisted** transition. Distinct from `/status`: this survives
the pod, and is readable from any instance sharing the state store.

```json
{
  "meetingId": "demo-001",
  "state": {
    "state": "recording_stopped",
    "timestamp": "2026-08-17T10:45:00+00:00",
    "metadata": { "complete": true, "uploaded_bytes": 8912896 }
  }
}
```

**404** if nothing is recorded for that meeting.

### `GET /meetings/{meetingId}/state/history?limit=100`

Recorded transitions, newest first. Returns an empty list rather than 404 for an
unknown meeting — a history read has a valid empty answer.

### `DELETE /meetings/{meetingId}/state`

Remove a meeting's recorded history.

---

## Health

### `GET /health`

Liveness. Answers "is this process up?" and touches no dependency — failing it
restarts the pod, so it must never depend on anything external.

```json
{ "status": "ok", "service": "meeting-bot", "version": "1.0.0", "environment": "prod" }
```

### `GET /ready`

Readiness. Answers "can this pod take work?".

```json
{
  "ready": false,
  "dependencies": [
    { "name": "state_repository", "healthy": true },
    { "name": "cw_utils",         "healthy": true },
    { "name": "audio_service",    "healthy": true },
    { "name": "capacity",         "healthy": false, "detail": "1 session(s) in progress" }
  ]
}
```

Returns **503 while a meeting is in progress**. That is intentional: it is what
stops a scheduler sending a second meeting to a pod that is already busy. It also
returns 503 when neither an audio service nor a CW backend is configured, since
there would be nowhere for audio to go.

---

## Notes for integrators

**Poll `/meetings/{id}/status`, do not assume a join succeeded.** A `202` means
the request was accepted. `session_state` becoming `failed` with `last_error` set
is how a failure is reported.

**Treat 409 on join as "this pod is busy", not as an error.** Dispatch to another
pod.

**Do not poll `/recordings/{id}/status` for completion.** `POST /recordings/stop`
returning `200` is the completion signal.

**Send `X-Request-ID`.** It is the fastest way to find the corresponding server
logs.
