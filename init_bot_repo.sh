#!/usr/bin/env bash

set -e

PROJECT_NAME="meeting-bot"

echo "Creating project structure: ${PROJECT_NAME}"

mkdir -p "$PROJECT_NAME"/app/{api/routes,meeting,browser,meeting_platform,recording,transcription,websocket,context,runtime,clients,core,schemas}
mkdir -p "$PROJECT_NAME"/tests/{meeting,browser,recording,transcription,websocket,clients}

# Application entry point
touch "$PROJECT_NAME"/app/main.py

# API
touch "$PROJECT_NAME"/app/api/__init__.py
touch "$PROJECT_NAME"/app/api/dependencies.py

touch "$PROJECT_NAME"/app/api/routes/__init__.py
touch "$PROJECT_NAME"/app/api/routes/health.py
touch "$PROJECT_NAME"/app/api/routes/status.py
touch "$PROJECT_NAME"/app/api/routes/meeting.py
touch "$PROJECT_NAME"/app/api/routes/recording.py
touch "$PROJECT_NAME"/app/api/routes/transcription.py

# Meeting
touch "$PROJECT_NAME"/app/meeting/__init__.py
touch "$PROJECT_NAME"/app/meeting/meeting_manager.py
touch "$PROJECT_NAME"/app/meeting/meeting_session.py
touch "$PROJECT_NAME"/app/meeting/lifecycle.py
touch "$PROJECT_NAME"/app/meeting/models.py

# Browser
touch "$PROJECT_NAME"/app/browser/__init__.py
touch "$PROJECT_NAME"/app/browser/browser.py
touch "$PROJECT_NAME"/app/browser/browser_manager.py
touch "$PROJECT_NAME"/app/browser/models.py

# Meeting platform / Google Meet
touch "$PROJECT_NAME"/app/meeting_platform/__init__.py
touch "$PROJECT_NAME"/app/meeting_platform/base.py
touch "$PROJECT_NAME"/app/meeting_platform/google_meet.py
touch "$PROJECT_NAME"/app/meeting_platform/actions.py

# Recording
touch "$PROJECT_NAME"/app/recording/__init__.py
touch "$PROJECT_NAME"/app/recording/recorder.py
touch "$PROJECT_NAME"/app/recording/audio_capture.py
touch "$PROJECT_NAME"/app/recording/chunk_uploader.py
touch "$PROJECT_NAME"/app/recording/models.py

# Transcription
touch "$PROJECT_NAME"/app/transcription/__init__.py
touch "$PROJECT_NAME"/app/transcription/base.py
touch "$PROJECT_NAME"/app/transcription/provider.py
touch "$PROJECT_NAME"/app/transcription/caption_provider.py
touch "$PROJECT_NAME"/app/transcription/models.py

# WebSocket client
touch "$PROJECT_NAME"/app/websocket/__init__.py
touch "$PROJECT_NAME"/app/websocket/client.py
touch "$PROJECT_NAME"/app/websocket/connection_manager.py
touch "$PROJECT_NAME"/app/websocket/event_handler.py
touch "$PROJECT_NAME"/app/websocket/models.py

# Context buffer
touch "$PROJECT_NAME"/app/context/__init__.py
touch "$PROJECT_NAME"/app/context/buffer.py
touch "$PROJECT_NAME"/app/context/models.py

# Runtime
touch "$PROJECT_NAME"/app/runtime/__init__.py
touch "$PROJECT_NAME"/app/runtime/state.py
touch "$PROJECT_NAME"/app/runtime/session.py
touch "$PROJECT_NAME"/app/runtime/heartbeat.py

# External clients
touch "$PROJECT_NAME"/app/clients/__init__.py
touch "$PROJECT_NAME"/app/clients/meeting_api.py
touch "$PROJECT_NAME"/app/clients/cw_utils.py
touch "$PROJECT_NAME"/app/clients/audio_service.py

# Core
touch "$PROJECT_NAME"/app/core/__init__.py
touch "$PROJECT_NAME"/app/core/config.py
touch "$PROJECT_NAME"/app/core/logging.py
touch "$PROJECT_NAME"/app/core/request_context.py
touch "$PROJECT_NAME"/app/core/timers.py
touch "$PROJECT_NAME"/app/core/exceptions.py
touch "$PROJECT_NAME"/app/core/dependencies.py

# Schemas
touch "$PROJECT_NAME"/app/schemas/__init__.py
touch "$PROJECT_NAME"/app/schemas/meeting.py
touch "$PROJECT_NAME"/app/schemas/recording.py
touch "$PROJECT_NAME"/app/schemas/transcription.py
touch "$PROJECT_NAME"/app/schemas/websocket.py

# Tests
touch "$PROJECT_NAME"/tests/__init__.py
touch "$PROJECT_NAME"/tests/meeting/__init__.py
touch "$PROJECT_NAME"/tests/browser/__init__.py
touch "$PROJECT_NAME"/tests/recording/__init__.py
touch "$PROJECT_NAME"/tests/transcription/__init__.py
touch "$PROJECT_NAME"/tests/websocket/__init__.py
touch "$PROJECT_NAME"/tests/clients/__init__.py

# Project-level files
touch "$PROJECT_NAME"/Dockerfile
touch "$PROJECT_NAME"/requirements.txt
touch "$PROJECT_NAME"/README.md
touch "$PROJECT_NAME"/.gitignore

echo ""
echo "Project structure created successfully."
echo ""

# Print structure if tree is installed
if command -v tree >/dev/null 2>&1; then
    tree "$PROJECT_NAME"
else
    find "$PROJECT_NAME" -print | sort
fi