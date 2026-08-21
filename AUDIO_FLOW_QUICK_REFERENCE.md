# Audio Capture & Upload - Quick Reference

## TL;DR - 30 Second Explanation

```
1. CAPTURE: AudioContext mixes bot voice (Python injection) + WebRTC participant audio
   
2. ENCODE: AudioWorklet extracts PCM → Opus encoder compresses → 5-sec packets
   
3. QUEUE: UploadQueueManager assigns sequence numbers, batches for upload
   
4. UPLOAD: Frontend calls sendAudioChunkToPython() → Backend receives
   
5. FINALIZE: Every 5 minutes, backend queries DB, builds WebM container, writes to GCS
```

---

## Component Breakdown

### Frontend (JavaScript)

| Component | File | Purpose | Input | Output |
|-----------|------|---------|-------|--------|
| **AudioPipeline** | `audio_pipeline.js` | Capture bot mic + WebRTC audio | Meeting page | `window.__meetingAudio`, `window.remoteAudioStreams` |
| **Recorder** | `recorder_start.js` | Mix audio sources | Mixed streams | AudioContext destination |
| **AudioWorklet** | `opus_worklet_processor.js` | Extract PCM samples | AudioContext | Float32Array samples |
| **PcmFrameCollector** | `pcm_frame_collector.js` | 5-second framing | PCM samples | {data, sampleRate, durationMs} |
| **OpusEncoder** | `opus_encoder.js` | Encode to Opus | PCM frames | Uint8Array (Opus bytes) |
| **UploadQueueManager** | `upload_queue_manager.js` | Sequence + queue | Opus packets | `sendAudioChunkToPython()` calls |
| **UploadSessionManager** | `upload_session_manager.js` | 5-minute boundaries | Queued chunks | Session finalization events |
| **RetryTracker** | `retry_tracker.js` | Retry failed uploads | Failed chunks | Exponential backoff retries |

### Backend (Python)

| Component | File | Purpose | Input | Output |
|-----------|------|---------|-------|--------|
| **Recorder** | `recorder.py` | Orchestration | Chunk events | Upload → ChunkUploader |
| **ChunkUploader** | `chunk_uploader.py` | Abstract upload | AudioChunk | Two implementations below |
| **StreamingChunkUploader** | `chunk_uploader.py:124` | WebSocket upload | Chunks | → Audio Service |
| **ResumableUploadChunkUploader** | `chunk_uploader.py` | Direct GCS upload | Chunks | → GCS (resumable URI) |
| **SessionFinalizer** | `session_finalizer.py` | WebM construction | Session event | WebM file → GCS |
| **WebMBuilder** | `session_finalizer.py:34` | EBML/Matroska container | Opus packets | WebM bytes |

---

## Step-by-Step Execution

### Step 1: Audio Source Initialization

```javascript
// Called once when recording starts
await window.__meetingAudio.initializeVirtualMic();
// ↓ Creates hidden audio element + AudioContext chain
// ↓ Produces MediaStreamTrack injectable to Google Meet

// Meanwhile, intercept RTCPeerConnection for remote streams
window.remoteAudioStreams  // Automatically populated by audio_pipeline.js
// ↓ Contains all remote participant audio tracks
```

### Step 2: Create AudioContext Destination

```javascript
const audioCtx = new AudioContext();
const destination = audioCtx.createMediaStreamDestination();

// Connect bot mic
const vmicSource = audioCtx.createMediaStreamSource(vmicStream);
vmicSource.connect(destination);

// Connect remote streams
window.remoteAudioStreams.forEach(stream => {
    const source = audioCtx.createMediaStreamSource(stream);
    source.connect(destination);
});

// destination.stream now contains mixed audio
```

### Step 3: Choose Transport & Start Recording

```javascript
if (useOpusTransport) {
    // NEW: AudioWorklet → Opus → Upload
    await audioCtx.audioWorklet.addModule("/static/scripts/opus_worklet_processor.js");
    const workletNode = new AudioWorkletNode(audioCtx, "opus-capture", {...});
    destination.connect(workletNode);
    
    // Wire up components
    frameCollector = new PcmFrameCollector(...);
    opusEncoder = new OpusEncoder(...);
    uploadQueue = new UploadQueueManager(...);
    sessionManager = new UploadSessionManager(...);
    retryTracker = new RetryTracker(...);
    
} else {
    // OLD: MediaRecorder → WebM chunks
    const mediaRecorder = new MediaRecorder(destination.stream, 
        {mimeType: "audio/webm; codecs=opus"});
    mediaRecorder.ondataavailable = async (event) => {
        await window.sendAudioChunkToPython({...});
    };
    mediaRecorder.start(5000);
}
```

### Step 4: PCM Extraction (AudioWorklet)

```javascript
// AudioWorklet processor (runs in separate thread)
class OpusCaptureProcessor extends AudioWorkletProcessor {
    process(inputs, outputs, parameters) {
        // inputs[0] = audio channels from destination
        // Extract left channel (mono)
        const pcmData = inputs[0][0];  // Float32Array
        
        // Send to frame collector
        this.port.postMessage({
            type: 'pcmFrame',
            data: pcmData,
            timestamp: currentFrame
        });
    }
}
```

### Step 5: Frame Collection (5 Seconds)

```javascript
frameCollector.processPcmFrame(event.data);
// ↓ Accumulates samples until 5 seconds worth
// ↓ Emits when complete:

frameCollector.onFrameReady = (frame) => {
    {
        frameNumber: 0,
        data: Float32Array(80000),    // 5 seconds @ 16kHz
        sampleRate: 16000,
        durationMs: 5000,
        sampleCount: 80000
    }
};
```

### Step 6: Opus Encoding

```javascript
opusEncoder.encode(frame);
// ↓ Encodes Float32Array → Uint8Array (Opus)
// ↓ ~160KB → ~60KB (2.7x compression)
// ↓ Emits:

opusEncoder.onEncodedPacket = (packet) => {
    {
        frameNumber: 0,
        sampleRate: 16000,
        channels: 1,
        codec: "opus",
        bitrate: 96,  // kbps
        durationMs: 5000,
        data: Uint8Array(60000),  // Opus bytes
        timestamp: Date.now()
    }
};
```

### Step 7: Upload Queue Management

```javascript
uploadQueue.queuePacket(packet);
// ↓ Assigns global sequence number
// ↓ Creates transport chunk:

{
    meetingId: "meeting-123",
    uploadSessionId: "1234567890-abc123",
    sequenceNumber: 0,            // Monotonic counter
    codec: "opus",
    sampleRate: 16000,
    channels: 1,
    durationMs: 5000,
    data: Uint8Array(60000),
    isFinal: false
}

// ↓ Immediately attempts upload
uploadQueue._uploadChunk(chunk);
// ↓ Calls sendAudioChunkToPython(payload)
```

### Step 8: Upload to Backend

```javascript
// Frontend → Backend (via sendAudioChunkToPython binding)
await window.sendAudioChunkToPython({
    meetingId: "meeting-123",
    uploadSessionId: "1234567890-abc123",
    sequenceNumber: 0,
    codec: "opus",
    sampleRate: 16000,
    channels: 1,
    durationMs: 5000,
    audioBlob: [60, 23, 45, ...],  // Uint8Array as Array
    timestamp: "2024-01-15T10:30:45.123Z",
    isFinal: false,
    audioFormatVersion: 2
});

// On success: uploadedSequences.add(0)
// On failure: queue.push(chunk) + retryTracker.recordFailure()
```

### Step 9: Backend Chunk Reception

```python
# Recorder._on_chunk(chunk: AudioChunk) receives from frontend
await self._uploader.upload(chunk)

# Routes to:
# - StreamingChunkUploader: sends to audio service via WebSocket
# - ResumableUploadChunkUploader: uploads directly to GCS
```

### Step 10: 5-Minute Session Boundary

```javascript
// UploadSessionManager fires every 5 minutes
onSessionFinalized({
    uploadSessionId: "1234567890-abc123",
    sequenceRange: {
        start: 0,
        end: 59
    },
    chunkCount: 60,
    byteCount: 3600000  // ~3.6 MB
});

// ↓ Sends to backend via /api/sessions/finalize endpoint
```

### Step 11: WebM Container Construction

```python
# Backend receives finalization event
await sessionFinalizer.finalize_session(event)

# 1. Query database for all Opus packets in session
packets = await database.query_packets(
    session_id=event.upload_session_id,
    sequence_start=0,
    sequence_end=59
)
# Returns 60 Opus packet bytes in order

# 2. Build WebM container
builder = WebMBuilder()
for packet in packets:
    builder.add_opus_packet(packet, timestamp_ms)
    timestamp_ms += 20  # ~20ms per frame

webm_bytes = builder.build()
# Returns complete, playable WebM file

# 3. Write to GCS
gs://meeting-recordings/meeting-123/1234567890-abc123.webm
```

---

## State Management

### Window Objects (Frontend)

```javascript
window.recordingAudioContext          // AudioContext instance
window.recordingDestination          // Mixed audio MediaStreamDestination
window.recordingAudioWorklet         // AudioWorkletNode
window.recordingFrameCollector       // PcmFrameCollector instance
window.recordingOpusEncoder          // OpusEncoder instance
window.recordingUploadQueue          // UploadQueueManager instance
window.recordingSessionManager       // UploadSessionManager instance
window.recordingRetryTracker         // RetryTracker instance

// Metrics
window.recordingFrameMetrics         // {totalSamplesProcessed, ...}
window.recordingEncoderMetrics       // {totalFramesEncoded, ...}
window.recordingUploadMetrics        // {totalChunksQueued, ...}
window.recordingSessionMetrics       // {sessionStartTime, ...}
window.recordingRetryMetrics         // {totalRetries, ...}
```

### Database (Backend)

```sql
-- Table: opus_packets
CREATE TABLE opus_packets (
    id INT PRIMARY KEY,
    meeting_id VARCHAR(255),
    upload_session_id VARCHAR(255),
    sequence_number INT,
    codec VARCHAR(10),          -- "opus"
    sample_rate INT,            -- 16000 or 48000
    channels INT,               -- 1 (mono)
    duration_ms INT,            -- 5000 (5 seconds)
    packet_data BLOB,           -- Opus bytes
    timestamp DATETIME,
    
    INDEX (meeting_id, upload_session_id, sequence_number)
);
```

---

## Troubleshooting Guide

### Issue: No audio captured

**Diagnosis:**
```javascript
// Check virtual mic
window.__meetingAudio.getMicState()
// Expected: {initialized: true, audioContextState: "running", trackEnabled: true}

// Check remote streams
window.remoteAudioStreams.length
// Expected: > 0

// Check destination
window.recordingDestination.stream.getAudioTracks().length
// Expected: > 0
```

**Solutions:**
1. Ensure `audio_pipeline.js` is loaded (check console)
2. Verify AudioContext state isn't "suspended" (call `audioCtx.resume()`)
3. Check microphone permissions in browser

---

### Issue: AudioWorklet fails to load

**Diagnosis:**
```javascript
// Check if processor URL is accessible
fetch('/static/scripts/opus_worklet_processor.js').then(r => r.status)
// Expected: 200

// Check browser support
window.AudioWorkletNode
// Expected: [Function] (not undefined)
```

**Solutions:**
1. Ensure `opus_worklet_processor.js` is served at correct path
2. Falls back to MediaRecorder automatically if fails
3. Check browser dev tools for CORS errors

---

### Issue: Opus encoding fails

**Diagnosis:**
```javascript
window.recordingOpusEncoder.ready
// Expected: true

window.recordingEncoderMetrics
// Check if totalFramesEncoded > 0
```

**Solutions:**
1. WebCodecs fails → falls back to WASM
2. WASM library must be loaded (check network tab)
3. Check encoder console logs for backend initialization errors

---

### Issue: Chunks not uploading

**Diagnosis:**
```javascript
window.recordingUploadQueue.getMetrics()
// Check: totalChunksQueued vs totalChunksUploaded
// Expected: mostly equal (some in-flight is OK)

window.recordingUploadQueue.getPendingChunks().length
// Expected: 0 (or small number)

window.recordingRetryMetrics
// Check: totalRetries (indicates failures)
```

**Solutions:**
1. Check if `sendAudioChunkToPython` is defined: `typeof window.sendAudioChunkToPython`
2. Monitor network tab for failed requests
3. Check backend logs for upload errors
4. Verify upload queue isn't full: `recordingUploadQueue.queueSize < maxQueueSize`

---

### Issue: WebM files are truncated or incomplete

**Diagnosis:**
```python
# Backend: check if finalization events are received
log_search('Session finalized')  # Should see every 5 minutes

# Check database for packets
SELECT COUNT(*) FROM opus_packets WHERE session_id = '{session_id}';
# Expected: 60 packets per complete 5-minute session
```

**Solutions:**
1. Verify session finalization endpoint is wired (POST /api/sessions/finalize)
2. Ensure database is accessible and storing packets
3. Check if session timeout is firing correctly
4. Verify WebM builder processes all packets in sequence order

---

### Issue: High CPU usage

**Diagnosis:**
```javascript
// Which component is consuming CPU?
window.recordingFrameMetrics.totalSamplesProcessed / 16000 / duration_seconds
// Should be ~1.0 (real-time processing)

// Opus encoding taking too long?
window.recordingEncoderMetrics
// Check: averageBitrateKbps (should be ~96)
```

**Solutions:**
1. Switch to WebCodecs backend (faster than WASM)
2. Reduce Opus bitrate if acceptable: `new OpusEncoder({bitrate: 64})`
3. Check for other browser processes competing for CPU
4. Enable hardware acceleration in browser settings

---

### Issue: Upload stalls (stuck at same sequence number)

**Diagnosis:**
```javascript
window.recordingUploadQueue.getSequenceStatus(42)
// Returns: "pending" (should transition to "uploaded")

// Check retry tracker
window.recordingRetryTracker.getMetrics()
// Check: totalRetries, maxRetriesExceeded count
```

**Solutions:**
1. Network disconnection? Check `navigator.onLine`
2. Backend service down? Check `/api/health` endpoint
3. Check retry backoff: waiting exponentially increases, may take minutes
4. Check if chunk size is too large (exceeds request limits)

---

## Common Metrics to Monitor

### Frontend

```javascript
// Every second, log:
console.log("Upload Success Rate:", 
    window.recordingUploadQueue.getMetrics().successRate);

console.log("Queue Depth (MB):", 
    window.recordingUploadQueue.getMetrics().queueSizeMB);

console.log("Compression Ratio:",
    (window.recordingFrameMetrics.totalSamplesProcessed * 2) / 
    window.recordingEncoderMetrics.totalBytesEncoded);

console.log("Encoder Bitrate:",
    window.recordingEncoderMetrics.averageBitrateKbps + " kbps");
```

### Backend

```python
# Per minute in logs:
logger.info(
    f"Upload metrics: "
    f"chunks_received={stats.chunks_received}, "
    f"chunks_uploaded={stats.chunks_uploaded}, "
    f"pending={pending_count}, "
    f"success_rate={(stats.chunks_uploaded/stats.chunks_received)*100:.1f}%"
)
```

---

## Environment Variables / Configuration

```javascript
// Frontend (recorder_start.js)
window.useOpusTransport = false;  // true = Opus, false = MediaRecorder

// PcmFrameCollector
sampleRate: 16000,      // 16kHz for speech (48kHz also supported)
frameSize: 80000,       // 5 seconds @ 16kHz

// OpusEncoder  
bitrate: 96,            // kbps (64-256 range)

// UploadQueueManager
maxQueueSize: 10485760, // 10 MB

// UploadSessionManager
sessionDurationMs: 300000,  // 5 minutes

// RetryTracker
maxRetries: 5,
maxTotalBackoffMs: 300000  // 5 minutes
```

---

## Files Reference

### Frontend Files

```
meeting-bot/app/meeting_platform/google_meet/scripts/
├── audio_pipeline.js                 # Virtual mic + WebRTC interception
├── recorder_start.js                 # AudioContext mixing, transport selection
├── opus_worklet_processor.js         # AudioWorklet for PCM extraction
├── pcm_frame_collector.js            # 5-second frame buffering
├── opus_encoder.js                   # Opus encoding (WebCodecs/WASM)
├── upload_queue_manager.js           # Sequence tracking, queuing
├── upload_session_manager.js         # 5-minute session boundaries
└── retry_tracker.js                  # Exponential backoff retry logic
```

### Backend Files

```
meeting-bot/app/recording/
├── recorder.py                       # Orchestration
├── chunk_uploader.py                 # Abstract + implementations
├── session_finalizer.py              # WebM construction
├── models.py                         # Data structures
├── audio_capture.py                  # Frontend chunk reception
└── sequencer.py                      # Sequence tracking
```

---

## Summary

**Frontend**: Capture → Encode → Queue → Upload  
**Backend**: Receive → Store → Finalize → Container  

**Key Numbers**:
- ✅ 5-second frame size
- ✅ 96 kbps Opus bitrate  
- ✅ 5-minute session window
- ✅ 10 MB queue limit
- ✅ 5 retry attempts per chunk
- ✅ 2.7x compression ratio

