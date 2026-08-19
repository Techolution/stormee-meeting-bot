# Recording Features Guide

This guide documents the enhanced recording features including meeting title-based naming, duration-based uploads, and incremental highlights generation.

## Table of Contents

1. [Meeting Title-Based Recording Names](#meeting-title-based-recording-names)
2. [Duration-Based Uploads](#duration-based-uploads)
3. [Incremental Highlights Generation](#incremental-highlights-generation)
4. [API Examples](#api-examples)
5. [Integration Guide](#integration-guide)

---

## Meeting Title-Based Recording Names

### Overview

Recording files are now named using the meeting title instead of the opaque meeting ID, making them more discoverable and user-friendly.

### Filename Format

```
<meeting_title>_<uuid>.webm
```

### Examples

- `Project Review_a1b2c3d4e5f6g7h8.webm`
- `Team Standup_x9y8z7w6v5u4t3s2.webm`
- `Client Presentation_m1n2o3p4q5r6s7t8.webm`

### Implementation Details

- **Title Truncation**: Meeting titles are truncated to 50 characters to prevent excessively long filenames
- **Character Sanitization**: Forward slashes `/`, colons `:`, and backslashes `\` are replaced with underscores `_`
- **Collision Prevention**: A UUID suffix ensures unique names even when the same meeting is recorded multiple times
- **Fallback**: If no meeting title is provided, the system falls back to using the meeting ID

### How to Use

When calling the meeting join API, provide a `meetingTitle` parameter:

```bash
curl -X POST http://localhost:8000/api/meetings/join \
  -H "Content-Type: application/json" \
  -d '{
    "meetingUrl": "https://meet.google.com/abc-def-ghi",
    "meetingTitle": "Quarterly Business Review",
    "projectId": "proj-123",
    "userName": "Bot User",
    "userEmail": "bot@example.com"
  }'
```

---

## Duration-Based Uploads

### Overview

Duration-based uploads enable incremental processing of long-running meetings. When you start recording, you can specify a maximum duration. The recording automatically uploads and generates highlights for that segment when the duration is reached, without stopping the meeting. You can then continue recording, which will upload the remaining audio when the meeting ends.

### Use Cases

1. **Long Meetings**: For meetings longer than 1-2 hours, breaking them into segments improves upload reliability
2. **Bandwidth Management**: Upload smaller segments individually rather than one large file
3. **Early Highlights**: Get highlights for the first 30 minutes while the meeting continues
4. **Incremental Processing**: Start processing/analyzing recordings while the meeting is still ongoing

### How to Use

#### Step 1: Start Recording with Segment Duration

```bash
# Start recording with auto-upload after 30 minutes (1800 seconds)
curl -X POST http://localhost:8000/api/recordings/start \
  -H "Content-Type: application/json" \
  -d '{
    "meetingId": "meet-abc-123",
    "maxDurationSeconds": 1800,
    "generateIncrementalHighlights": true
  }'
```

#### Step 2: Meeting Continues (Automatic Segment Upload)

Recording continues as normal. When the duration reaches 1800 seconds:
1. The first 30 minutes are automatically uploaded
2. Incremental highlights are generated for that segment ("Part 1")
3. Recording continues from that point onward

#### Step 3: Stop Recording at Meeting End

```bash
# Simply stop - remaining audio after last segment is uploaded
curl -X POST http://localhost:8000/api/recordings/stop \
  -H "Content-Type: application/json" \
  -d '{"meetingId": "meet-abc-123"}'
```

The remaining audio is automatically uploaded and highlights generated for the final segment.

### Request Fields

**StartRecordingRequest**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `meetingId` | string | Yes | The meeting identifier |
| `maxDurationSeconds` | integer | No | Automatically upload segment after this duration (in seconds). Omit for single upload at end. |
| `generateIncrementalHighlights` | boolean | No | Request highlights for each segment. Default: `false`. |

**StopRecordingRequest**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `meetingId` | string | Yes | The meeting identifier |

---

## Incremental Highlights Generation

### Overview

Incrementalhighlights enable generating meeting summaries and key points for each recorded segment, not just the complete meeting. This allows:

- Real-time insights from ongoing meetings
- Segmented action items and summaries
- Reduced latency for long meetings

### How It Works

1. **Duration Threshold**: Highlights are only generated when the segment duration exceeds a minimum threshold (default: 60 seconds)
2. **Incremental Increase**: Highlights are generated when duration increases by at least 50% from the previous segment
3. **Segment Labeling**: Each segment is labeled as "Part 1", "Part 2", etc.
4. **Request Correlation**: Each highlight request includes a `request_id` for tracking in the CW system

### Configuration

The HighlightsManager can be configured with custom thresholds:

```python
from app.recording.highlights_manager import HighlightsManager

highlights_manager = HighlightsManager(
    cw_client=cw_client,
    min_duration_seconds=120.0,  # Require 2 minutes minimum
)
```

### Threshold Logic

Highlights are generated when:
- `current_duration >= min_duration_seconds` AND
- `current_duration - last_processed_duration >= (min_duration_seconds * 0.5)`

**Example Timeline**:

```
Time  Duration  Action
----  --------  ------------------------------------------
0:00    0s      Recording starts
1:00   60s      Duration reached (>= 60s), but no prior
                process → Generate highlights for Part 1
               
1:45   45s+     1:45 total (90s recorded since start)
                Increase from Part 1 is only 30s (< 50%)
                → Skip highlights
               
2:20  80s+      2:20 total (140s since start)
                Increase from Part 1 is 80s (>= 50%)
                → Generate highlights for Part 2
```

### Response Tracking

Each highlight request returns a `request_id` for tracking:

```json
{
  "segment_id": "meet-abc-123-segment-1",
  "meeting_id": "meet-abc-123",
  "duration_seconds": 120.5,
  "request_id": "req-abc123def456",
  "generated_at": "2024-01-15T10:30:45.123456Z"
}
```

Use this `request_id` to correlate with CW's artifact generation response.

---

## API Examples

### Complete Example: Recording with Incremental Uploads

```bash
# 1. Join meeting with title
curl -X POST http://localhost:8000/api/meetings/join \
  -H "Content-Type: application/json" \
  -d '{
    "meetingUrl": "https://meet.google.com/abc-def-ghi",
    "meetingTitle": "Sprint Planning Meeting",
    "projectId": "proj-sprint-001",
    "userName": "Recording Bot",
    "userEmail": "bot@company.com"
  }' > response.json

MEETING_ID=$(jq -r '.meeting_id' response.json)

# 2. Start recording with automatic segment upload after 30 minutes
curl -X POST http://localhost:8000/api/recordings/start \
  -H "Content-Type: application/json" \
  -d "{
    \"meetingId\": \"$MEETING_ID\",
    \"maxDurationSeconds\": 1800,
    \"generateIncrementalHighlights\": true
  }"

# 3. Recording runs automatically. When 30 minutes is reached:
#    - First segment is automatically uploaded
#    - Highlights generated for Part 1
#    - Recording continues from that point
#
# If meeting lasts another 30 minutes, another segment is uploaded:
#    - Second segment (seconds 1800-3600) is uploaded
#    - Highlights generated for Part 2
#    - Recording continues

# 4. Stop recording when meeting ends (no params needed)
curl -X POST http://localhost:8000/api/recordings/stop \
  -H "Content-Type: application/json" \
  -d "{\"meetingId\": \"$MEETING_ID\"}"

# 5. Remaining audio is automatically uploaded and highlights generated
#    Example timeline for 1.5 hour meeting:
#    - 0:00-30:00 (1800s) → Uploaded immediately at 30:00 mark (Part 1)
#    - 30:00-90:00 (3600s) → Uploaded when meeting ends (Part 2)
```

### Checking Recording Status

```bash
curl -X GET http://localhost:8000/api/recordings/$MEETING_ID/status
```

Response:

```json
{
  "meetingId": "meet-abc-123",
  "status": "recording",
  "chunksCaptured": 1250,
  "chunksUploaded": 1248,
  "chunksPending": 2,
  "bytesUploaded": 5242880,
  "startedAt": "2024-01-15T10:00:00.000000Z",
  "stoppedAt": null,
  "transport": "websocket"
}
```

---

## Integration Guide

### Backend Integration

#### 1. Enable HighlightsManager

In your application factory/setup:

```python
from app.recording.highlights_manager import HighlightsManager

highlights_manager = HighlightsManager(
    cw_client=cw_client,
    min_duration_seconds=60.0,  # Adjust based on your needs
)

# Pass to session dependencies
session_deps = SessionDependencies(
    ...,
    highlights_manager=highlights_manager,
)
```

#### 2. Update UploadFinalizer

When creating the UploadFinalizer, pass the highlights manager:

```python
finalizer = UploadFinalizer(
    cw_client=cw_client,
    mail_client=mail_client,
    highlights_manager=highlights_manager,  # Optional
)
```

### Frontend Integration

If using the JavaScript SDK:

```javascript
// Start recording
await bot.startRecording(meetingId);

// Stop with duration-based upload
await bot.stopRecording({
  meetingId: meetingId,
  maxDurationSeconds: 1800,  // 30 minutes
  generateIncrementalHighlights: true,
});
```

### Monitoring and Observability

Watch for these log patterns to monitor incremental highlights:

```
"Generating incremental highlights" - Highlights generation started
"Incremental highlights requested" - Highlights request sent to CW
"Skipping highlights: insufficient duration" - Duration threshold not met
"Failed to request incremental highlights" - Highlights generation failed
```

---

## Best Practices

### Recommended Duration Thresholds

| Meeting Length | Segment Duration | Num Segments |
|----------------|------------------|-------------|
| < 1 hour | N/A (upload once) | 1 |
| 1-3 hours | 30-45 minutes | 2-4 |
| 3-8 hours | 60 minutes | 3-8 |
| \> 8 hours | 90 minutes | 6+ |

### Error Handling

1. **Upload Failures**: If `stop_recording` fails, retry with the same `maxDurationSeconds`
2. **Highlights Failures**: Highlights generation is non-blocking; recording upload still completes successfully
3. **Missing Titles**: Always provide a `meetingTitle`; system falls back to meeting_id if not provided

### Performance Considerations

1. **Chunk Upload Latency**: Smaller segments (30-45 min) upload faster than large ones
2. **Highlights Processing**: Each segment's highlights are generated independently; no blocking
3. **Storage Efficiency**: File naming with titles improves discoverability without increasing storage

---

## Troubleshooting

### Recordings Named with ID Instead of Title

**Symptom**: Recording file is named like `meeting-abc-123_uuid.webm` instead of `Meeting Title_uuid.webm`

**Cause**: No `meetingTitle` provided when joining

**Fix**: Include `meetingTitle` in the join request

### Highlights Not Generated

**Symptom**: `generateIncrementalHighlights: true` but no highlights in CW

**Possible Causes**:
1. Duration threshold not met (< 60s by default)
2. HighlightsManager not configured in session dependencies
3. CW service returned an error (check logs for warnings)

**Fix**: 
- Check recording duration: `GET /api/recordings/{meetingId}/status`
- Verify HighlightsManager is configured
- Review logs for `"Failed to request incremental highlights"`

### Upload Hangs with maxDurationSeconds

**Symptom**: `stop_recording` with `maxDurationSeconds` never returns

**Cause**: Recording hasn't reached the specified duration yet

**Fix**: `maxDurationSeconds` is a maximum, not a timeout. Recording stops immediately if meeting ends before reaching this duration.

---

## Future Enhancements

- [ ] Persistent segment tracking across session restarts
- [ ] Configurable highlight themes (action items, questions, decisions)
- [ ] Per-segment audio quality metrics
- [ ] Automatic segment sizing based on network conditions
- [ ] Parallel highlight generation for overlapping segments


