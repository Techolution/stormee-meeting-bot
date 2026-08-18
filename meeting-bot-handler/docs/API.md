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
