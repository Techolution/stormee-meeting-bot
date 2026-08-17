# Meeting Bot

Sends a headless browser into a video meeting, records the meeting's audio, and
produces a transcript.

One process runs one meeting. A meeting is started over HTTP, the bot joins and
waits to be admitted, and audio is streamed out continuously while the meeting
runs — so a bot that dies mid-meeting still leaves everything captured up to
that point.

```
       HTTP                                        ┌──────────────────┐
  ──────────────►  ┌───────────────┐   WebSocket   │  Audio service   │
                   │  Meeting Bot  │ ─────────────►│  (separate)      │
                   │               │               └──────────────────┘
                   │  browser      │
                   │  recording    │      HTTP     ┌──────────────────┐
                   │  transcript   │ ─────────────►│  CW backend      │
                   └───────┬───────┘               │  uploads,        │
                           │ Playwright            │  artifacts, mail │
                           ▼                       └──────────────────┘
                   ┌───────────────┐
                   │  Google Meet  │
                   └───────────────┘
```

## Contents

| Document | What it covers |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Getting it running locally, and in Docker |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is put together and why |
| [docs/ENTRY_POINTS.md](docs/ENTRY_POINTS.md) | What calls what — start here when tracing a call |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting, with defaults |
| [docs/API.md](docs/API.md) | Endpoint reference and typical flows |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Deploying, monitoring, diagnosing |
| [docs/TESTING.md](docs/TESTING.md) | How the suite is organised |
| [docs/MIGRATION.md](docs/MIGRATION.md) | Mapping from the previous codebase |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Conventions, and where new code goes |
| [docs/adr/](docs/adr/) | Decision records for the choices worth explaining |

## Quick start

Requires Python 3.10+ and Chromium (installed via Playwright).

```bash
make install          # dependencies + Chromium
cp .env.example .env  # then fill in CW_UTILS_URL and PROJECT_ID
make run              # http://localhost:5000/api/meet/docs
```

Send the bot into a meeting:

```bash
curl -X POST http://localhost:5000/api/meet/meetings/join \
  -H 'Content-Type: application/json' \
  -d '{
        "meetingId":  "demo-001",
        "meetingUrl": "https://meet.google.com/abc-defg-hij",
        "userEmail":  "you@example.com",
        "projectId":  "your-project-id"
      }'
```

`join` returns immediately — admission depends on a human host, which can take
minutes. Poll for progress:

```bash
curl http://localhost:5000/api/meet/meetings/demo-001/status
```

Then record, and stop when done:

```bash
curl -X POST http://localhost:5000/api/meet/recordings/start   -d '{"meetingId":"demo-001"}' -H 'Content-Type: application/json'
curl -X POST http://localhost:5000/api/meet/transcription/start -d '{"meetingId":"demo-001"}' -H 'Content-Type: application/json'

curl -X POST http://localhost:5000/api/meet/recordings/stop    -d '{"meetingId":"demo-001"}' -H 'Content-Type: application/json'
curl -X POST http://localhost:5000/api/meet/meetings/leave     -d '{"meetingId":"demo-001"}' -H 'Content-Type: application/json'
```

Leaving finalizes any recording still running, so `leave` alone is a safe way to
end a meeting.

## Layout

```
app/
├── api/                 HTTP layer — routes, error translation, middleware
├── meeting/             Orchestration: MeetingManager, MeetingSession, lifecycle
├── browser/             Chromium via Playwright. Knows nothing about meetings.
├── meeting_platform/    The MeetingPlatform interface + the Google Meet driver
├── recording/           Capture → buffer → order → upload
├── transcription/       The TranscriptionProvider interface + caption provider
├── websocket/           Client-side connection to the audio service
├── context/             Accumulated meeting context
├── runtime/             In-process status: what this pod is doing now
├── repositories/        Durable meeting state (Redis, or in-memory)
├── clients/             Every outbound network boundary
├── schemas/             HTTP and wire contracts
├── core/                Config, logging, correlation, errors, timing
└── bootstrap.py         The only module that wires interfaces to implementations
```

Dependencies point inward. `core` imports nothing from the domain; `meeting`
names no concrete platform, transport, or storage backend. Which implementation
satisfies which interface is decided in exactly one place, `bootstrap.py` — see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

```bash
make test       # full suite
make lint       # ruff
make typecheck  # mypy
make check      # all three
```

The suite runs without Chromium, a network, or Redis: the browser, the audio
service, and every HTTP client sit behind interfaces with test doubles. See
[docs/TESTING.md](docs/TESTING.md).

## Operational notes

- **One meeting per pod.** Readiness reports `503` while a meeting is in
  progress, so a scheduler will not send a second one.
- **Graceful shutdown matters here.** On `SIGTERM` the bot finalizes its
  recording and closes Chromium before exiting. Give it a
  `terminationGracePeriodSeconds` long enough to finish — see
  [docs/OPERATIONS.md](docs/OPERATIONS.md).
- **Audio survives an outage.** If the audio service is unreachable, chunks are
  buffered (bounded) and replayed on reconnect. With no audio service configured
  at all, the bot uploads to object storage itself.
