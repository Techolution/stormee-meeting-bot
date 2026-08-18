#!/usr/bin/env bash

set -euo pipefail

REPO_NAME="${1:-meeting-bot-handler}"

echo "Creating repository: ${REPO_NAME}"

if [[ -e "${REPO_NAME}" ]]; then
  echo "Error: ${REPO_NAME} already exists."
  exit 1
fi

mkdir -p "${REPO_NAME}"
cd "${REPO_NAME}"

# -------------------------------------------------------------------
# Application source
# -------------------------------------------------------------------

mkdir -p app/api/routes
mkdir -p app/application
mkdir -p app/domain
mkdir -p app/kubernetes
mkdir -p app/bot
mkdir -p app/repositories
mkdir -p app/clients
mkdir -p app/runtime
mkdir -p app/schemas
mkdir -p app/core

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

mkdir -p tests/unit/api
mkdir -p tests/unit/application
mkdir -p tests/unit/domain
mkdir -p tests/unit/kubernetes
mkdir -p tests/unit/bot
mkdir -p tests/unit/repositories
mkdir -p tests/unit/clients
mkdir -p tests/unit/runtime

mkdir -p tests/integration

# -------------------------------------------------------------------
# Deployment
# -------------------------------------------------------------------

mkdir -p deploy/k8s

# -------------------------------------------------------------------
# Documentation
# -------------------------------------------------------------------

mkdir -p docs/adr

# -------------------------------------------------------------------
# Migrations
# -------------------------------------------------------------------

mkdir -p migrations

# -------------------------------------------------------------------
# Python package files
# -------------------------------------------------------------------

touch app/__init__.py

touch app/api/__init__.py
touch app/api/routes/__init__.py

touch app/application/__init__.py
touch app/domain/__init__.py
touch app/kubernetes/__init__.py
touch app/bot/__init__.py
touch app/repositories/__init__.py
touch app/clients/__init__.py
touch app/runtime/__init__.py
touch app/schemas/__init__.py
touch app/core/__init__.py

# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------

cat > app/api/routes/health.py <<'EOF'
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    return {"status": "ready"}
EOF

cat > app/api/routes/bot.py <<'EOF'
from fastapi import APIRouter

router = APIRouter(
    prefix="/bot-sessions",
    tags=["bot-sessions"],
)
EOF

cat > app/api/routes/commands.py <<'EOF'
from fastapi import APIRouter

router = APIRouter(
    prefix="/bot-sessions",
    tags=["commands"],
)
EOF

cat > app/api/routes/status.py <<'EOF'
from fastapi import APIRouter

router = APIRouter(
    prefix="/bot-sessions",
    tags=["status"],
)
EOF

cat > app/api/dependencies.py <<'EOF'
"""
FastAPI dependency definitions.

Dependencies will be wired in bootstrap.py.
"""
EOF

cat > app/api/errors.py <<'EOF'
"""
HTTP/API error handling.
"""
EOF

cat > app/api/middleware.py <<'EOF'
"""
Application middleware.
"""
EOF

# -------------------------------------------------------------------
# Application layer
# -------------------------------------------------------------------

cat > app/application/bot_handler.py <<'EOF'
"""
Main application orchestrator for Bot sessions.

This module owns workflow orchestration only.

It must not contain:
- Playwright logic
- Google Meet implementation
- recording implementation
- transcription implementation
- WebSocket implementation
- direct Kubernetes API details
"""

from __future__ import annotations


class BotHandler:
    """Orchestrates the lifecycle of one Bot session."""

    async def start_bot(self, session_id: str) -> None:
        raise NotImplementedError

    async def start_recording(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop_recording(self, session_id: str) -> None:
        raise NotImplementedError

    async def start_transcription(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop_transcription(self, session_id: str) -> None:
        raise NotImplementedError

    async def leave(self, session_id: str) -> None:
        raise NotImplementedError

    async def stop(self, session_id: str) -> None:
        raise NotImplementedError

    async def get_status(self, session_id: str):
        raise NotImplementedError
EOF

cat > app/application/command_handler.py <<'EOF'
"""
Command orchestration.

This module may be used when command processing becomes complex.
"""
EOF

cat > app/application/lifecycle_service.py <<'EOF'
"""
Bot session lifecycle orchestration.

Responsible for high-level lifecycle transitions, not Kubernetes details.
"""
EOF

# -------------------------------------------------------------------
# Domain
# -------------------------------------------------------------------

cat > app/domain/enums.py <<'EOF'
from enum import StrEnum


class BotSessionStatus(StrEnum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
EOF

cat > app/domain/models.py <<'EOF'
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import BotSessionStatus


@dataclass
class BotSession:
    session_id: str
    meeting_id: str
    status: BotSessionStatus

    k8s_job_name: str | None = None
    k8s_service_name: str | None = None
    k8s_namespace: str | None = None

    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    failed_at: datetime | None = None
    updated_at: datetime | None = None
EOF

cat > app/domain/exceptions.py <<'EOF'
class DomainError(Exception):
    """Base domain exception."""


class InvalidStateTransition(DomainError):
    """Raised when a bot session state transition is invalid."""


class BotSessionNotFound(DomainError):
    """Raised when a requested bot session does not exist."""
EOF

# -------------------------------------------------------------------
# Kubernetes
# -------------------------------------------------------------------

cat > app/kubernetes/client.py <<'EOF'
"""
Kubernetes API client wrapper.

Keep all Kubernetes client-library interaction behind this module.
"""
EOF

cat > app/kubernetes/job_manager.py <<'EOF'
"""
Kubernetes Job lifecycle management.
"""


class KubernetesJobManager:
    async def create_job(self, *args, **kwargs):
        raise NotImplementedError

    async def get_job(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_job(self, *args, **kwargs):
        raise NotImplementedError

    async def get_job_status(self, *args, **kwargs):
        raise NotImplementedError
EOF

cat > app/kubernetes/service_manager.py <<'EOF'
"""
Kubernetes Service lifecycle management.

One Bot session should have a stable internal endpoint rather than
routing commands directly to a Pod IP.
"""


class KubernetesServiceManager:
    async def create_service(self, *args, **kwargs):
        raise NotImplementedError

    async def get_service(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_service(self, *args, **kwargs):
        raise NotImplementedError
EOF

cat > app/kubernetes/watcher.py <<'EOF'
"""
Kubernetes Job/Pod watcher.

Used to detect unexpected Bot termination or Job failure.
"""
EOF

# -------------------------------------------------------------------
# Bot client
# -------------------------------------------------------------------

cat > app/bot/client.py <<'EOF'
"""
HTTP client for communicating with an individual meeting-bot instance.

The handler talks to the Bot through this client.
It must not contain Kubernetes logic.
"""


class BotClient:
    async def health(self, base_url: str):
        raise NotImplementedError

    async def get_status(self, base_url: str):
        raise NotImplementedError

    async def start_recording(self, base_url: str):
        raise NotImplementedError

    async def stop_recording(self, base_url: str):
        raise NotImplementedError

    async def start_transcription(self, base_url: str):
        raise NotImplementedError

    async def stop_transcription(self, base_url: str):
        raise NotImplementedError

    async def leave(self, base_url: str):
        raise NotImplementedError
EOF

cat > app/bot/models.py <<'EOF'
"""
Models representing Bot responses/events.
"""
EOF

# -------------------------------------------------------------------
# Repositories
# -------------------------------------------------------------------

cat > app/repositories/session_repository.py <<'EOF'
"""
Durable Bot session persistence.

This repository owns DB access for bot_sessions.
"""


class SessionRepository:
    async def create(self, session):
        raise NotImplementedError

    async def get_by_session_id(self, session_id: str):
        raise NotImplementedError

    async def update(self, session):
        raise NotImplementedError
EOF

cat > app/repositories/redis_repository.py <<'EOF'
"""
Redis access for ephemeral Bot runtime/heartbeat information.

Redis must not become the durable source of truth for Bot sessions.
"""


class RedisRepository:
    async def get_heartbeat(self, session_id: str):
        raise NotImplementedError

    async def set_heartbeat(self, session_id: str, value):
        raise NotImplementedError

    async def delete_heartbeat(self, session_id: str):
        raise NotImplementedError
EOF

# -------------------------------------------------------------------
# External clients
# -------------------------------------------------------------------

cat > app/clients/meeting_api.py <<'EOF'
"""
Client used by the Bot Handler to communicate with Meeting API.
"""


class MeetingApiClient:
    async def report_event(self, session_id: str, event: str, payload=None):
        raise NotImplementedError

    async def report_error(self, session_id: str, error: str):
        raise NotImplementedError
EOF

# -------------------------------------------------------------------
# Runtime
# -------------------------------------------------------------------

cat > app/runtime/locks.py <<'EOF'
"""
Concurrency primitives for Bot session operations.

Used to prevent races such as:
- start_recording + start_recording
- leave + start_recording
- stop + leave
"""
EOF

# -------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------

cat > app/schemas/bot.py <<'EOF'
from pydantic import BaseModel


class CreateBotSessionRequest(BaseModel):
    session_id: str
    meeting_id: str
    meeting_url: str


class CreateBotSessionResponse(BaseModel):
    session_id: str
    status: str
EOF

cat > app/schemas/commands.py <<'EOF'
from pydantic import BaseModel


class CommandResponse(BaseModel):
    session_id: str
    command: str
    status: str
EOF

cat > app/schemas/status.py <<'EOF'
from pydantic import BaseModel


class BotStatusResponse(BaseModel):
    session_id: str
    status: str
    healthy: bool | None = None
EOF

# -------------------------------------------------------------------
# Core
# -------------------------------------------------------------------

cat > app/core/config.py <<'EOF'
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "meeting-bot-handler"
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    redis_url: str = "redis://localhost:6379/0"

    kubernetes_namespace: str = "meeting-bots"

    bot_image: str = "meeting-bot:latest"

    meeting_api_url: str = "http://meeting-api:8000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
EOF

cat > app/core/logging.py <<'EOF'
"""
Application logging configuration.
"""
EOF

# -------------------------------------------------------------------
# Bootstrap
# -------------------------------------------------------------------

cat > app/bootstrap.py <<'EOF'
"""
Application dependency wiring.

This is where concrete implementations will be constructed and injected.
"""

from app.application.bot_handler import BotHandler


def create_bot_handler() -> BotHandler:
    # Dependency wiring will be implemented in later phases.
    return BotHandler()
EOF

# -------------------------------------------------------------------
# FastAPI entry point
# -------------------------------------------------------------------

cat > app/main.py <<'EOF'
from fastapi import FastAPI

from app.api.routes import bot, commands, health, status

app = FastAPI(
    title="Meeting Bot Handler",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(bot.router)
app.include_router(commands.router)
app.include_router(status.router)


@app.get("/")
async def root():
    return {
        "service": "meeting-bot-handler",
        "status": "ok",
    }
EOF

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

touch tests/__init__.py
touch tests/integration/__init__.py

for dir in \
  tests/unit/api \
  tests/unit/application \
  tests/unit/domain \
  tests/unit/kubernetes \
  tests/unit/bot \
  tests/unit/repositories \
  tests/unit/clients \
  tests/unit/runtime
do
  touch "${dir}/__init__.py"
done

cat > tests/conftest.py <<'EOF'
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
EOF

cat > tests/unit/api/test_health.py <<'EOF'
def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
EOF

# -------------------------------------------------------------------
# Documentation
# -------------------------------------------------------------------

cat > docs/ARCHITECTURE.md <<'EOF'
# Meeting Bot Handler Architecture

The Meeting Bot Handler is the control-plane service responsible for:

- Bot session lifecycle
- Kubernetes Job creation
- Kubernetes Service creation
- session-to-workload mapping
- routing commands to Bot Pods
- Bot health monitoring
- Kubernetes Job/Pod monitoring
- Meeting API callbacks

It does NOT implement:

- Google Meet automation
- Playwright
- recording
- transcription
- WebSocket/audio processing

Those responsibilities belong to the `meeting-bot` repository.
EOF

cat > docs/API.md <<'EOF'
# API

Planned endpoints:

## Bot sessions

POST /bot-sessions
GET /bot-sessions/{session_id}

## Commands

POST /bot-sessions/{session_id}/recording/start
POST /bot-sessions/{session_id}/recording/stop

POST /bot-sessions/{session_id}/transcription/start
POST /bot-sessions/{session_id}/transcription/stop

POST /bot-sessions/{session_id}/leave
POST /bot-sessions/{session_id}/stop

## Bot events

POST /bot-sessions/{session_id}/events

## Health

GET /health
GET /ready
EOF

cat > docs/KUBERNETES.md <<'EOF'
# Kubernetes

The Handler creates one Kubernetes Job for each Bot session.

Each Bot session should also have a stable Kubernetes Service.

Do not persist or use Pod IP as the primary Bot routing mechanism.

Conceptually:

Meeting API
    |
    v
Bot Handler
    |
    +-- Kubernetes Job
    |
    +-- Kubernetes Service
             |
             v
          Bot Pod
EOF

cat > docs/adr/0001-control-plane.md <<'EOF'
# ADR 0001: Bot Handler as Control Plane

The meeting-bot-handler is a control-plane service.

The existing meeting-bot repository remains responsible for actual
meeting execution.

The Handler owns Kubernetes lifecycle and command routing.
EOF

# -------------------------------------------------------------------
# Deployment
# -------------------------------------------------------------------

cat > deploy/k8s/deployment.yaml <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: meeting-bot-handler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: meeting-bot-handler
  template:
    metadata:
      labels:
        app: meeting-bot-handler
    spec:
      serviceAccountName: meeting-bot-handler
      containers:
        - name: meeting-bot-handler
          image: meeting-bot-handler:latest
          ports:
            - containerPort: 8000
          env:
            - name: KUBERNETES_NAMESPACE
              value: meeting-bots
EOF

cat > deploy/k8s/service.yaml <<'EOF'
apiVersion: v1
kind: Service
metadata:
  name: meeting-bot-handler
spec:
  selector:
    app: meeting-bot-handler
  ports:
    - port: 80
      targetPort: 8000
EOF

cat > deploy/k8s/serviceaccount.yaml <<'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: meeting-bot-handler
EOF

cat > deploy/k8s/configmap.yaml <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: meeting-bot-handler
data:
  KUBERNETES_NAMESPACE: meeting-bots
  BOT_IMAGE: meeting-bot:latest
EOF

# -------------------------------------------------------------------
# Docker
# -------------------------------------------------------------------

cat > Dockerfile <<'EOF'
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

# -------------------------------------------------------------------
# Dependencies
# -------------------------------------------------------------------

cat > requirements.txt <<'EOF'
fastapi
uvicorn[standard]
pydantic
pydantic-settings
httpx
redis
kubernetes
pytest
pytest-asyncio
EOF

# -------------------------------------------------------------------
# Environment
# -------------------------------------------------------------------

cat > .env.example <<'EOF'
ENVIRONMENT=development

HOST=0.0.0.0
PORT=8000

REDIS_URL=redis://localhost:6379/0

KUBERNETES_NAMESPACE=meeting-bots

BOT_IMAGE=meeting-bot:latest

MEETING_API_URL=http://localhost:8001
EOF

# -------------------------------------------------------------------
# Git
# -------------------------------------------------------------------

cat > .gitignore <<'EOF'
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

.venv/
venv/
.env

*.log

.DS_Store

.idea/
.vscode/

dist/
build/
*.egg-info/
EOF

# -------------------------------------------------------------------
# pyproject
# -------------------------------------------------------------------

cat > pyproject.toml <<'EOF'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "meeting-bot-handler"
version = "0.1.0"
description = "Kubernetes control-plane service for meeting bot sessions"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
EOF

# -------------------------------------------------------------------
# Makefile
# -------------------------------------------------------------------

cat > Makefile <<'EOF'
.PHONY: install run test lint format

install:
	python -m pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

lint:
	python -m compileall app

format:
	python -m compileall app
EOF

# -------------------------------------------------------------------
# README
# -------------------------------------------------------------------

cat > README.md <<'EOF'
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