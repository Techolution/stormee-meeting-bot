# Meeting Bot Handler

Control plane for meeting bots. It owns the durable state of a meeting session,
picks a bot pod in the cluster to run it, and drives that pod's lifecycle.

A client only ever holds a `session_id`. Which pod runs the meeting, where it
is, and whether it is still alive are this service's problem.

```
client → handler → (Kubernetes: find a free bot pod) → bot pod → Google Meet
```

## Quick start

The project runs in the `meeting-bot` conda environment (Python 3.12), shared
with the bot worker:

```bash
conda activate meeting-bot
make install                                       # first time only
```

Against a bot pod, without a cluster:

```bash
kubectl port-forward pod/<a-bot-pod> 5000:5000     # or run the bot locally
make run-local
```

```bash
# Register a meeting
SESSION=$(curl -sX POST localhost:8000/bot-sessions \
  -H 'Content-Type: application/json' \
  -d '{"meeting_id":"demo-001","meeting_url":"https://meet.google.com/abc-defg-hij"}' \
  | jq -r .session_id)

# Send the bot in, then poll until it is admitted
curl -sX POST localhost:8000/bot-sessions/$SESSION/start
curl -s localhost:8000/bot-sessions/$SESSION/status | jq .meeting_status

curl -sX POST localhost:8000/bot-sessions/$SESSION/recording/start
curl -sX POST localhost:8000/bot-sessions/$SESSION/recording/stop
curl -sX POST localhost:8000/bot-sessions/$SESSION/leave
```

In a cluster, drop `KUBERNETES_ENABLED=false` and `BOT_SERVICE_URL`: the handler
discovers bot pods itself. `GET /bot-pods` shows what it can see.

## How dispatch works

Bot pods take one meeting at a time and advertise that by failing their
readiness probe. The handler lists the pods behind the bot Deployment, probes
each one, and joins on the first that accepts — retrying past any pod claimed by
someone else in between. From then on, every command for that session goes to
that same pod, because only that pod is running the meeting.

Details, RBAC and troubleshooting: [docs/KUBERNETES.md](docs/KUBERNETES.md).

## Documentation

| | |
|---|---|
| [docs/API.md](docs/API.md) | Endpoints, error codes, typical flow |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, ownership, current limitations |
| [docs/KUBERNETES.md](docs/KUBERNETES.md) | Pod discovery, deployment, debugging |
| `/docs` | Generated OpenAPI reference |

## Development

```bash
conda activate meeting-bot
make test     # 66 tests, no cluster or bot required
make lint
```

Tests fake the Kubernetes API and serve the bot contract over an httpx mock
transport, so the full dispatch path — including busy pods, join races and
unreachable pods — is exercised offline.

## Status

Session state is held in memory: it does not survive a restart, and the handler
must run as a single replica until a PostgreSQL repository replaces
`InMemorySessionRepository`. See the limitations section in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
