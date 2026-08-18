# Architecture

How the meeting bot is put together, and why it is put together that way.

## Contents

- [What the service is](#what-the-service-is)
- [The one rule](#the-one-rule)
- [Layers](#layers)
- [Component model](#component-model)
- [The three interfaces](#the-three-interfaces)
- [Runtime flows](#runtime-flows)
- [Two kinds of state](#two-kinds-of-state)
- [Concurrency and background work](#concurrency-and-background-work)
- [Tracing a call](#tracing-a-call)
- [Failure handling](#failure-handling)
- [Extending it](#extending-it)

---

## What the service is

A meeting execution worker. One process joins one meeting, records its audio,
and produces a transcript.

It is deliberately *not* the system of record. Durable meeting state belongs to
the upstream Meeting API; recordings belong in object storage; audio ingest
belongs to the audio service. This process is the thing that sits in the meeting
and does the work, and it is designed to be disposable.

```
                     ┌──────────────────────────┐
                     │      Meeting API         │
                     │  (dispatcher, durable    │
                     │   state — external)      │
                     └────────────┬─────────────┘
                                  │ HTTP: start / stop
                                  ▼
     ┌────────────────────────────────────────────────────────┐
     │                    MEETING BOT                         │
     │                                                        │
     │   meeting lifecycle · browser · recording ·            │
     │   transcription · runtime state                        │
     └──────┬─────────────────────┬────────────────┬──────────┘
            │ Playwright          │ WebSocket      │ HTTP
            ▼                     ▼                ▼
     ┌─────────────┐      ┌──────────────┐   ┌──────────────┐
     │ Google Meet │      │ Audio service│   │  CW backend  │
     │  (browser)  │      │  (separate)  │   │  uploads,    │
     └─────────────┘      └──────────────┘   │  artifacts,  │
                                             │  mail        │
                                             └──────────────┘
```

The audio service is a separately deployed process. This bot is a **client** of
it and never a server for it — there is no Socket.IO server in this codebase,
which is the single biggest structural difference from the implementation it
replaces.

---

## The one rule

**Dependencies point inward.** Everything else follows from it.

```
  ┌──────────────────────────────────────────────────────┐
  │  api/            HTTP. Knows FastAPI. Knows nothing  │
  │                  about meetings.                     │
  ├──────────────────────────────────────────────────────┤
  │  meeting/        Orchestration. Names no concrete    │
  │                  platform, transport, or storage.    │
  ├──────────────────────────────────────────────────────┤
  │  interfaces      MeetingPlatform · TranscriptionProvider
  │                  ContextBuffer · ChunkUploader
  │                  MeetingStateRepository              │
  ├──────────────────────────────────────────────────────┤
  │  implementations google_meet/ · caption_provider ·   │
  │                  chunk_uploader · redis_repository   │
  ├──────────────────────────────────────────────────────┤
  │  clients/        Every outbound network boundary.     │
  ├──────────────────────────────────────────────────────┤
  │  core/           Config, logging, correlation,        │
  │                  errors, timing. Imports no domain.  │
  └──────────────────────────────────────────────────────┘
```

Three consequences worth stating explicitly, because they are what the rule buys:

1. **`app/bootstrap.py` is the only module that knows which implementation
   satisfies which interface.** Nothing else constructs a client, a platform, or
   a repository.
2. **`app/core` imports nothing from the domain.** Configuration and logging
   cannot develop opinions about meetings.
3. **A client never imports a domain model.** Serialisation to the wire happens
   on the domain side (`AudioChunk.as_wire_payload()`); the client transports
   what it is given. This was a real violation caught during development — the
   audio-service client imported `AudioChunk` and produced an import cycle.

---

## Layers

| Package | Owns | Must not |
|---|---|---|
| `api/` | HTTP routes, error translation, correlation middleware | Contain business logic |
| `meeting/` | Session lifecycle, ordering, component coordination | Perform browser, socket, or HTTP I/O directly |
| `browser/` | Chromium via Playwright | Know any Meet selector or meeting concept |
| `meeting_platform/` | The `MeetingPlatform` interface; the Meet driver | Leak a DOM node or locator past its boundary |
| `recording/` | Capture, buffering, ordering, upload | Know that a recording triggers email |
| `transcription/` | The provider interface; the caption provider | Know how captions are read from a page |
| `websocket/` | Keeping one client connection available | Know what any event means |
| `context/` | Accumulated meeting context | Know where it will eventually be stored |
| `runtime/` | In-process status | Be treated as durable |
| `repositories/` | Durable meeting state | Be required for a meeting to run |
| `clients/` | Outbound network boundaries | Import a domain model |
| `schemas/` | HTTP and wire contracts | Contain behaviour |
| `core/` | Config, logging, correlation, errors, timing | Import from any domain package |

---

## Component model

```
                            MeetingManager
                     (registry + process-level deps)
                                  │
                                  │ one per meeting
                                  ▼
                            MeetingSession
                            (orchestrator)
                                  │
   ┌───────────┬──────────────┬───┴───────┬─────────────┬──────────────┐
   ▼           ▼              ▼           ▼             ▼              ▼
Browser   MeetingPlatform  Recorder  Transcription  ChatMonitor  ConnectionManager
   │        (interface)       │        Provider          │              │
   │            │             │       (interface)        │              │
   │            ▼             │            │             │              ▼
   │     GoogleMeetPlatform   │            ▼             │      WebSocketClient
   │            │             │   CaptionProvider        │              │
   │            ▼             │            │             │              ▼
   │   ┌────────┴────────┐    │            ▼             │     AudioServiceClient
   │   │ actions.py      │    │     CaptionAggregator    │
   │   │ selectors.py    │    │            │             │
   │   │ scripts/*.js    │    │            ▼             │
   │   └─────────────────┘    │      ContextBuffer       │
   │                          │                          │
   ▼                          ▼                          ▼
Playwright            ChunkUploader              ParticipantMonitor
                     ┌──────┴───────┐
                     ▼              ▼
              Streaming        Direct
              (audio svc)   (object storage)
                                   │
                                   ▼
                            UploadFinalizer
                            (CW + mail)
```

`MeetingSession` is an orchestrator. It decides *what* happens and in *what
order*, and delegates every *how*. That is the specific thing the previous
implementation did not do, and the reason a change to upload behaviour used to
require editing meeting logic.

---

## The three interfaces

These exist from day one because each has a known second implementation coming.
An abstraction introduced for a migration that is already visible is not
speculative.

### `MeetingPlatform`

Google Meet today. Teams and Zoom are plausible tomorrow.

```python
class MeetingPlatform(ABC):
    async def join(self, request: JoinRequest) -> JoinResult: ...
    async def leave(self) -> None: ...
    async def get_participants(self) -> list[Participant]: ...
    async def get_captions(self) -> list[CaptionLine]: ...
    async def start_recording(self, meeting_id, *, chunk_duration_ms) -> RecordingHandle: ...
```

Observation methods degrade rather than raise: they are polled continuously, and
a transient DOM read failure is normal. Action methods raise, because a caller
asked for something specific.

The Meet implementation is layered so that Meet's habit of redesigning its UI
stays contained:

```
selectors.py   every DOM selector, named for intent
scripts/*.js   browser-side JavaScript as real .js files
actions.py     individual UI operations — click, type, toggle
platform.py    the flows those operations compose into
```

A Meet redesign is normally a change to the first two only.

### `TranscriptionProvider`

Captions today. Speech-to-text over the recorded audio next — the audio already
exists, and running recognition over it yields better text with real timing and
speaker diarisation.

```
                   TranscriptionProvider
                            ▲
              ┌─────────────┴──────────────┐
   CaptionTranscriptionProvider   SpeechTranscriptionProvider
              │                            │  (future)
              ▼                            ▼
      Meet caption area            recorded audio → STT
```

Meeting code starts and stops *a provider*. It never learns where the text came
from, which makes that migration a configuration change.

### `MeetingStateRepository`

Redis when configured and reachable, in-memory otherwise. The fallback is a
working implementation rather than a disabled flag, which keeps "is persistence
enabled?" out of every call site.

---

## Runtime flows

### Joining

```
POST /meetings/join
      │
      ▼
MeetingManager.join_meeting()          returns 202 immediately
      │                                (admission depends on a human host)
      ├─ SessionRegistry.add()         rejects a duplicate or over-capacity join
      └─ create_task(session.start())  manager holds the task
                    │
                    ▼
         LifecycleRunner.start([...])  stops at the first critical failure
                    │
      ┌─────────────┼──────────────┬───────────────────┬──────────────┐
      ▼             ▼              ▼                   ▼              ▼
 launch_browser  create_platform  join_meeting  connect_audio_service  start_monitors
  (critical)      (critical)      (critical)      (optional)          (optional)
                                      │
                                      ├─ navigate
                                      ├─ dismiss interstitial
                                      ├─ mute mic and camera
                                      ├─ submit join
                                      └─ poll until admitted
```

The critical/optional split is the point: a browser that will not launch ends the
attempt, while an unreachable audio service degrades it. Audio buffers locally
when streaming is down, so the meeting is still worth having.

### Recording

```
page MediaRecorder ── every 5s ──► sendAudioChunkToPython
                                          │
                                          ▼
                                    AudioCapture          never raises: an
                                    parse + count         exception here reaches
                                          │               page JS and stops the
                                          ▼               recorder mid-meeting
                                      Recorder
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
          StreamingChunkUploader                    DirectChunkUploader
                     │                                         │
          connected? ─── no ──► AudioBuffer         ChunkSequencer
                     │          (bounded;                      │
                    yes         head-drop)          256 KiB block accumulation
                     │              │                          │
                     ▼         on reconnect                    ▼
            AudioServiceClient   ──drain──►         ResumableUploadClient
                     │                                         │
                     ▼                                         ▼
             audio service                             object storage
                                                               │
                                                               ▼
                                                       UploadFinalizer
                                                    CW confirm → artifact → mail
```

Two properties this shape guarantees:

- **Audio survives an outage.** Chunks buffer, bounded, and replay in order once
  the link returns. The bound matters: unbounded buffering during a long outage
  takes the pod down and loses the whole meeting rather than part of it.
- **Order is preserved.** A WebM/Opus stream written out of order is not
  scrambled, it is unplayable. `ChunkSequencer` holds out-of-order arrivals until
  the gap ahead of them fills.

### Transcription

Meet's caption area is not a log. It shows two or three blocks, rewrites them in
place as a speaker continues, and drops them once they scroll away. Polling it
yields overlapping snapshots.

```
platform.get_captions()  ──► CaptionAggregator ──► TranscriptSegment
   (snapshot, mutating)         reassembles              │
                                                         ├─► ContextBuffer
                                                         └─► audio service
```

The aggregator mirrors the legacy bot: every poll replaces the previous live
buffer, and stopping returns only the latest visible ordered rows.

Adjacent rows with exactly identical text are deduplicated at stop time. This
prevents growing partial captions from accumulating across polls. Captions that
already scrolled away are intentionally not retained.

### Shutdown

Order encodes real constraints, so it is declared as data rather than implied by
statement order.

```
SIGTERM ──► lifespan ──► ApplicationContext.aclose()
                              │
                              ▼
                     MeetingManager.shutdown()
                              │
                     cancel in-flight join      ◄── or `stop` queues behind a
                              │                     multi-minute lobby wait
                              ▼
                  LifecycleRunner.shutdown([...])   every step runs, each bounded
                              │
   1. stop heartbeat          stop watching
   2. stop monitors           no new chat or participant events
   3. stop transcription      close the final utterance
   4. stop recording  ◄────── the step that must not be skipped:
                              flush, finalize, register the upload
   5. disconnect socket
   6. leave meeting           politely, while the page still exists
   7. close browser   ◄────── last, and unconditionally: a leaked Chromium
                              outlives the meeting and then the pod
```

Shutdown never aborts on a failure and every step has a timeout, because a hung
leave-call must not prevent the browser from being released.

---

## Two kinds of state

Conflating these is a mistake with consequences, so they are separate types in
separate packages.

| | Runtime state | Durable state |
|---|---|---|
| Module | `app/runtime/state.py` | `app/repositories/` |
| Question | "What is this pod doing right now?" | "What happened to this meeting?" |
| Lifetime | Dies with the process | Outlives it |
| Storage | In memory | Redis, or in-memory fallback |
| Read by | `/status`, health probes, the heartbeat | `/meetings/{id}/state`, other services |

Runtime state answers *should this pod be restarted?*. Durable state answers
*did this meeting get recorded?*. A decision that treats runtime state as the
source of truth silently changes its answer after a restart.

---

## Concurrency and background work

A session runs several loops at once: caption polling, chat polling, participant
monitoring, connection supervision, the heartbeat.

Every one is created through a `TaskSupervisor` (`app/core/tasks.py`) rather than
a bare `create_task`, which has two failure modes this codebase hit:

- The task object is garbage-collected mid-flight because nothing held a
  reference.
- An exception inside it disappears into a "Task exception was never retrieved"
  warning nobody reads.

A supervisor owns its tasks, logs their failures, and cancels them
deterministically on shutdown. `MeetingManager` applies the same discipline to
the session-startup task it spawns.

---

## Tracing a call

Most of this service is event-driven: the browser calls into Python, the audio
service pushes events in, participants type chat commands, and timers fire polls.
In roughly twenty places, **grepping for a caller finds nothing** — the caller is
JavaScript, a socket event, or a background loop.

[ENTRY_POINTS.md](ENTRY_POINTS.md) indexes every one of them, and each such method
carries a `Called by:` line in its docstring. Read it before concluding that
something is dead code.

The one that surprises people: audio does not flow *down* the call chain. It
arrives from `recorder_start.js` calling `window.sendAudioChunkToPython`, which is
bound to `AudioCapture.on_chunk` during `Recorder.start()`.

---

## Failure handling

Every deliberate failure derives from `MeetingBotError`, carries an HTTP status
and a stable `code`, and is translated to a response in exactly one place
(`app/api/errors.py`). Route handlers therefore contain no `try`/`except`.

```
MeetingBotError
├── ConfigurationError
├── MeetingError
│   ├── MeetingNotFoundError            404
│   ├── MeetingAlreadyActiveError       409
│   └── MeetingJoinError                502
│       ├── MeetingAdmissionTimeoutError
│       └── AuthenticationRequiredError 403
├── BrowserError
│   ├── BrowserLaunchError
│   ├── BrowserNotAvailableError        409
│   └── ElementNotFoundError            502
├── RecordingError
│   ├── RecordingAlreadyActiveError     409
│   ├── RecordingNotActiveError         409
│   └── ChunkUploadError                502
├── TranscriptionError
├── ExternalServiceError                502
├── WebSocketError                      502
└── UnsupportedPlatformError            400
```

Where degradation is correct rather than failure:

| Failure | Behaviour | Why |
|---|---|---|
| Audio service unreachable | Buffer locally, replay on reconnect | Losing the socket should not lose the audio |
| Redis unreachable | In-memory state | Meetings matter more than their history |
| Mail fails | Log and continue | The recording is already safe |
| Caption read fails | Retry; give up after a sustained run | A single failure is a page mid-render |
| Chunk malformed | Count, log, discard, continue | Never raise into page JavaScript |
| Browser will not launch | Fail the session | Nothing else can proceed |

---

## Extending it

### A new meeting platform

1. Implement `MeetingPlatform` under `app/meeting_platform/<platform>/`, using
   the same `selectors` / `scripts` / `actions` / `platform` split.
2. Register it: `register_platform("teams.microsoft.com", PlatformName.TEAMS, factory)`.

No change to `meeting/`, `recording/`, or `transcription/`.

### Speech-to-text transcription

1. Implement `TranscriptionProvider`, reading from the recorded audio.
2. `register_provider("speech", factory)`.
3. Set `TRANSCRIPTION_PROVIDER=speech`.

### Redis-backed context

Implement `ContextBuffer` and swap it in `MeetingSession`. The interface is three
methods precisely so this is possible without touching a caller.

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions, and [adr/](adr/) for the
decisions worth explaining at length.
