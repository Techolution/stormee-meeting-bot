# Meeting Bot Handler - Architecture

## Overview

The Meeting Bot Handler service is designed with clear separation of concerns:

```
┌─────────────┐
│  HTTP Route │
│ (FastAPI)   │
└──────┬──────┘
       │
       v
┌──────────────────────┐
│   BotHandler         │
│  (Orchestration)     │
└──────┬───────────────┘
       │
       v
┌──────────────────────┐
│   BotClient          │
│  (HTTP Comm)         │
└──────┬───────────────┘
       │
       v
┌──────────────────────┐
│   httpx              │
│  (HTTP Library)      │
└──────┬───────────────┘
       │
       v
┌──────────────────────┐
│   meeting-bot API    │
│  (External Service)  │
└──────────────────────┘
```

## Core Components

### 1. BotClient (`app/application/bot_client.py`)

**Responsibility**: All HTTP communication with the Meeting Bot service.

**Knows about**:
- HTTP endpoints and methods (GET, POST, etc.)
- Request URLs (e.g., `POST /meetings/join`)
- Request payloads (e.g., `{"meetingId": "..."}`)
- Timeouts and connection settings
- HTTP error handling and status codes
- Response parsing (JSON, etc.)

**Does NOT know about**:
- Business logic or state
- Orchestration decisions
- Database access
- Kubernetes or service discovery
- Application-level events or state transitions

**Methods**:
```python
class BotClient:
    async def join_meeting(self, meeting_id: str) -> dict
    async def start_recording(self, meeting_id: str) -> dict
    async def stop_recording(self, meeting_id: str) -> dict
    async def start_transcription(self, meeting_id: str) -> dict
    async def stop_transcription(self, meeting_id: str) -> dict
    async def leave_meeting(self, meeting_id: str) -> dict
    async def get_meeting_status(self, meeting_id: str) -> dict
```

Each method:
1. Constructs the correct URL from `self.service_url`
2. Builds the required request payload
3. Makes the HTTP request via `self._http_client`
4. Calls `response.raise_for_status()` for error checking
5. Returns the parsed JSON response

### 2. BotHandler (`app/application/bot_handler.py`)

**Responsibility**: Session lifecycle orchestration and business logic.

**Knows about**:
- Session lifecycle states (starting, recording, transcribing, etc.)
- Validation rules for operations
- Business logic flow (e.g., ensure recording stopped before leaving)
- State tracking and persistence (future)
- Event emission (future)
- Application-level error handling

**Does NOT know about**:
- HTTP endpoints, URLs, or methods
- httpx or HTTP implementation details
- Request payloads or response parsing
- Timeouts or connection details

**Methods**:
```python
class BotHandler:
    async def start_bot(self, session_id: str) -> dict
    async def start_recording(self, session_id: str) -> dict
    async def stop_recording(self, session_id: str) -> dict
    async def start_transcription(self, session_id: str) -> dict
    async def stop_transcription(self, session_id: str) -> dict
    async def leave(self, session_id: str) -> dict
    async def stop(self, session_id: str) -> dict
    async def get_status(self, session_id: str) -> dict
```

Each method follows this pattern:
```python
async def operation(self, session_id: str) -> dict:
    # 1. Validate/prepare operation
    # TODO: validation logic
    
    # 2. Call BotClient
    result = await self.bot_client.appropriate_method(session_id)
    
    # 3. Process result
    # TODO: update state, emit events, etc.
    
    return result
```

### 3. API Routes (`app/api/routes/bot.py`)

**Responsibility**: HTTP interface to the handler.

Routes expose BotHandler methods as HTTP endpoints:
```
POST   /bot-sessions/{session_id}/start
POST   /bot-sessions/{session_id}/recording/start
POST   /bot-sessions/{session_id}/recording/stop
POST   /bot-sessions/{session_id}/transcription/start
POST   /bot-sessions/{session_id}/transcription/stop
POST   /bot-sessions/{session_id}/leave
POST   /bot-sessions/{session_id}/stop
GET    /bot-sessions/{session_id}/status
```

Each route:
1. Uses FastAPI dependency injection to get BotHandler instance
2. Calls the appropriate handler method
3. Converts exceptions to HTTP error responses
4. Returns JSON response

## Design Rules

### Separation of Concerns

**Simple Rule**: 
> If a line of code knows an HTTP endpoint, method, URL, request body, timeout, or httpx response, it belongs in **BotClient**.
> If a line decides what should happen in the meeting/bot lifecycle, it belongs in **BotHandler**.

### Dependency Flow

```
API Routes
    ↓
BotHandler (depends on)
    ↓
BotClient (depends on)
    ↓
httpx
```

Never reverse this direction:
- ❌ BotClient should NOT import from BotHandler
- ❌ BotHandler should NOT contain httpx code
- ❌ Routes should NOT make direct httpx calls

### Testing Strategy

#### BotClient Tests (`test_bot_client.py`)
- Mock httpx responses
- Verify URL construction
- Verify request payloads
- Verify response parsing
- Test HTTP error handling
- NO business logic tests

#### BotHandler Tests (`test_bot_handler.py`)
- Mock BotClient
- Verify correct BotClient method is called
- Verify results are returned
- Verify exceptions are propagated
- NO HTTP detail tests

#### Integration Tests (`test_bot_session_flow.py`)
- Mock BotHandler or full integration with real services
- Verify end-to-end flows
- Verify API route handling

## Configuration

### Environment Variables

- `BOT_SERVICE_URL`: Base URL of the bot service (default: `http://localhost:8000`)
  - Set once in BotClient initialization
  - No other component concerns itself with this

## Future Enhancements

The clean separation enables easy addition of:

### In BotHandler (without touching BotClient)
- ✅ Session state validation
- ✅ Event emission
- ✅ Database persistence
- ✅ Retry logic at the orchestration level
- ✅ Custom error handling per operation

### In BotClient (without touching BotHandler)
- ✅ Retry/exponential backoff
- ✅ Circuit breaker pattern
- ✅ Connection pooling
- ✅ Additional request headers (authentication, tracing)
- ✅ Response caching
- ✅ Metrics collection

### New Layers
- ✅ SessionRepository (state persistence)
- ✅ EventBus (asynchronous notifications)
- ✅ SessionValidator (pre-operation validation)

## Import Structure

```
app/
├── api/
│   └── routes/
│       └── bot.py          # imports BotHandler
├── application/
│   ├── bot_client.py       # No internal imports (only httpx, os)
│   └── bot_handler.py      # imports BotClient
├── bootstrap.py            # imports both, creates instances
└── main.py                 # imports routes
```

## Example: Adding Session Validation

With the current architecture, adding validation is straightforward:

```python
# In BotHandler.start_recording()
async def start_recording(self, session_id: str) -> dict:
    # NEW: Validate session exists and is in correct state
    if session_id not in self._sessions:
        raise SessionNotFoundError(session_id)
    if self._sessions[session_id].state != "active":
        raise InvalidStateError("Session must be active")
    
    # Call BotClient (unchanged)
    result = await self.bot_client.start_recording(session_id)
    
    # NEW: Update session state
    self._sessions[session_id].recording = True
    
    return result

# BotClient remains completely unchanged!
```

## Example: Adding Exponential Backoff

With the current architecture, adding retry logic is simple:

```python
# In BotClient._make_request() helper (new)
async def _make_request_with_retry(self, method, url, **kwargs):
    """Make HTTP request with exponential backoff."""
    for attempt in range(3):
        try:
            response = await self._http_client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

# Update all methods to use _make_request_with_retry
# BotHandler remains completely unchanged!
```

## Conclusion

This architecture provides:
- ✅ Clear separation of concerns
- ✅ Testability (each layer can be tested independently)
- ✅ Maintainability (changes to one layer don't affect others)
- ✅ Extensibility (new features can be added without affecting existing code)
- ✅ Reusability (BotClient can be used in other services)

