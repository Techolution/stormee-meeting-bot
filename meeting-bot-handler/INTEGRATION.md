# Meeting Bot Handler - Integration Guide

## Overview

The Meeting Bot Handler service provides HTTP APIs to control the lifecycle of bot sessions in meetings. It acts as a bridge between external clients and the Meeting Bot service.

## Architecture

### Components

1. **BotHandler** (`app/application/bot_handler.py`)
   - Orchestrates bot session lifecycle
   - Makes HTTP calls to the Meeting Bot service
   - Handles async operations with proper error handling

2. **API Routes** (`app/api/routes/bot.py`)
   - Exposes HTTP endpoints for session control
   - Manages dependency injection via FastAPI
   - Converts exceptions to HTTP responses

3. **Bootstrap** (`app/bootstrap.py`)
   - Creates and configures service dependencies
   - Currently implements BotHandler factory

## Configuration

### Environment Variables

- `BOT_SERVICE_URL` (default: `http://localhost:8000`)
  - The base URL of the Meeting Bot service
  - Used by BotHandler to construct API endpoint URLs
  - Should point to your meeting-bot service (e.g., `http://meeting-bot:8000` in Kubernetes)

## API Endpoints

All endpoints use the `/bot-sessions/{session_id}` prefix.

### Session Management

#### Start Session (Join Meeting)
```
POST /bot-sessions/{session_id}/start
Status: 202 Accepted
Response: {"message": "Session started successfully", "session_id": "..."}
```
Starts a bot session by having the bot join a meeting.

#### Leave Session
```
POST /bot-sessions/{session_id}/leave
Status: 200 OK
Response: {"message": "Session left successfully", "session_id": "..."}
```
Ends a bot session by having the bot leave the meeting.

#### Stop Session
```
POST /bot-sessions/{session_id}/stop
Status: 200 OK
Response: {"message": "Session stopped successfully", "session_id": "..."}
```
Stops a bot session (equivalent to leaving).

### Recording Control

#### Start Recording
```
POST /bot-sessions/{session_id}/recording/start
Status: 202 Accepted
Response: {"message": "Recording started successfully", "session_id": "..."}
```
Begins capturing the meeting's audio.

#### Stop Recording
```
POST /bot-sessions/{session_id}/recording/stop
Status: 200 OK
Response: {"message": "Recording stopped successfully", "session_id": "..."}
```
Stops audio capture and finalizes the recording.

### Transcription Control

#### Start Transcription
```
POST /bot-sessions/{session_id}/transcription/start
Status: 202 Accepted
Response: {"message": "Transcription started successfully", "session_id": "..."}
```
Begins producing a transcript of the meeting.

#### Stop Transcription
```
POST /bot-sessions/{session_id}/transcription/stop
Status: 200 OK
Response: {"message": "Transcription stopped successfully", "session_id": "..."}
```
Stops transcription.

### Status Monitoring

#### Get Session Status
```
GET /bot-sessions/{session_id}/status
Status: 200 OK
Response: {
  "session_id": "...",
  "status": {
    "meeting_id": "...",
    "status": "active",
    "recording": "recording",
    ...
  }
}
```
Retrrieves the current status of a session from the bot service.

## Integration Guide

### 1. Running Locally

Start the Meeting Bot service first:
```bash
cd meeting-bot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then start the Meeting Bot Handler:
```bash
cd meeting-bot-handler
BOT_SERVICE_URL=http://localhost:8000 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 2. Testing End-to-End

Use the integration tests:
```bash
cd meeting-bot-handler
python -m pytest tests/integration/test_bot_session_flow.py -v
```

Or run unit tests:
```bash
python -m pytest tests/unit/application/test_bot_handler.py -v
```

### 3. Manual Testing with curl

```bash
# Start a session
curl -X POST http://localhost:8001/bot-sessions/meeting-123/start

# Start recording
curl -X POST http://localhost:8001/bot-sessions/meeting-123/recording/start

# Check status
curl -X GET http://localhost:8001/bot-sessions/meeting-123/status

# Stop recording
curl -X POST http://localhost:8001/bot-sessions/meeting-123/recording/stop

# Leave session
curl -X POST http://localhost:8001/bot-sessions/meeting-123/leave
```

## Request Flow

### Example: Start Recording

1. Client sends: `POST /bot-sessions/{session_id}/recording/start`
2. FastAPI route handler receives the request
3. Dependency injection provides BotHandler instance
4. Handler calls `await bot_handler.start_recording(session_id)`
5. BotHandler makes HTTP POST to `{BOT_SERVICE_URL}/recordings/start` with payload `{"meetingId": session_id}`
6. Bot service responds with success (HTTP 2xx) or error (HTTP 4xx/5xx)
7. Handler's `raise_for_status()` raises exception on error
8. FastAPI route catches exception and converts to HTTP 500
9. Response returned to client

## Error Handling

All endpoints return HTTP 500 with a descriptive error message if the operation fails:

```json
{
  "detail": "Failed to start recording: HTTPStatusError: 404 Not Found"
}
```

Common error scenarios:
- **Meeting not found**: Bot service returns 404
- **Already recording**: Bot service returns 400
- **Service unavailable**: HTTP connection timeout or 503
- **Internal error**: HTTPStatusError or generic exception

## Testing Strategy

### Unit Tests
- Test BotHandler methods in isolation
- Mock httpx responses
- Verify correct URL construction
- Verify correct payload structure
- Test error handling (4xx, 5xx, timeout)

### Integration Tests
- Test API endpoints through FastAPI
- Mock BotHandler to verify endpoint behavior
- Verify HTTP status codes
- Test full session lifecycle sequences

### End-to-End Tests (Manual)
- Run real bot service
- Make actual HTTP requests to handler
- Verify data flows correctly through the system

## Deployment

### Docker

Build:
```bash
cd meeting-bot-handler
docker build -t meeting-bot-handler:latest .
```

Run:
```bash
docker run -e BOT_SERVICE_URL=http://meeting-bot:8000 \
           -p 8001:8000 \
           meeting-bot-handler:latest
```

### Kubernetes

Set environment variable in deployment:
```yaml
env:
  - name: BOT_SERVICE_URL
    value: http://meeting-bot:8000
```

Service discovery example:
```yaml
env:
  - name: BOT_SERVICE_URL
    value: http://meeting-bot.meeting-bot-namespace.svc.cluster.local:8000
```

## Monitoring

### Health Checks

Use the provided health endpoints:
```bash
curl http://localhost:8001/health    # Simple health check
curl http://localhost:8001/ready     # Readiness check
```

### Status Monitoring

Monitor active sessions via status endpoint:
```bash
curl http://localhost:8001/bot-sessions/{session_id}/status
```

## Future Enhancements

1. **Session Persistence**: Store session state in database
2. **WebSocket Events**: Stream session events to clients
3. **Advanced Retry Logic**: Implement exponential backoff for failed requests
4. **Circuit Breaker**: Handle bot service unavailability gracefully
5. **Metrics and Tracing**: Add Prometheus metrics and OpenTelemetry tracing
6. **Rate Limiting**: Prevent abuse with request throttling
7. **Authentication**: Add API key or OAuth2 authentication

