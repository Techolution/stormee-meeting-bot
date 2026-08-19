# API

Interactive documentation is generated from the code and is authoritative:

- Swagger UI — `/docs`
- ReDoc — `/redoc`
- OpenAPI — `/openapi.json`

## Conventions

**A session is addressed by `session_id`.** It is returned by
`POST /bot-sessions` and is the only identifier a caller needs. Which pod runs
the meeting is internal and never appears in a response.

**Field names are snake_case.** This is an internal control plane; the camelCase
translation happens one layer down, at the bot boundary.

**`X-Request-ID` is honoured and echoed.** Send one and it appears on every log
line for that request — in this service *and* in the bot pod, because the
handler forwards it. Omit it and one is generated.

**Dispatch is asynchronous.** `POST /bot-sessions/{id}/start` returns 202 once a
pod has accepted the join. Admission depends on a human host and can take
minutes, so the outcome is reported through the session's status.

## Errors

Every failure shares one envelope:

```json
{
  "code": "no_bot_pod_available",
  "message": "All 3 bot pod(s) are busy",
  "details": {"session_id": "a3f9...", "pods": 3},
  "requestId": "3f9c2a10..."
}
```

Branch on `code`, not on `message`.

| Code | Status | Meaning |
|---|---|---|
| `validation_error` | 422 | Malformed request. `details.fields` lists each problem. |
| `session_not_found` | 404 | No session with that id. |
| `session_already_exists` | 409 | A session with that id is already stored. |
| `invalid_session_state` | 409 | The command does not apply in the session's current state — already started, already recording. |
| `bot_service_not_assigned` | 409 | The session has never been dispatched, so there is no pod to command. |
| `no_bot_pod_available` | 503 | Every bot pod is busy or unreachable. Retry, or scale the bot Deployment. |
| `bot_service_unavailable` | 502 | The assigned pod did not answer. |
| `cluster_unavailable` | 503 | The Kubernetes API could not be reached. |
| `internal_error` | 500 | Unexpected. Nothing internal is exposed; quote `requestId`. |

Errors raised by the bot keep the bot's own code — `meeting_already_active`,
`recording_not_active`, `authentication_required` and the rest — with its
`requestId` under `details.botRequestId`. A 5xx from the bot is reported as 502
here; a 4xx keeps its status.

## Typical flow

```
POST /bot-sessions                        201  register the meeting
POST /bot-sessions/{id}/start             202  claim a pod, bot begins joining
GET  /bot-sessions/{id}/status                 poll until meeting_status == ACTIVE
POST /bot-sessions/{id}/recording/start   202
POST /bot-sessions/{id}/transcription/start 202
   ⋮ meeting runs
POST /bot-sessions/{id}/recording/stop    200  recording is durable when this returns
POST /bot-sessions/{id}/leave             200  finalizes and releases the pod
```

## Sessions

### `POST /bot-sessions`

```json
{
  "meeting_id": "google-calendar-event-id",
  "meeting_url": "https://meet.google.com/abc-defg-hij",
  "scheduled_at": "2026-08-19T10:00:00Z",
  "user_name": "Alice Smith",
  "user_email": "alice@example.com",
  "project_id": "project-123",
  "project_name": "Q3 Planning",
  "meeting_title": "Weekly Sync",
  "auto_start": false
}
```

Only `meeting_id` and `meeting_url` are required. `auto_start` dispatches
immediately instead of waiting for `/start`. `bot_service_url` pins the session
to one pod and bypasses discovery — for local development, or to re-attach to a
known pod.

**201** returns the session record, including `session_id`.

### `GET /bot-sessions` · `GET /bot-sessions/{session_id}`

The durable record, read from storage without touching a pod.
`?active_only=true` excludes finished sessions from the list.

### `POST /bot-sessions/{session_id}/start`

Claim a pod and send the bot in. **202**; poll status for the outcome.

**503 `no_bot_pod_available`** — no pod could take it.
**409 `invalid_session_state`** — already starting, running, or finished.

### `POST /bot-sessions/{session_id}/leave` · `/stop`

Leave the meeting and release the pod, finalizing a running recording. Safe to
retry: leaving a finished session is a no-op, not an error.

## Recording and transcription

`POST /bot-sessions/{id}/recording/start` (202) ·
`POST /bot-sessions/{id}/recording/stop` (200) ·
`POST /bot-sessions/{id}/transcription/start` (202) ·
`POST /bot-sessions/{id}/transcription/stop` (200) ·
`GET /bot-sessions/{id}/transcript` · `GET /bot-sessions/{id}/chat`

Starting something already running is `409 invalid_session_state`. Stopping
something that is not running is a no-op, so retries are safe. A 200 from
`recording/stop` means the recording is durable.

## Audio

`POST /bot-sessions/{id}/audio/play` with `{"audio_url": "...", "volume": 0.7}`,
plus `/audio/mute` and `/audio/unmute`. The URL must be reachable from inside
the bot's browser.

## Status

### `GET /bot-sessions/{session_id}/status`

Durable state, enriched with what the pod reports right now.

```json
{
  "session_id": "a3f9c21054ab8e70",
  "meeting_id": "demo-001",
  "meeting_status": "ACTIVE",
  "bot_status": "RUNNING",
  "recording_status": "RECORDING",
  "transcription_status": "RUNNING",
  "last_error": null,
  "timestamps": {"created_at": "...", "started_at": "...", "updated_at": "..."},
  "runtime": {"session_state": "in_meeting", "participant_count": 4, "healthy": true},
  "runtime_error": null
}
```

`runtime` is null with `runtime_error` set when the pod could not be reached —
the durable state is still returned. `?include_runtime=false` skips the pod
entirely.

`meeting_status`: `CREATED`, `STARTING`, `ACTIVE`, `LEAVING`, `COMPLETED`,
`FAILED`, `CANCELLED`.
`bot_status`: `PENDING`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, `FAILED`.

### `GET /bot-pods`

What the handler can see in the cluster, and which pods are free. See
[KUBERNETES.md](KUBERNETES.md).

## Health

`GET /health` — liveness; touches no dependency.
`GET /ready` — readiness; 503 when no bot pod can be discovered and no static
bot service is configured.
