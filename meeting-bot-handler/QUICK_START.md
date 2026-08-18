# Meeting Bot Handler - Quick Start

## Prerequisites

- Python 3.12+
- Running Meeting Bot service (on localhost:8000 or configured via `BOT_SERVICE_URL`)
- pip/poetry for dependency management

## Installation

```bash
cd meeting-bot-handler
pip install -r requirements.txt
```

## Running Locally

### Option 1: Default Configuration (Bot on localhost:8000)

```bash
python -m uvicorn app.main:app --reload --port 8001
```

The handler will look for the bot service at `http://localhost:8000`.

### Option 2: Custom Bot Service URL

```bash
BOT_SERVICE_URL=http://meeting-bot:9000 \
  python -m uvicorn app.main:app --reload --port 8001
```

## Quick Test

Once running, test the API with curl:

```bash
# Check if handler is up
curl http://localhost:8001/

# Check health
curl http://localhost:8001/health

# Start a session (assumes bot service is running)
curl -X POST http://localhost:8001/bot-sessions/my-meeting-123/start

# Start recording
curl -X POST http://localhost:8001/bot-sessions/my-meeting-123/recording/start

# Check status
curl http://localhost:8001/bot-sessions/my-meeting-123/status

# Stop recording
curl -X POST http://localhost:8001/bot-sessions/my-meeting-123/recording/stop

# Leave session
curl -X POST http://localhost:8001/bot-sessions/my-meeting-123/leave
```

## API Endpoints Overview

All endpoints operate on `/bot-sessions/{session_id}`:

| Method | Endpoint | Purpose |
|--------|----------|----------|
| POST | `/bot-sessions/{session_id}/start` | Join meeting |
| POST | `/bot-sessions/{session_id}/recording/start` | Start recording |
| POST | `/bot-sessions/{session_id}/recording/stop` | Stop recording |
| POST | `/bot-sessions/{session_id}/transcription/start` | Start transcription |
| POST | `/bot-sessions/{session_id}/transcription/stop` | Stop transcription |
| POST | `/bot-sessions/{session_id}/leave` | Leave meeting |
| POST | `/bot-sessions/{session_id}/stop` | Stop session |
| GET | `/bot-sessions/{session_id}/status` | Get status |

## Running Tests

### Unit Tests

```bash
python -m pytest tests/unit/application/test_bot_handler.py -v
```

### Integration Tests

```bash
python -m pytest tests/integration/test_bot_session_flow.py -v
```

### All Tests

```bash
python -m pytest tests/ -v
```

## Docker

### Build

```bash
docker build -t meeting-bot-handler:latest .
```

### Run

```bash
docker run -e BOT_SERVICE_URL=http://meeting-bot:8000 \
           -p 8001:8000 \
           meeting-bot-handler:latest
```

## Troubleshooting

### Connection Refused

**Problem**: `Connection refused` when calling endpoints

**Solution**: Ensure the Meeting Bot service is running and the `BOT_SERVICE_URL` is correct:

```bash
# Check default URL
curl http://localhost:8000/health

# If bot is on different host/port, set BOT_SERVICE_URL:
BOT_SERVICE_URL=http://your-bot-host:8000 \
  python -m uvicorn app.main:app --reload --port 8001
```

### 500 Internal Server Error

**Problem**: Endpoints return HTTP 500 errors

**Possible causes**:
1. Bot service is not running
2. BOT_SERVICE_URL is incorrect
3. Session ID format doesn't match bot service expectations
4. Bot service is returning an error

**Solution**: Check the error message in the response:

```bash
curl -X POST http://localhost:8001/bot-sessions/test-123/start 2>&1 | jq '.detail'
```

### Import Errors

**Problem**: `ModuleNotFoundError` when running

**Solution**: Ensure dependencies are installed:

```bash
pip install -r requirements.txt
```

## Next Steps

1. Read [INTEGRATION.md](./INTEGRATION.md) for detailed architecture and deployment guide
2. Run integration tests to verify end-to-end functionality
3. Deploy to your infrastructure (Docker, Kubernetes, etc.)
4. Monitor health via `/health` and `/ready` endpoints

## Documentation

- **[INTEGRATION.md](./INTEGRATION.md)** - Detailed integration guide, architecture, and deployment
- **[README.md](./README.md)** - Project overview
- **[API Routes](./app/api/routes/bot.py)** - Endpoint implementations with docstrings
- **[Bot Handler](./app/application/bot_handler.py)** - Core HTTP client implementation

## Support

For issues or questions, refer to:
- Error messages from HTTP responses
- Test files for usage examples
- Integration guide for deployment help

