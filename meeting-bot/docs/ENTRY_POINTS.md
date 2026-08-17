# Entry points — what calls what

Read this when you are trying to work out how something gets called.

Most of this service is not called from another Python function. It is
event-driven: the browser calls into Python, the audio service pushes events in,
participants type commands, and timers fire polls. **Grepping for a caller will
find nothing in roughly twenty places**, and this document is the index of those
places.

If you are looking at a method and cannot find who calls it, it is almost
certainly listed here.

## Contents

- [The five ways code starts running](#the-five-ways-code-starts-running)
- [1. HTTP requests](#1-http-requests)
- [2. The browser page calling into Python](#2-the-browser-page-calling-into-python)
- [3. Audio-service events](#3-audio-service-events)
- [4. In-meeting chat commands](#4-in-meeting-chat-commands)
- [5. Background loops](#5-background-loops)
- [Internal callbacks](#internal-callbacks)
- [Process lifecycle](#process-lifecycle)
- [Answering "what calls this?"](#answering-what-calls-this)

---

## The five ways code starts running

```
  1. HTTP request        ──►  api/routes/*  ──►  MeetingManager  ──►  MeetingSession
  2. Browser page (JS)   ──►  AudioCapture.on_chunk        ──►  Recorder  ──►  ChunkUploader
  3. Audio-service event ──►  AudioServiceEventHandler     ──►  MeetingSession
  4. Chat command        ──►  ChatMonitor._dispatch_command ──►  MeetingSession
  5. Timer / loop        ──►  five polling loops           ──►  their own components
```

Only (1) reads as a normal call chain. The other four are inversions.

---

## 1. HTTP requests

The only conventional path. 19 routes, all thin: validate, call the manager,
shape the response.

```
uvicorn
  └─ app/main.py                     create_app(), lifespan
       └─ api/middleware.py          RequestContextMiddleware — binds request_id
            └─ api/routes/*.py       the handler
                 └─ meeting/meeting_manager.py
                      └─ meeting/meeting_session.py
                           └─ components
```

Errors never travel back up through the routes: they are raised as
`MeetingBotError` subclasses and translated centrally in `api/errors.py`. That is
why no handler has a `try`/`except`.

Full endpoint reference: [API.md](API.md).

---

## 2. The browser page calling into Python

**This is the least obvious flow in the codebase.** Audio does not travel down the
call chain — it arrives from JavaScript, asynchronously, every five seconds.

```
Setup (during Recorder.start):
    Recorder.start()
      └─ platform.bind_chunk_sink(audio_capture)
           └─ browser.expose_function("sendAudioChunkToPython", …)   ← binds the name

Runtime (repeatedly, for the life of the recording):
    recorder_start.js
      └─ mediaRecorder.ondataavailable
           └─ window.sendAudioChunkToPython({meetingId, chunkId, audioBlob})
                └─ GoogleMeetPlatform._receive          (platform.py, closure)
                     └─ AudioCapture.on_chunk           ← no Python caller
                          └─ Recorder._on_chunk
                               └─ ChunkUploader.upload
```

| | |
|---|---|
| Bound in | `meeting_platform/google_meet/platform.py` → `bind_chunk_sink` |
| Callback name | `sendAudioChunkToPython` (`_CHUNK_CALLBACK`) |
| Called from | `meeting_platform/google_meet/scripts/recorder_start.js` |
| Received by | `recording/audio_capture.py` → `AudioCapture.on_chunk` |

**`AudioCapture.on_chunk` must never raise.** An exception propagates into page
JavaScript and stops the recorder, silently ending the recording mid-meeting.
That is why it catches everything and counts failures instead.

The name is bound once per page. A second recording reuses the same binding,
which is why `AudioCapture` ignores chunks while inactive rather than being
rebound.

---

## 3. Audio-service events

The audio service can push work back to the bot.

```
audio service (Socket.IO)
  └─ websocket/client.py            WebSocketClient._wrap_handler
       └─ websocket/event_handler.py  AudioServiceEventHandler
            ├─ playAudio      ──► MeetingSession._handle_remote_play_audio
            ├─ leaveMeeting   ──► MeetingSession._handle_remote_leave
            └─ error          ──► logged only
```

| Event | Handler | Registered in |
|---|---|---|
| `playAudio` | `MeetingSession._handle_remote_play_audio` | `meeting_session.py::_connect_audio_service` |
| `leaveMeeting` | `MeetingSession._handle_remote_leave` | same |
| `error` | `AudioServiceEventHandler._handle_error` | `event_handler.py::register` |

Event names are constants in `schemas/websocket.py`. Unregistered events are
logged and dropped, not treated as errors.

---

## 4. In-meeting chat commands

A participant typing in the meeting chat can drive the bot.

```
participant types "stormee start recording"
  └─ ChatMonitor._poll_loop            (polls every second)
       └─ ChatMonitor._handle_new_message
            └─ ChatMonitor._dispatch_command   (longest match wins)
                 └─ MeetingSession._safe(…)    ← failures logged, never raised
                      └─ MeetingSession.start_recording()
```

Registered in `meeting_session.py::_register_chat_commands`:

| Chat text | Calls |
|---|---|
| `stormee start recording` | `MeetingSession.start_recording` |
| `stormee stop recording` | `MeetingSession.stop_recording` |
| `stormee start caption recording` | `MeetingSession.start_transcription` |
| `stormee stop caption recording` | `MeetingSession.stop_transcription` |
| `stormee leave` | `MeetingSession.stop` |

So `start_recording` has **three** callers: the HTTP route, a chat command, and
nothing else — but the chat one is invisible unless you know to look here.

Disable with `MEETING_CHAT_COMMANDS_ENABLED=false`.

---

## 5. Background loops

Five detached loops. Each is started through a `TaskSupervisor`
(`core/tasks.py`), never a bare `create_task`, so it is owned, logged and
cancellable. **Nothing calls these after they are spawned.**

| Loop | Started by | Stopped by | Interval |
|---|---|---|---|
| `CaptionTranscriptionProvider._poll_loop` | `start()` | `stop()` | `TRANSCRIPTION_POLL_INTERVAL_SECONDS` |
| `ChatMonitor._poll_loop` | `start()` | `stop()` | 1 s |
| `ParticipantMonitor._loop` | `start()` | `stop()` | `MEETING_PARTICIPANT_POLL_INTERVAL_SECONDS` |
| `Heartbeat._loop` | `start()` | `stop()` | 15 s |
| `ConnectionManager._reconnect_loop` | a dropped connection | `disconnect()` | backoff |

All five are started by `MeetingSession._start_monitors` or, for reconnection, by
the connection dropping. All five are cancelled by `MeetingSession._teardown`.

Where each loop's work goes:

```
CaptionProvider._poll_loop  ──► CaptionAggregator ──► MeetingSession._handle_transcript_segment
                                                          ├─► ContextBuffer
                                                          └─► audio service

ChatMonitor._poll_loop      ──► chat commands (see §4)

ParticipantMonitor._loop    ──► MeetingSession._handle_participant_change
                            └─► MeetingSession._handle_left_alone  ──► session.stop()

Heartbeat._loop             ──► MeetingSession._probe_liveness
                            └─► MeetingSession._handle_session_dead ──► session.stop()

ConnectionManager._reconnect_loop ──► MeetingSession._drain_buffered_audio
                                          └─► Recorder.flush_pending()
```

Note that **three different things can end a meeting**: the HTTP `leave` route, the
participant monitor finding the bot alone, and the heartbeat declaring the session
dead. All three converge on `MeetingSession.stop()`, which is why it is
idempotent.

---

## Internal callbacks

Registered once during startup, in `meeting_session.py::_connect_audio_service`
and `::_start_monitors`:

| Hook | Set on | Runs |
|---|---|---|
| `set_on_reconnect` | `ConnectionManager` | `MeetingSession._drain_buffered_audio` |
| `on_count_change` | `ParticipantMonitor` | `MeetingSession._handle_participant_change` |
| `on_alone` | `ParticipantMonitor` | `MeetingSession._handle_left_alone` |
| `on_dead` | `Heartbeat` | `MeetingSession._handle_session_dead` |
| `on_disconnect` | `WebSocketClient` | `ConnectionManager._handle_drop` |
| `add_done_callback` | join task | `MeetingManager._forget_startup_task` |
| `add_done_callback` | any supervised task | `TaskSupervisor._on_task_done` |

---

## Process lifecycle

```
uvicorn app.main:app
  └─ create_app()               builds the FastAPI app, configures logging
       └─ _lifespan()  ── startup ──►  build_application_context()   (bootstrap.py)
                                          └─ constructs every client, the manager,
                                             the state repository
                       ── shutdown ──►  ApplicationContext.aclose()
                                          └─ MeetingManager.shutdown()
                                               └─ per session: cancel join,
                                                  then MeetingSession.stop()
```

`bootstrap.py` is the **only** module that decides which implementation satisfies
which interface. If you are wondering where a concrete class gets chosen, it is
there.

Shutdown ordering and its rationale: [OPERATIONS.md](OPERATIONS.md#graceful-shutdown).

---

## Answering "what calls this?"

1. **Is it a route handler?** Called by FastAPI. See [API.md](API.md).
2. **Is it named `on_*`, `_handle_*`, or `_loop`?** It is an inversion — find it in
   the tables above. Its docstring also carries a `Called by:` line.
3. **Is it `AudioCapture.on_chunk`?** The caller is JavaScript. See §2.
4. **Is it a `MeetingSession` public method?** Called by `MeetingManager`, and
   possibly by a chat command (§4).
5. **Is it a concrete class being constructed?** `bootstrap.py`, or
   `MeetingSession._build_recorder` / `_build_uploader`.
6. **Is it on an interface?** The implementation is chosen by a registry —
   `meeting_platform/registry.py` or `transcription/provider.py`.

If none of those apply, it is an ordinary call and grep will find it.
