# Incremental Segment Upload Implementation

This document describes how automatic segment uploads and incremental highlights work during recording.

## Architecture

### Duration Monitoring in Recorder

The `Recorder` class monitors recording duration in real-time and automatically uploads segments when `max_duration_seconds` is reached.

#### Key Components:

1. **Segment Tracking Variables** (in `Recorder.__init__`):
   - `_segment_number`: Tracks current segment (starts at 1, increments after each auto-upload)
   - `_last_segment_upload_duration`: Records the duration when the last segment was uploaded (starts at 0)

2. **Duration Monitoring** (in `Recorder._on_chunk()`):
   - After each chunk is uploaded, check if: `duration >= (last_upload_duration + max_duration_seconds)`
   - If threshold reached, call `_trigger_segment_upload()`

3. **Segment Upload Trigger** (new method `Recorder._trigger_segment_upload()`):
   - Finalizes current uploader (closes resumable URL)
   - Calls `UploadFinalizer.finalize()` with `is_final_segment=False`
   - Updates tracking: `last_upload_duration = current_duration`, `segment_number += 1`
   - Creates new uploader for next segment (TODO: requires uploader re-initialization)

4. **Final Segment** (updated `Recorder.stop()`):
   - Finalizes remaining audio accumulated since last auto-upload
   - Calls `UploadFinalizer.finalize()` with `is_final_segment=True`
   - Segment number is whatever we're currently on

### Flow Diagrams

#### Complete Recording with Auto-Uploads

```
Start Recording (maxDurationSeconds=1800)
│
├─ Chunks: 0-600s accumulated (10 min)
│  │
│  └─ Duration check: 600 < 1800, continue
│
├─ Chunks: 600-1200s accumulated (20 min)
│  │
│  └─ Duration check: 1200 < 1800, continue
│
├─ Chunks: 1200-1800s accumulated (30 min) ✓ THRESHOLD REACHED
│  │
│  └─ _on_chunk() detects: 1800 >= (0 + 1800)
│     │
│     └─ Call _trigger_segment_upload():
│        ├─ Finalize Uploader 1 (close resumable URL)
│        ├─ Call finalizer.finalize(..., is_final_segment=False, segment_number=1)
│        ├─ Update: last_upload_duration=1800, segment_number=2
│        └─ Create Uploader 2 for next segment (TODO)
│
├─ Chunks: 1800-2400s accumulated (40 min)
│  │
│  └─ Duration check: 2400 < 3600 (2*1800), continue
│
├─ Chunks: 2400-3600s accumulated (60 min) ✓ THRESHOLD REACHED AGAIN
│  │
│  └─ _on_chunk() detects: 3600 >= (1800 + 1800)
│     │
│     └─ Call _trigger_segment_upload():
│        ├─ Finalize Uploader 2 (close resumable URL)
│        ├─ Call finalizer.finalize(..., is_final_segment=False, segment_number=2)
│        ├─ Update: last_upload_duration=3600, segment_number=3
│        └─ Create Uploader 3 for next segment (TODO)
│
├─ Chunks: 3600-3900s accumulated (65 min)
│  │
│  └─ Duration check: 3900 < 5400 (3*1800), continue
│
└─ User calls stop_recording() [BEFORE next threshold]
   │
   ├─ Finalize Uploader 3 (close resumable URL)
   │
   └─ Call finalizer.finalize(..., is_final_segment=True, segment_number=3)
      ├─ Upload remaining 65 minutes of audio (1-65 min was split into 2 segments)
      ├─ Generate highlights for final segment
      └─ Recording ends
```

#### Early Stop (Before Any Threshold)

```
Start Recording (maxDurationSeconds=1800)
│
├─ Chunks: 0-600s accumulated (10 min)
│  │
│  └─ Duration check: 600 < 1800, continue
│
└─ User calls stop_recording() [BEFORE 30-minute threshold]
   │
   ├─ Finalize Uploader (close resumable URL)
   │
   └─ Call finalizer.finalize(..., is_final_segment=True, segment_number=1)
      ├─ Upload 10 minutes of audio
      ├─ Generate highlights for segment 1
      └─ Recording ends
```

## Highlight Generation

### Incremental Highlights (is_final_segment=False)

When an intermediate segment is uploaded:
- Highlights labeled as "Part N" (e.g., "Part 1", "Part 2")
- Based on segment duration (first 30 min = Part 1, etc.)
- Request ID includes segment number for correlation with CW

### Final Segment Highlights (is_final_segment=True)

When the final segment (remaining audio) is uploaded:
- Highlights labeled appropriately for final segment
- Could be "Final Part", or just "Meeting Highlights" if only one segment
- Marks end of incremental processing

## Implementation Status

### ✅ Completed
- [x] Segment tracking variables added to Recorder
- [x] Duration monitoring in _on_chunk()
- [x] _trigger_segment_upload() method implemented
- [x] Final segment handling in stop()
- [x] Parameter passing through finalizer.finalize()
- [x] Uploader re-initialization: New resumable upload URLs for subsequent segments
  - [x] Abstract reinitialize() method added to ChunkUploader base class
  - [x] DirectChunkUploader.reinitialize(): Clears state to force new resumable URL creation
  - [x] StreamingChunkUploader.reinitialize(): Updates context for remote segmentation
  - [x] Recorder._trigger_segment_upload() calls uploader.reinitialize()

### ⏳ TODO
- [ ] Testing: Validate segment uploads work correctly with multiple segments
  - End-to-end tests with maxDurationSeconds set
  - Verify each segment uploads independently
  - Verify highlights generated per segment
- [ ] Monitoring: Add metrics for segment upload latency, success rates
  - Track time between auto-uploads
  - Monitor per-segment upload success
  - Alert on missing segments

## Concurrency Control: Preventing Duplicate Segment Uploads

To prevent race conditions where multiple chunks arrive during segment upload finalization, a guard flag `_segment_upload_in_progress` is used:

```python
# In Recorder.__init__
self._segment_upload_in_progress = False  # Guard flag

# In Recorder._on_chunk()
if (
    not self._segment_upload_in_progress  # Check guard first
    and self._max_duration_seconds
    and self._stats.duration_seconds >= (self._last_segment_upload_duration + self._max_duration_seconds)
):
    self._segment_upload_in_progress = True
    try:
        await self._trigger_segment_upload()
    finally:
        self._segment_upload_in_progress = False  # Always clear flag
```

**Why it's needed:**

Chunks arrive asynchronously every 5 seconds. When duration threshold is reached:
1. Chunk N triggers `_trigger_segment_upload()` → sets flag = True
2. Chunk N+1 arrives before upload finalization → checks flag, sees True, skips upload
3. Chunk N+2 arrives after finalization → checks flag, sees False, can trigger next segment

Without this guard, Chunk N+1 would attempt to upload an already-finalized segment, causing "upload already finalized" errors.

## Uploader Re-initialization Strategy

### DirectChunkUploader Re-initialization

For direct uploads to object storage:

```python
async def reinitialize(self, context: RecordingContext) -> None:
    # Clear upload state to force new resumable URL creation
    self._target = None      # Remove old upload target
    self._state = None       # Clear resumable state
    self._pending_bytes.clear()  # Clear pending data
    self._failed = False     # Reset error flag
```

How it works:
1. When next chunk arrives, `_ensure_target()` is called
2. `_ensure_target()` sees `self._state is None` and creates a new resumable URL
3. New URL returned from CW API is stored in `self._state`
4. Chunks continue uploading to the new URL
5. Sequencer is preserved to maintain chunk ordering across segments

### StreamingChunkUploader Re-initialization

For streaming to audio service:

```python
async def reinitialize(self, context: RecordingContext) -> None:
    # Update context, buffer preserved
    self._context = context
    # Audio service handles remote segmentation
```

How it works:
1. Context is updated with new meeting ID/segment info
2. Buffer is preserved (chunks don't get lost during transition)
3. Audio service on remote end receives chunks with updated context
4. Remote service creates new logical segments as needed
5. No local state management needed

### State Transitions During Segment Upload

```
Recorder._on_chunk() detects threshold
    ↓
Recorder._trigger_segment_upload() called
    ├─ await self._uploader.finalize()  [LOCK HELD]
    │   └─ Closes current upload/segment
    │
    ├─ await self._finalizer.finalize(..., is_final_segment=False)
    │   └─ Generates highlights for this segment
    │
    ├─ Update: segment_number += 1, last_upload_duration = current_duration
    │
    └─ await self._uploader.reinitialize(self._context)  [LOCK HELD]
        └─ Clears state for new upload
            └─ Next chunk will create new resumable URL (DirectChunkUploader)
            └─ Or use new context (StreamingChunkUploader)
```

Note: Re-initialization happens inside `_on_chunk()` which is called asynchronously, so multiple concurrent chunk callbacks could theoretically race. However, the lock in Recorder protects critical sections.

## Code References

**Files Modified:**
- `meeting-bot/app/recording/recorder.py`: Duration monitoring and segment tracking
- `meeting-bot/app/recording/chunk_uploader.py`: Re-initialization implementations
- `meeting-bot/app/recording/upload_finalizer.py`: Segment vs final handling
- `meeting-bot/app/schemas/recording.py`: StartRecordingRequest schema
- `meeting-bot/app/api/routes/recording.py`: API endpoint

**Key Methods:**
- `Recorder._on_chunk()`: Duration monitoring
- `Recorder._trigger_segment_upload()`: Segment upload orchestration
- `Recorder.stop()`: Final segment handling
- `UploadFinalizer.finalize()`: Segment-aware artifact generation

## Next Steps

1. **Implement Uploader Re-initialization**
   - Design method for creating new resumable URLs mid-recording
   - Handle state transfer between uploaders
   - Test with DirectChunkUploader and StreamingChunkUploader

2. **Testing**
   - Unit tests for segment monitoring logic
   - Integration tests with actual recordings
   - Edge cases: early stops, no max_duration_seconds, etc.

3. **Monitoring & Observability**
   - Track segment upload latencies
   - Monitor success/failure rates per segment
   - Alert on excessively long segments

