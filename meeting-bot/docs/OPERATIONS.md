# Operations

Running the meeting bot in a cluster.

## Contents

- [Deployment shape](#deployment-shape)
- [Graceful shutdown](#graceful-shutdown)
- [Resources](#resources)
- [Probes](#probes)
- [Secrets](#secrets)
- [Observability](#observability)
- [Diagnosing incidents](#diagnosing-incidents)
- [Capacity](#capacity)

---

## Deployment shape

**One pod runs one meeting.** A pod owns a Chromium instance and a browser
profile; a second concurrent meeting would double its memory while breaking the
readiness contract. `MeetingManager` enforces the limit
(`max_concurrent_sessions=1`) and `/ready` reports `503` while busy.

Two viable topologies:

**Pool of warm pods.** A `Deployment` of N replicas; a dispatcher picks a pod
reporting `ready: true`. Simple, fast to join, wastes idle capacity.

**Pod per meeting.** A `Job` per meeting, created by the dispatcher. No idle
waste, but each meeting pays image-pull and browser-start latency (10–30 s).

Manifests for the first are in [`deploy/k8s/`](../deploy/k8s/).

---

## Graceful shutdown

**This is the setting most likely to cost you a recording.**

On `SIGTERM` the bot finalizes its recording — flushes buffered audio, closes the
storage object, registers the upload — and then releases Chromium. If the pod is
killed before that finishes, the recording is truncated or lost entirely, and a
Chromium process may be orphaned.

```yaml
spec:
  terminationGracePeriodSeconds: 180   # not the 30s default
```

Why 180: the shutdown sequence is bounded at 180 s by `MeetingManager`, dominated
by a worst-case final flush over a slow link. Anything less and Kubernetes sends
`SIGKILL` mid-flush.

The sequence, and what each step protects:

| Step | Timeout | If skipped |
|---|---|---|
| cancel in-flight join | 10 s | shutdown queues behind a multi-minute lobby wait |
| stop heartbeat | 5 s | — |
| stop monitors | 10 s | — |
| stop transcription | 15 s | the final utterance is lost |
| **stop recording** | **120 s** | **the recording is lost** |
| disconnect socket | 15 s | — |
| leave meeting | 20 s | the bot lingers in the participant list |
| close browser | 30 s | a Chromium process is orphaned |

Every step runs even if an earlier one failed, and each is individually bounded —
a hung leave-call cannot prevent the browser from being released.

Verify it works:

```bash
kubectl logs <pod> --previous | tail -30
# Expect: "Shutting down meeting-bot" … "Session shutdown complete" … "Shutdown complete"
```

Seeing `Session teardown exceeded its timeout` means the grace period needs
raising, or the upload destination is slow.

---

## Resources

```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2"
```

Chromium with an active WebRTC session is essentially all of this. Memory is the
constraint that matters: **an OOM kill loses the recording**, because it bypasses
graceful shutdown entirely. Prefer a generous limit over a tight one.

### `/dev/shm`

Chromium's shared-memory needs exceed the 64 MB Kubernetes provides by default,
and it crashes partway through a meeting — usually once video tiles appear.

```yaml
volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 1Gi
volumeMounts:
  - name: dshm
    mountPath: /dev/shm
```

This is not optional. It is the single most common cause of a bot that joins
successfully and dies ten minutes later.

### Buffer sizing

`RECORDING_QUEUE_MAX_MEMORY_MB` (default 10) bounds audio held while the
destination is unreachable. At 5-second chunks the default covers roughly 8
minutes of outage. Raise it if your audio service restarts take longer — and
raise the memory limit with it.

---

## Probes

```yaml
livenessProbe:
  httpGet: { path: /api/meet/health, port: 5000 }
  initialDelaySeconds: 20
  periodSeconds: 30
  failureThreshold: 3

readinessProbe:
  httpGet: { path: /api/meet/ready, port: 5000 }
  initialDelaySeconds: 10
  periodSeconds: 10
```

`/health` is dependency-free and true whenever the event loop runs. `/ready`
reports `503` while a meeting is in progress, which removes the pod from
dispatch without killing the meeting.

> Never point liveness at `/ready`. A pod in a meeting is deliberately not ready,
> and liveness on that endpoint restarts it mid-meeting.

The in-process heartbeat is the complement to these: it detects a bot whose
browser has died while the HTTP server still answers, and ends the session so the
pod becomes available again.

---

## Secrets

| Secret | Notes |
|---|---|
| `chrome_profile/` | Live Google session cookies. Treat as a credential. |
| `REDIS_PASSWORD` | From a `Secret`, never in the manifest. |
| `CW_UTILS_URL` | Not secret, but environment-specific. |

The browser profile is the sensitive one — it is an authenticated Google session.
Mount it, never bake it into an image:

```yaml
volumes:
  - name: browser-profile
    secret:
      secretName: meeting-bot-browser-profile
volumeMounts:
  - name: browser-profile
    mountPath: /data/chrome_profile
    readOnly: false        # Chromium writes to its profile directory
```

Create it with `make auth-profile` locally, then load the directory into a
`Secret`. Rotate it when the Google session expires — a stale profile causes the
bot to fall back to guest joins, which need host admission.

---

## Observability

### Logs

Set `LOG_FORMAT=json` outside local development. Every line carries the
correlation fields:

```json
{
  "timestamp": "2026-08-17T10:15:03+0000",
  "level": "INFO",
  "logger": "app.recording.recorder",
  "message": "Recording stopped",
  "meeting_id": "demo-001",
  "session_id": "a3f9c21054ab8e70",
  "request_id": "3f9c2a10-...",
  "chunks_captured": 120,
  "bytes_uploaded": 8912896
}
```

`meeting_id` is the field to index. Every log line produced while handling a
meeting — including from background tasks — carries it.

### Lines worth alerting on

| Message | Severity | Meaning |
|---|---|---|
| `Final block upload failed` | **critical** | A recording is incomplete. |
| `Recording finalized with chunks still buffered` | **critical** | Audio was captured but not stored. |
| `Audio buffer at capacity; dropped oldest chunks` | **high** | Audio is being lost right now. |
| `Session teardown exceeded its timeout` | **high** | Shutdown is not completing; raise the grace period. |
| `Reconnection abandoned` | high | Streaming is down for the rest of the meeting. |
| `Could not create an upload target` | high | The recording will not be persisted. |
| `Session declared dead by heartbeat` | medium | The browser died mid-meeting. |
| `Abandoning caption transcription` | medium | Transcript will be incomplete. |
| `Could not find a join control` | medium | Likely a Meet UI change — check selectors. |
| `Redis unavailable` | low | History only; meetings are unaffected. |

### Metrics worth deriving

There is no metrics endpoint; these come from logs or `/status`:

- `chunksPending` over time — sustained non-zero means audio is buffering.
- Join duration (`waited_seconds` on admission) — rising means hosts are slow.
- Session count vs. replica count — how much of the pool is busy.
- OOM kill rate — each one is a lost recording.

---

## Diagnosing incidents

### A recording is missing

1. `GET /meetings/{id}/state/history` — did `recording_started` and
   `recording_stopped` both happen?
2. Check `recording_stopped` metadata for `complete: true`.
3. If `complete: false`, read `detail`.
4. `transport: websocket` means the audio service owns the upload — check there.
   `transport: direct` means this pod does — check its logs for
   `Final block upload failed`.
5. If the pod was OOM-killed (`kubectl describe pod`, reason `OOMKilled`),
   graceful shutdown never ran. Raise the memory limit.

### The bot will not join

Match the error code to the cause:

| Code | Cause | Fix |
|---|---|---|
| `authentication_required` | Meeting forbids anonymous joins | Mount a browser profile |
| `meeting_admission_timeout` | Nobody admitted it | Use a profile, or raise the timeout |
| `element_not_found` | Meet UI changed | Update `selectors.py`; check screenshots |
| `browser_launch_failed` | Chromium missing or resource-starved | Check image and limits |

Set `BROWSER_SCREENSHOT_DIR` to capture the page on join failures — for a UI
change, that image is the fastest route to the fix.

### The bot joined but produced nothing

`GET /meetings/{id}/status` and read the components:

- `recording: idle` — nothing called `/recordings/start`.
- `recording: degraded` — the upload is failing; read `detail`.
- `transcription: idle` — nothing called `/transcription/start`.
- `websocket: degraded` — streaming is down and audio is buffering.
- `healthy: false` — read `last_error`.

### The pod is stuck in a meeting

The heartbeat should end a session whose browser has died. If it has not:

```bash
curl -X POST localhost:5000/api/meet/meetings/leave \
  -H 'Content-Type: application/json' -d '{"meetingId":"<id>"}'
```

That runs the full teardown, including finalizing the recording — always prefer it
over deleting the pod.

---

## Capacity

Rough sizing:

| Concurrent meetings | Replicas | Memory | CPU |
|---|---|---|---|
| 5 | 5 (+1 spare) | 6–12 Gi | 3–12 |
| 20 | 20 (+2 spare) | 22–44 Gi | 11–44 |

Spares matter because joining takes 10–30 seconds before the meeting even starts.

Autoscaling on CPU works poorly here: a bot in a quiet meeting uses little CPU
while being entirely unavailable. Scale on `activeSessions` from `/status`, or on
the dispatcher's queue depth.
