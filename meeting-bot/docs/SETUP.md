# Setup

Getting the meeting bot running locally and in Docker.

## Requirements

| | Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.12 in the container image |
| Chromium | — | installed by Playwright, not from your package manager |
| ffmpeg | any recent | only needed for local audio-format conversion |
| Redis | 5+ | optional; the bot runs without it |

The bot needs roughly **1.5 GB of RAM** and **1 CPU** while in a meeting.
Chromium with an active WebRTC session is the bulk of that.

---

## Local install

```bash
cd meeting-bot
make install
```

That creates `.venv`, installs the package with its dev extras, and downloads the
Chromium build Playwright expects. **Use Playwright's Chromium** — a
distro-provided browser is a different build and the automation flags do not
behave the same way.

Configure:

```bash
cp .env.example .env
```

Only two things must be set:

```dotenv
CW_UTILS_URL=https://dev.appmod.ai   # where recordings are uploaded
PROJECT_ID=your-project-id           # default project for a recording
```

Run:

```bash
make run
```

- API docs: <http://localhost:5000/api/meet/docs>
- Liveness: <http://localhost:5000/api/meet/health>
- Status: <http://localhost:5000/api/meet/status>

`make run` uses the project's own `.venv`. If you are managing your environment
yourself, any of these work and are equivalent:

```bash
uvicorn app.main:app          # what the container runs
python -m app.main            # adds --reload outside prod
python app/main.py            # same, run from anywhere
```

All three must be run with the project's dependencies available — `make install`,
or `pip install -e ".[dev]"` into whichever environment you are using. A bare
`ModuleNotFoundError: No module named 'fastapi'` means the environment is not the
one that was installed into.

### Verifying the install

```bash
make check    # lint, types, tests — all three should pass
```

The suite needs no browser, no network, and no Redis. If it fails, the problem is
the install rather than the environment.

---

## Joining your first meeting

Start a Google Meet in your own browser, then:

```bash
curl -X POST http://localhost:5000/api/meet/meetings/join \
  -H 'Content-Type: application/json' \
  -d '{
        "meetingId":  "test-001",
        "meetingUrl": "https://meet.google.com/your-meet-code",
        "userEmail":  "you@example.com",
        "projectId":  "your-project-id"
      }'
```

The call returns `202` immediately. The bot then asks to join and waits — **you
must admit it from the meeting**, because without a signed-in profile it joins as
a guest.

Watch progress:

```bash
curl -s localhost:5000/api/meet/meetings/test-001/status | python3 -m json.tool
```

`session_state` moves `created → joining → in_meeting`.

Record, then finish:

```bash
curl -X POST localhost:5000/api/meet/recordings/start   -H 'Content-Type: application/json' -d '{"meetingId":"test-001"}'
curl -X POST localhost:5000/api/meet/transcription/start -H 'Content-Type: application/json' -d '{"meetingId":"test-001"}'

curl -X POST localhost:5000/api/meet/meetings/leave      -H 'Content-Type: application/json' -d '{"meetingId":"test-001"}'
```

`leave` finalizes a running recording first, so it is a safe way to end a meeting.

### Watching the browser

A join that fails is much easier to diagnose with a visible window:

```bash
make run-headful
```

Also useful:

```dotenv
BROWSER_SCREENSHOT_DIR=/tmp/meeting-bot-screenshots
```

The bot captures the page whenever a join step cannot find what it expects.

---

## Joining as a signed-in account

Without a browser profile the bot joins as a guest and needs a host to admit it.
With one, it joins as that Google account and is often admitted automatically.

```bash
make auth-profile
```

A browser opens; sign in to the Google account the bot should use, then press
Enter. The session is written to `chrome_profile/`.

Then point the bot at it:

```dotenv
BROWSER_PROFILE_DIR=chrome_profile
```

The bot uses a persistent profile when the directory exists and falls back to a
guest join when it does not — no flag to keep in sync.

> `chrome_profile/` contains live Google session cookies. It is in `.gitignore`
> and must never be committed or baked into an image. In a cluster, mount it as a
> secret or a volume.

---

## Docker

```bash
make docker-build
make docker-run
```

`docker-run` passes `.env`, mounts `chrome_profile/`, and sets `--ipc=host`.

> **`--ipc=host` is required.** Chromium's shared-memory needs exceed Docker's
> default 64 MB `/dev/shm`, and without it the browser crashes partway through a
> meeting — usually once video tiles appear. `--shm-size=2g` works too.

Manually:

```bash
docker run --rm -it \
  --ipc=host \
  -p 5000:5000 \
  --env-file .env \
  -v "$PWD/chrome_profile:/data/chrome_profile" \
  meeting-bot:local
```

With a profile mounted there, set `BROWSER_PROFILE_DIR=/data/chrome_profile`.

### Local Redis

Optional. Meeting-state history survives a restart with it and does not without.

```bash
docker run -d --name meeting-bot-redis -p 6379:6379 redis:7-alpine
```

```dotenv
REDIS_ENABLED=true
REDIS_HOST=localhost
```

`/api/meet/ready` reports whether the bot actually connected.

---

## Troubleshooting

**`BrowserLaunchError` on startup**

Playwright's Chromium is missing:

```bash
.venv/bin/playwright install --with-deps chromium
```

**Browser dies partway through a meeting, in Docker**

Missing `--ipc=host` (see above).

**`authentication_required` from a join**

The meeting forbids anonymous participants. Set up a profile with
`make auth-profile`.

**`meeting_admission_timeout`**

Nobody admitted the bot within `MEETING_ADMISSION_TIMEOUT_SECONDS`. Either admit
it, or use a signed-in profile.

**Recording produces no file**

Check `/api/meet/status`:

- `recording.transport` — `websocket` means the audio service owns the upload, so
  look there; `direct` means this process does, so look at its logs.
- `chunks_pending` above zero and rising means the destination is unreachable.
- Warnings at startup name every unconfigured integration.

**Transcript is empty**

Captions must be on. The bot enables them, but Meet occasionally moves the
control — check the logs for `Could not confirm captions were enabled`, and
`app/meeting_platform/google_meet/selectors.py` for the selectors to update.

**Profile locked / browser will not start with a profile**

A killed pod can leave a lock behind:

```bash
rm -f chrome_profile/SingletonLock
```

---

## Next

- [CONFIGURATION.md](CONFIGURATION.md) — every setting
- [API.md](API.md) — endpoint reference
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it works
- [OPERATIONS.md](OPERATIONS.md) — deploying it
