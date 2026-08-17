# Migration from the previous implementation

What moved where, what changed behaviourally, and what to check when deploying.

The previous codebase (`legacy/`) is preserved for reference. This document maps
it onto the current structure so that a question of the form "where did X go?"
has a definite answer.

## Contents

- [What changed structurally](#what-changed-structurally)
- [File mapping](#file-mapping)
- [Behavioural changes](#behavioural-changes)
- [Bugs fixed](#bugs-fixed)
- [API changes](#api-changes)
- [Configuration changes](#configuration-changes)
- [Deployment checklist](#deployment-checklist)

---

## What changed structurally

**The Socket.IO server is gone.** The previous `main.py` hosted a Socket.IO
*server* and the bot connected to it as a *client* — often to itself. The server
half is the audio service, which is deployed separately, so this codebase is now
client-only. Its ingest logic was not discarded: it lives on as the `direct`
upload transport, so a deployment without an audio service still works.

**The god service is decomposed.** `stormee_meet_bot_service.py` (1,458 lines)
did browser automation, DOM scraping, WebSocket transport, HTTP upload, email,
and state management in one class. Those are now separate packages behind
interfaces, with `MeetingSession` coordinating them.

**`utilities/` is gone.** Every file in it had a real home:

```
utilities/cw_utils.py        →  clients/cw_utils.py       (an API client, not a utility)
utilities/mail_utils.py      →  clients/mail.py + clients/templates.py
utilities/env_config.py      →  core/config.py
utilities/logging_config.py  →  core/logging.py
utilities/logging_context.py →  core/request_context.py
utilities/error_handler.py   →  core/exceptions.py + core/timers.py
utilities/browser_utils.py   →  deleted (it was empty)
utilities/doc_utils.py       →  deleted (see below)
```

---

## File mapping

### Entry point and API

| Previous | Current | Notes |
|---|---|---|
| `main.py` | `app/main.py` + `app/bootstrap.py` | Socket.IO server removed; wiring extracted to a composition root. |
| `routes/stormee_meet_bot_routes.py` | `app/api/routes/*.py` | Split by resource. |
| `controllers/stormee_meet_bot_controller.py` | *(removed)* | It only forwarded to the service. Routes now call `MeetingManager` directly. |

### Core service

| Previous responsibility | Current home |
|---|---|
| `MeetBot.ensure_auth_session` | `browser/browser_manager.py` |
| `MeetBot.join_meeting`, `join_as_guest` | `meeting_platform/google_meet/platform.py` |
| `MeetBot.check_meeting_status` | `meeting_platform/google_meet/scripts/room_state.js` |
| `MeetBot.scrape_captions`, `stop_captions` | `transcription/caption_provider.py` + `caption_aggregator.py` |
| `MeetBot.start_chat_scraping` | `meeting/chat_monitor.py` |
| `MeetBot.get_participant_count`, monitoring | `meeting/participant_monitor.py` |
| `MeetBot.start_audio_recording` | `recording/recorder.py` |
| `MeetBot._handle_audio_chunk` | `recording/audio_capture.py` |
| `MeetBot.play_audio_url` | `meeting_platform/google_meet/platform.py` |
| `MeetBot.leave_meeting` | `meeting/meeting_session.py` (`_teardown`) + `lifecycle.py` |
| `MeetBot.save_audio` | *(removed — see below)* |
| `create_bot_for`, `get_bot`, `remove_bot` | `meeting/meeting_manager.py` + `runtime/session.py` |

### Services

| Previous | Current |
|---|---|
| `services/websocket_manager.py` | `websocket/connection_manager.py` |
| `services/stormee_websocket_caller.py` | `websocket/client.py` + `clients/audio_service.py` |
| `services/reconnection_strategy.py` | `websocket/reconnection.py` |
| `services/websocket_events.py` | Split: client events → `websocket/event_handler.py`; upload logic → `recording/chunk_uploader.py` + `clients/object_storage.py`; post-upload work → `recording/upload_finalizer.py` |
| `services/audio_queue_manager.py` | `recording/audio_buffer.py` |
| `services/audio_stream_producer.py` | `recording/audio_capture.py` |
| `services/chunk_upload_manager.py` | `recording/sequencer.py` |
| `services/meeting_state_manager.py` | Split: durable → `repositories/`; runtime → `runtime/state.py` |
| `services/state_persistence_manager.py` | `repositories/redis_repository.py` |
| `services/graceful_shutdown_manager.py` | `meeting/lifecycle.py` |

### Google Meet

| Previous | Current |
|---|---|
| `utilities/meet_utils/google_meet/meet_action_controller.py` | `meeting_platform/google_meet/actions.py` |
| `utilities/meet_utils/google_meet/js_helpers.py` | `meeting_platform/google_meet/scripts/*.js` |

The JavaScript was extracted **verbatim** into real `.js` files. It is the part
most sensitive to the browser's behaviour, and rewriting it during a
restructuring would have made any resulting bug impossible to attribute. Inline
JS that had been embedded in Python strings was extracted into the same
directory.

Selectors, previously scattered across both files, are now in
`meeting_platform/google_meet/selectors.py`.

---

## Behavioural changes

Read this section before deploying.

### The WebSocket now reconnects

Previously, `ReconnectionStrategy` existed but nothing drove it: the client was
created with `reconnection=False` and no supervision loop, and the
`set_on_reconnect_success` callback was never invoked. Buffered audio therefore
drained only when the recording stopped.

Now `ConnectionManager` supervises the connection and drains the buffer on
reconnect. Set `WEBSOCKET_AUTO_RECONNECT=false` to restore the old behaviour.

### Audio buffers are per-session

`AudioQueueManager` was a process-wide singleton shared by every bot in the
process. With more than one meeting, chunks from different meetings interleaved
into each other's uploads. Each session now owns its buffer.

### Transcripts contain the whole meeting

Caption polling overwrote its buffer with each snapshot
(`self.live_caption_buffer = current_snapshot`), so the final transcript held only
the last few seconds of visible captions. `CaptionAggregator` now reconstructs
utterances across snapshots. **Transcripts will be substantially longer.**

### Participant monitoring actually runs

The monitor loop was gated on `while self.chat_scraping_active`, but was started
from `join_meeting`, where chat scraping was not active — so the loop exited
immediately and auto-leave never fired. It now runs for the session's lifetime.

### Joining a meeting twice is refused

`create_bot_for` returned the existing bot when asked to join an active meeting,
which reported a fresh join that never happened. It is now a `409
meeting_already_active`.

### Local audio assembly was removed

`save_audio` combined chunks in memory, wrote a `.webm`, shelled out to `ffmpeg`,
uploaded the `.mp3`, and deleted both. It was already dead code — the call site
was commented out — and it held an entire meeting's audio in memory. Audio is now
streamed to storage as it is captured, which is both bounded and resilient to the
pod dying.

### DOCX transcript export was removed

`doc_utils.save_captions_to_docx` was also already commented out at its only call
site. Transcripts are returned by the API and streamed to the audio service. If a
DOCX artifact is needed, it belongs in CW alongside the other artifact
generation, not in the bot.

---

## Bugs fixed

Found while porting; each was reachable in production.

| Bug | Previous behaviour |
|---|---|
| Route/controller signature mismatch | `/stop`, `/audio`, `/pauseaudio` called `stop_captions_controller()` and friends with no arguments while the functions required `request` — an immediate `TypeError`, so those three endpoints could never succeed. |
| `play_audio` error handler crashed | The `except` branch read `request.audioData`, which does not exist on `PlayAudioRequest` (`audioUrl`) — an `AttributeError` inside the handler, masking the real error. |
| Global project id used for uploads | `save_audio` closed over the module-level `project_id` rather than the bot's, so a recording could be filed under the wrong project. |
| Chunk-tracking cleared early | `buffered_chunk_ids_in_upload_buffer.clear()` ran inside the 256 KiB loop, marking chunks uploaded whose bytes were still in the remainder buffer. |
| Redis availability latched at startup | A single failed ping at construction disabled state tracking permanently, so a bot started during a Redis restart logged nothing for its whole life. Availability is now rechecked. |
| Unbounded state history | `lpush` with no `ltrim`: a long meeting grew its history list without limit. Now trimmed on write. |
| Reserved log field crashed the upload path | `extra={"filename": ...}` collides with `LogRecord.filename`; stdlib logging raises `KeyError`. It sat on the recording-completion path. Fixed at the call sites, and `SafeLogger` now renames colliding keys so the class of bug cannot recur. |
| Keyword collision on the streaming path | `ComponentStatus.set(state, state=...)` — a `TypeError` inside a non-critical startup step, which meant it was swallowed and streaming silently never connected. |
| Shutdown could hang indefinitely | A session stuck in browser launch or lobby wait blocked `SIGTERM` handling, so the pod was `SIGKILL`ed and its recording lost. Joins are now cancelled first and teardown is bounded. |

---

## API changes

Paths were reorganised by resource. The request and response *shapes* are
unchanged, so a client only needs its URLs updated.

| Previous | Current |
|---|---|
| `POST /api/meet/signin` | `POST /api/meet/meetings/join` |
| `POST /api/meet/exit` | `POST /api/meet/meetings/leave` |
| `POST /api/meet/start` | `POST /api/meet/transcription/start` |
| `POST /api/meet/stop` | `POST /api/meet/transcription/stop` |
| `POST /api/meet/record/start` | `POST /api/meet/recordings/start` |
| `POST /api/meet/record/stop` | `POST /api/meet/recordings/stop` |
| `GET /api/meet/record/status` | `GET /api/meet/recordings/{meetingId}/status` |
| `POST /api/meet/audio` | `POST /api/meet/meetings/audio/unmute` |
| `POST /api/meet/pauseaudio` | `POST /api/meet/meetings/audio/mute` |
| `POST /api/meet/audio/play` | `POST /api/meet/meetings/audio/play` |
| `POST /api/meet/chat/start` | *(removed — chat is monitored automatically)* |
| `POST /api/meet/chat/stop` | `GET /api/meet/transcription/{meetingId}/chat` |
| `GET /api/meet/health` | `GET /api/meet/health` *(unchanged)* |
| `GET /api/meet/meetings/{id}/state` | *(unchanged)* |
| `GET /api/meet/meetings/{id}/states` | `GET /api/meet/meetings/{id}/state/history` |
| — | `GET /api/meet/ready` *(new)* |
| — | `GET /api/meet/status` *(new)* |
| — | `GET /api/meet/meetings/{id}/status` *(new)* |
| — | `GET /api/meet/transcription/{id}/transcript` *(new)* |

Two other differences:

- `POST /meetings/join` returns **202**, not 200. It was always asynchronous; the
  status code now says so.
- Errors have a uniform envelope with a stable `code`. Previously they were
  `{"detail": "..."}` with prose that varied.

`GET /record/status` used to return a placeholder (`"not yet implemented"`). It
is now real.

---

## Configuration changes

Every legacy variable name is still accepted — see
[CONFIGURATION.md](CONFIGURATION.md#legacy-names) for the mapping. An existing
`.env` will work unchanged.

Two are no longer read:

| Removed | Why |
|---|---|
| `BROWSER_TYPE` | Only Chromium was ever supported; Firefox and WebKit lack the media flags the audio pipeline requires. |
| `JOIN_AS_GUEST` | Now inferred from whether `BROWSER_PROFILE_DIR` exists, so the flag cannot disagree with reality. |

New settings worth reviewing: `RECORDING_UPLOAD_TRANSPORT`, `LOG_FORMAT`,
`WEBSOCKET_AUTO_RECONNECT`, `MEETING_CHAT_COMMANDS_ENABLED`.

---

## Deployment checklist

1. **Update client URLs** using the table above. This is the only breaking change
   for callers.
2. **Set `RECORDING_UPLOAD_TRANSPORT`.** Keep `websocket` if the audio service is
   deployed and `WEBSOCKET_URL` is set; use `direct` otherwise. Leaving
   `websocket` set without a URL falls back to `direct` and logs a warning.
3. **Set `terminationGracePeriodSeconds: 180`.** The default 30 s will truncate
   recordings — see [OPERATIONS.md](OPERATIONS.md#graceful-shutdown).
4. **Mount `/dev/shm` with at least 1 Gi.** Without it Chromium crashes partway
   through meetings.
5. **Set `LOG_FORMAT=json`** outside local development.
6. **Point readiness at `/ready`, liveness at `/health`.** Not the same endpoint.
7. **Expect longer transcripts** and verify downstream consumers handle them.
8. **Watch `chunksPending`** on `/recordings/{id}/status` for the first few
   meetings to confirm the upload path is healthy.
