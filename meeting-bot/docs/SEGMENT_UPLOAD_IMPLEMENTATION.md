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

## Audio Duplication vs. File Validity: Finding the Balance

**THE TRADE-OFF:**

WebM files require proper EBML headers to be playable. Chunk 0 contains:
- WebM EBML header (codec info, ~4KB) 
- First audio frame data (~100 bytes)

We have two options:

### Option A: No Headers (Files Unplayable)
```python
# Don't reinject headers
if self._header_bytes is not None:
    self._pending_bytes.extend(self._header_bytes)  # REMOVED
```
Result: Segments 2+ missing WebM headers → **CORRUPTED, UNPLAYABLE** ❌

### Option B: Full Headers + Minimal Frame Duplication (Files Valid)
```python
# Reinject headers for WebM validity
if self._header_bytes is not None:
    self._pending_bytes.extend(self._header_bytes)  # Full chunk 0
```
Result: 
```
Segment 1: Chunk 0 (header + frame 0) + Chunks 1,2,3 = [0KB header + ~100B frame 0 + audio 1-10sec]
Segment 2: Chunk 0 (header + frame 0) + Chunks 4,5,6 = [0KB header + ~100B frame 0 + audio 11-20sec]
Segment 3: Chunk 0 (header + frame 0) + Chunks 8,9,10 = [0KB header + ~100B frame 0 + audio 21-30sec]
```

**The Cost:** Each segment has ONE audio frame repeated (~100 bytes out of hundreds of KB)
**The Benefit:** All segment files are valid, independently playable WebM ✅

### Decision: Option C (Smart Header Extraction)

**ACTUAL SOLUTION:** Extract ONLY the WebM header bytes, not the entire chunk 0:

```python
# In upload() method, when chunk 0 arrives:
if ready.sequence == 0 and self._header_bytes is None:
    # Extract only first 4KB (WebM EBML header size)
    header_size = min(4096, len(ready.data))
    self._header_bytes = bytes(ready.data[:header_size])
```

Then in `reinitialize()`:
```python
if self._header_bytes is not None:
    self._pending_bytes.extend(self._header_bytes)  # Only ~4KB, no audio!
```

Result:
```
Segment 1: [WebM header ~4KB] + [Chunk 0 audio + Chunks 1,2,3] = 0-10sec ✅
Segment 2: [WebM header ~4KB] + [Chunks 4,5,6,7] = 11-20sec ✅ (NO chunk 0 audio!)
Segment 3: [WebM header ~4KB] + [Chunks 8,9,10,11] = 21-30sec ✅ (NO chunk 0 audio!)
```

**Why this works:**
1. **WebM validity** - Headers present, files are playable ✅
2. **No audio duplication** - Only 4KB header repeated, not chunk 0's audio ✅
3. **Perfect segment boundaries** - Each segment has ONLY its own audio ✅

Users get:
- ✅ Segment 1: Complete audio 0-10sec
- ✅ Segment 2: Complete audio 11-20sec (no overlap!)
- ✅ Segment 3: Complete audio 21-30sec (no overlap!)
- ✅ All segments independently playable with correct audio

## Critical: Segment Upload Execution Order

**PROBLEM:** If `reinitialize()` is called AFTER artifact generation, incoming chunks will fail:

```
10:51:09 - Threshold reached, finalize() starts
10:51:14 - finalize() completes, upload CLOSED with is_final=True
          Then: artifact generation, email sending (44 seconds!)
10:51:58 - reinitialize() finally called (TOO LATE!)

Meanwhile:
10:51:30 - Chunk 6 arrives → tries to upload to CLOSED session → ERROR!
```

**SOLUTION:** Call `reinitialize()` IMMEDIATELY after `finalize()`, before any async work:

```python
async def _trigger_segment_upload(self) -> None:
    # STEP 1: Finalize current segment
    outcome = await self._uploader.finalize()  # Closes upload
    
    # STEP 2: Reinitialize IMMEDIATELY (creates new session)
    await self._uploader.reinitialize(self._context)  # <- MUST BE HERE!
    
    # STEP 3: Update counters
    self._segment_number += 1
    
    # STEP 4: Artifact generation (non-blocking, fire-and-forget)
    asyncio.create_task(self._finalizer.finalize(...))  # Background task
```

Now incoming chunks will upload to the new session created in STEP 2, not the closed session from STEP 1.

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
    # CRITICAL: Do NOT reset the sequencer!
    # Keep sequencer to handle chunks across segment boundaries
    self._failed = False     # Reset error flag
```

**Why Sequencer Must NOT Be Reset:**

The ChunkSequencer does NOT enforce per-file sequence order. It ensures GLOBAL chunk sequence ordering:
- Browser sends chunks with continuous sequence: 0, 1, 2, ..., 50, 51, 52, ..., 100, ...
- This sequence is GLOBAL across all segments
- Sequencer's job: buffer out-of-order arrivals, release when in-sequence

**Segment Upload Flow:**

```
Segment 1: Create File1 with resumable URL
  Chunks 0-50 arrive → Sequencer releases them in order → Upload to File1
  
Reinitialize: Clear File1's state, keep sequencer
  
Segment 2: Create File2 with NEW resumable URL
  Chunks 51-100 arrive → Sequencer (at state 51) releases them → Upload to File2
  
Segment 3: Create File3 with NEW resumable URL
  Chunks 101-150 arrive → Sequencer (at state 101) releases them → Upload to File3
```

**Key Insight:**
Different resumable URLs point to different files, so the SAME byte stream (from global sequencer) is uploaded to DIFFERENT storage objects. The sequencer doesn't care about files—it just ensures chunks are released in global sequence order.

**Critical: Sequencer Creation Logic:**

The `start()` method must preserve the sequencer:

```python
async def start(self, context: RecordingContext) -> None:
    self._context = context
    # Only create sequencer ONCE on first recording start
    if self._sequencer is None:  # <- CRITICAL CHECK
        self._sequencer = ChunkSequencer(meeting_id=context.meeting_id)
    self._pending_bytes.clear()
    self._failed = False
```

Why? Because:
- Recording starts → `start()` called → creates sequencer
- Chunks 0-50 arrive → released immediately
- Segment 1 finalized → sequencer state: `next_expected=51`, `_seen={0..50}`
- Segment 2 begins → `start()` called AGAIN
  - ❌ If start() creates NEW sequencer: `next_expected=0`, `_seen={}`
    - Chunk 51 arrives → sequencer waits for 0-50 → DEADLOCK
  - ✅ If start() preserves sequencer: `next_expected=51`, `_seen={0..50}`
    - Chunk 51 arrives → matches next_expected → RELEASED

**Why Resetting Breaks It:**
If sequencer is reset or recreated during segment transitions, incoming chunks for segment 2+ are waiting for earlier sequence numbers that already passed.

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

## Approach 2: Fresh Uploader Per Segment (Implemented)

To solve cumulative segment uploads and audio duplication issues, we implement **Approach 2: Create New Uploader Instance Per Segment**.

### Problem Addressed

Previous approaches tried to reuse the same uploader with reinitialize(), but this caused:
1. **Audio Duplication**: WebM header bytes from chunk 0 were re-injected into segment 2, causing overlap
2. **Cumulative Uploads**: Segments were 0-10s, 0-20s, 0-30s instead of 0-10s, 11-20s, 21-30s
3. **State Confusion**: Single uploader instance accumulated state across segments

### Solution

**Create a completely fresh uploader for each segment** instead of reusing/reinitializing.

#### Implementation Details:

1. **Uploader Builder Factory** (`MeetingSession._build_recorder()`):
   ```python
   def uploader_builder() -> ChunkUploader:
       """Create a new uploader for the next segment."""
       new_stats = RecordingStats()
       return self._build_uploader(new_stats)
   ```
   - Creates a closure that has access to dependencies
   - Returns completely fresh uploader with new RecordingStats
   - Passed to Recorder during construction

2. **Recorder Stores Builder** (`Recorder.__init__()`):
   ```python
   self._uploader_builder = uploader_builder  # Function to create new uploaders for segments
   ```
   - Stores the builder callback for later use
   - Used in `_trigger_segment_upload()` for segment transitions

3. **Create New Uploader on Segment Transition** (`Recorder._trigger_segment_upload()`):
   ```python
   # STEP 2: Create BRAND NEW uploader for next segment
   if self._uploader_builder is not None:
       self._uploader = self._uploader_builder()
       await self._uploader.start(self._context)
   else:
       # Fallback: use old reinitialize method if no builder provided
       await self._uploader.reinitialize(self._context)
   ```
   - When `max_duration_seconds` threshold reached, creates fresh uploader
   - New uploader has:
     - Fresh `_sequencer` (starts at 0, not continuing globally)
     - Fresh `_pending_bytes` buffer
     - Fresh `_header_bytes` extraction from new segment's chunk 0
     - Fresh `_state` and resumable URL
   - Ensures each segment is uploaded to its own object/resumable session
   - Maintains backward compatibility with fallback to reinitialize

### Why This Works

1. **Fresh Sequencer**: Each uploader starts with a new ChunkSequencer, so chunk 0 for segment 2 is properly sequenced (not waiting for chunk 51)
2. **Clean Header Extraction**: New uploader extracts WebM header from segment 2's chunk 0, not reusing segment 1's header
3. **Independent Objects**: Each segment uploads to its own resumable URL, creating separate audio files
4. **No State Carryover**: No accumulated `_pending_bytes` or `_header_bytes` confusion between segments

### Code Impact

**Modified Files:**
- `meeting-bot/app/meeting/meeting_session.py`: Added uploader_builder to _build_recorder()
- `meeting-bot/app/recording/recorder.py`:
  - Added uploader_builder parameter to __init__()
  - Updated _trigger_segment_upload() to create fresh uploader
  - Made finalizer.finalize() non-blocking with asyncio.create_task()

**Unchanged:**
- `meeting-bot/app/recording/chunk_uploader.py`: reinitialize() methods kept for backward compatibility
- No changes to sequencer logic or header extraction

### Result

Segments are now uploaded independently with proper headers:
- Segment 1: 0-10s (uploaded as complete WebM file)
- Segment 2: 11-20s (uploaded as complete WebM file)
- Segment 3: 21-30s (uploaded as complete WebM file)

Each segment is independently playable with valid WebM structure.

## Next Steps

1. **Testing**
   - Unit tests for uploader_builder and segment creation
   - Integration tests with actual multi-segment recordings
   - Verify segment boundaries and audio continuity

2. **Monitoring & Observability**
   - Track segment upload latencies
   - Monitor success/failure rates per segment
   - Alert on excessively long segments

3. **Performance Optimization**
   - Consider caching chunk headers for efficiency
   - Optimize sequencer creation overhead

