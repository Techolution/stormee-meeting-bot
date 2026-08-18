# Meeting Bot Handler

Control-plane service responsible for managing meeting bot sessions.

## Responsibilities

- Create Kubernetes Jobs
- Create Kubernetes Services
- Track Bot sessions
- Route commands to Bot Pods
- Monitor Bot health
- Monitor Kubernetes workloads
- Report lifecycle events to Meeting API

## Non-responsibilities

The Handler does not implement:

- Google Meet automation
- Playwright
- recording
- transcription
- WebSocket/audio processing

Those responsibilities belong to the `meeting-bot` repository.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env

uvicorn app.main:app --reload
