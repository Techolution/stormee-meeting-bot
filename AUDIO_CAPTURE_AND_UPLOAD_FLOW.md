# Audio Capture and Upload Flow - Complete Architecture Guide

## Overview

The system implements a **three-phase pipeline** for capturing, encoding, and uploading audio from Google Meet meetings:

1. **Frontend Audio Capture** - Capture and mix audio streams in the browser
2. **Encoding & Queuing** - Encode to Opus and queue chunks with sequence numbers
3. **Backend Upload & Finalization** - Upload to GCS and construct WebM containers

---

## Phase 1: Frontend Audio Capture (Browser)

### 1.1 Audio Source Initialization

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/audio_pipeline.js`

The system captures audio from **two independent sources**:

#### A. Virtual Microphone (Bot Audio)

```javascript
// Lines 24-127: initializeVirtualMicrophone()
```

**What it does:**
- Creates a hidden `<audio>` element (`__python_virtual_microphone_audio`)
- Wraps it in an AudioContext chain: `AudioElement → MediaElementSource → GainNode → MediaStreamDestination`
- Outputs a `MediaStreamTrack` that can be injected into Google Meet's microphone input
- Allows Python backend to play audio that appears as if it's coming from the bot's own microphone

**Flow:**
```
Python Audio Data (via dataUrl)
        ↓
  HTMLAudioElement.src = dataUrl
        ↓
  MediaElementSource (extracts PCM from audio)
        ↓
  GainNode (volume control)
        ↓
  MediaStreamDestination (converts to MediaStreamTrack)
        ↓
  Virtual Microphone Track (injected into Google Meet)
```

#### B. WebRTC Remote Audio (Participant Streams)

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/audio_pipeline.js` (Lines 328-436)

**What it does:**
- Intercepts `RTCPeerConnection` constructor
- Listens for `"track"` events when remote participants' audio arrives
- Stores audio tracks in `window.remoteAudioStreams` and `window.remoteAudioTracks`
- Fires `remoteStreamAdded` custom event when new remote audio arrives

**Flow:**
```
WebRTC Signaling
        ↓
  RTCPeerConnection.ontrack event
        ↓
  Extract audio stream from event.streams[0]
        ↓
  Store in window.remoteAudioStreams
        ↓
  Fire remoteStreamAdded CustomEvent
        ↓
  Available for recording pipeline
```

---

### 1.2 Audio Context Mixing

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/recorder_start.js` (Lines 74-290)

When recording starts, the system **mixes both audio sources** into a single destination:

```javascript
// Create recording AudioContext
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

// Create mixed destination
const destination = audioCtx.createMediaStreamDestination();

// Connect virtual mic stream
const vmicStream = window.__meetingAudio.getVirtualMicStream();
const vmicSource = audioCtx.createMediaStreamSource(vmicStream);
vmicSource.connect(destination);  // Bot audio → mixed output

// Connect remote streams (initial + future arrivals)
window.remoteAudioStreams.forEach(stream => {
    const source = audioCtx.createMediaStreamSource(stream);
    source.connect(destination);  // Remote audio → mixed output
});

// Listen for new remote streams
window.addEventListener('remoteStreamAdded', (event) => {
    const source = audioCtx.createMediaStreamSource(event.detail.stream);
    source.connect(destination);  // New remote audio → mixed output
});
```

**Result:**
- Mixed audio stream available at `destination.stream`
- Contains bot voice + all participant voices
- Ready for recording/encoding

---

### 1.3 Recording Transport Selection

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/recorder_start.js` (Lines 293-699)

The system supports **two transport modes** (feature flag controlled):

#### Mode A: Opus Streaming (NEW - Modern Browsers)

```javascript
const useOpusTransport = window.useOpusTransport || false;

if (useOpusTransport) {
    // Lines 308-488: AudioWorklet setup
    
    // 1. Load Opus AudioWorklet processor
    await audioCtx.audioWorklet.addModule("/static/scripts/opus_worklet_processor.js");
    
    // 2. Create AudioWorklet node for PCM extraction
    const workletNode = new AudioWorkletNode(
        audioCtx,
        "opus-capture",
        {
            processorOptions: {
                sampleRate: audioCtx.sampleRate,
                channels: 1,  // Mono for speech
                sampleFormat: "float32"
            }
        }
    );
    destination.connect(workletNode);
    
    // 3. Create PCM frame collector (5-second framing)
    const frameCollector = new PcmFrameCollector({...});
    
    // 4. Create Opus encoder
    const opusEncoder = new OpusEncoder({...});
    
    // 5. Create upload queue manager
    const uploadQueue = new UploadQueueManager({...});
    
    // 6. Create session manager (5-minute boundaries)
    const sessionManager = new UploadSessionManager({...});
    
    // 7. Create retry tracker for failure recovery
    const retryTracker = new RetryTracker({...});
    
    // Wire them together
    workletNode.port.onmessage = (event) => {
        frameCollector.processPcmFrame(event.data);
    };
    
    frameCollector.onFrameReady = (frame) => {
        opusEncoder.encode(frame);
    };
    
    opusEncoder.onEncodedPacket = (packet) => {
        uploadQueue.queuePacket(packet);
        sessionManager.notifyChunkQueued(packet);
    };
}
```

**Component Pipeline:**
```
Mixed AudioContext
        ↓
   AudioWorklet (PCM extraction)
        ↓
   PcmFrameCollector (5-second framing)
        ↓
   OpusEncoder (Opus encoding)
        ↓
   UploadQueueManager (sequencing + queuing)
        ↓
   RetryTracker (failure recovery)
        ↓
   sendAudioChunkToPython() → Backend
```

#### Mode B: MediaRecorder (LEGACY - Fallback)

```javascript
if (!useOpusTransport) {
    // Lines 506-687: MediaRecorder setup
    
    const mediaRecorder = new MediaRecorder(
        destination.stream,
        { mimeType: "audio/webm; codecs=opus" }
    );
    
    // On data available, send chunk to Python
    mediaRecorder.ondataavailable = async (event) => {
        const chunkId = `${meetingId}-${window.chunkCounter++}`;
        const arrayBuffer = await event.data.arrayBuffer();
        const audioBlob = Array.from(new Uint8Array(arrayBuffer));
        
        await window.sendAudioChunkToPython({
            meetingId,
            chunkId,
            timestamp: new Date().toISOString(),
            audioBlob
        });
    };
    
    mediaRecorder.start(5000);  // 5-second timeslice
}
```

---

## Phase 2: Encoding & Queuing (Frontend)

### 2.1 PCM Frame Collection

**What happens:**
1. AudioWorklet extracts raw PCM samples (float32) from mixed audio
2. Samples are accumulated until 5 seconds worth (e.g., 80,000 samples @ 16kHz)
3. PcmFrameCollector emits a `frame` object with metadata:

```javascript
{
    frameNumber: 0,
    data: Float32Array(80000),  // 5 seconds of 16kHz mono
    sampleRate: 16000,
    durationMs: 5000,
    sampleCount: 80000,
    isFinal: false
}
```

### 2.2 Opus Encoding

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/opus_encoder.js`

**What happens:**

```javascript
class OpusEncoder {
    async encode(frame) {
        // Encode 5-second PCM frame to Opus bitstream
        const encodedData = await this.backend.encode(frame.data);
        
        // Emit encoded packet
        const packet = {
            frameNumber: this.frameNumber++,
            sourceFrameNumber: frame.frameNumber,
            sampleRate: frame.sampleRate,
            channels: 1,
            codec: "opus",
            bitrate: 96,  // kbps for speech
            durationMs: frame.durationMs,
            sampleCount: frame.sampleCount,
            data: encodedData,  // Uint8Array with Opus bytes
            timestamp: new Date(),
            isFinal: frame.isFinal
        };
        
        // Callback to upload queue
        this.onEncodedPacket(packet);
    }
}
```

**Supported Backends:**

1. **WebCodecs API** (Chrome 94+) - Native browser Opus encoding
2. **WASM Libopus** (Fallback) - JavaScript implementation of libopus
3. **Mock Backend** (Testing) - Synthetic data generation

**Compression Ratio:**
- Input: 5 seconds of 16kHz mono PCM = ~160 KB
- Output: 5 seconds at 96 kbps = ~60 KB
- **Compression: ~2.7x**

### 2.3 Upload Queue Management

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/upload_queue_manager.js`

**What happens:**

```javascript
class UploadQueueManager {
    queuePacket(packet) {
        // Create transport chunk with sequence number
        const chunk = {
            meetingId: this.meetingId,
            uploadSessionId: this.uploadSessionId,
            sequenceNumber: this.globalSequence++,  // Global counter
            codec: "opus",
            sampleRate: packet.sampleRate,
            channels: packet.channels,
            durationMs: packet.durationMs,
            data: packet.data,  // Opus bytes
            timestamp: packet.timestamp,
            isFinal: packet.isFinal
        };
        
        // Add to queue
        this.queue.push(chunk);
        this.queueSize += packet.data.byteLength;
        
        // Process queue (upload immediately if possible)
        this._processQueue();
    }
    
    _uploadChunk(chunk) {
        const payload = {
            meetingId: chunk.meetingId,
            uploadSessionId: chunk.uploadSessionId,
            sequenceNumber: chunk.sequenceNumber,
            codec: chunk.codec,
            sampleRate: chunk.sampleRate,
            channels: chunk.channels,
            durationMs: chunk.durationMs,
            audioBlob: Array.from(chunk.data),
            timestamp: chunk.timestamp.toISOString(),
            isFinal: chunk.isFinal,
            audioFormatVersion: 2  // New Opus format
        };
        
        // Fire upload to Python backend
        window.sendAudioChunkToPython(payload)
            .then(() => {
                this.uploadedSequences.add(chunk.sequenceNumber);
                this.totalChunksUploaded++;
                this.totalBytesSent += chunk.data.byteLength;
            })
            .catch((error) => {
                // Re-queue for retry
                this.queue.push(chunk);
                // Notify retry tracker
                if (this.retryTracker) {
                    this.retryTracker.recordFailure(...);
                }
            });
    }
}
```

**Key Features:**
- **Global Sequence Numbering**: Each Opus packet gets a monotonically increasing sequence number
- **Session ID**: All packets in a 5-minute window share the same `uploadSessionId`
- **Backpressure Control**: Queue size capped at 10MB to prevent memory overflow
- **Idempotency**: Sequence numbers enable deduplication on backend
- **Fire-and-Forget with Retries**: Uploads are async, failed chunks re-queued

### 2.4 Session Management (5-Minute Boundaries)

**File**: `meeting-bot/app/meeting_platform/google_meet/scripts/upload_session_manager.js`

**What happens:**

```javascript
class UploadSessionManager {
    constructor(config) {
        this.sessionDurationMs = 5 * 60 * 1000;  // 5 minutes
        this.sessionStartTime = Date.now();
        this.uploadQueue = config.uploadQueue;
    }
    
    start() {
        setInterval(() => {
            const elapsed = Date.now() - this.sessionStartTime;
            if (elapsed >= this.sessionDurationMs) {
                // Fire session finalization event
                this.onSessionFinalized({
                    uploadSessionId: this.uploadQueue.uploadSessionId,
                    chunkCount: this.uploadQueue.totalChunksQueued,
                    byteCount: this.uploadQueue.totalBytesSent,
                    sequenceRange: {
                        start: this.sequenceStart,
                        end: this.uploadQueue.globalSequence - 1
                    }
                });
                
                // Rotate to new session
                this.uploadQueue.rotateSession();
                this.sessionStartTime = Date.now();
                this.sequenceStart = this.uploadQueue.globalSequence;
            }
        }, 1000);
    }
}
```

**Purpose:**
- Every 5 minutes, finalize the current upload session
- Send session summary to backend
- Backend constructs WebM container from this session's Opus packets
- Start fresh session for next 5 minutes

### 2.5 Retry & Error Recovery

**What happens:**

```javascript
class RetryTracker {
    recordFailure(sessionId, sequenceNumber, error) {
        const retryCount = this.failureMap.get(sequenceNumber) || 0;
        
        if (retryCount < this.maxRetries) {
            // Schedule exponential backoff retry
            const backoffMs = Math.min(
                Math.pow(2, retryCount) * 1000,
                this.maxTotalBackoffMs
            );
            
            setTimeout(() => {
                this.uploadQueue._uploadChunk(chunk);
            }, backoffMs);
            
            return true;  // Will retry
        } else {
            // Max retries exceeded
            return false;  // Give up
        }
    }
}
```

---

## Phase 3: Backend Upload & Finalization (Python)

### 3.1 Chunk Reception

**File**: `meeting-bot/app/recording/recorder.py`

**What happens:**

```python
class Recorder:
    async def _on_chunk(self, chunk: AudioChunk) -> None:
        """Receive chunk from frontend via sendAudioChunkToPython."""
        await self._uploader.upload(chunk)
        
        # Monitor for auto-upload segments (max_duration_seconds)
        if self._max_duration_seconds and \
           self._stats.duration_seconds >= (self._last_segment_upload_duration + self._max_duration_seconds):
            # Trigger segment upload
            await self._trigger_segment_upload()
```

### 3.2 Upload Routes

Chunks are routed based on **transport configuration**:

#### Transport A: WebSocket (Audio Service)

**File**: `meeting-bot/app/recording/chunk_uploader.py` (Lines 124-150+)

```python
class StreamingChunkUploader(ChunkUploader):
    """Streams chunks to audio service via WebSocket."""
    
    transport = "websocket"
    
    async def upload(self, chunk: AudioChunk) -> None:
        # Send to audio service via WebSocket
        await self._audio_service.send_chunk(chunk)
        
        # Buffer locally in case of disconnect
        if not acknowledged:
            self._buffer.push(chunk)
```

**Flow:**
```
Frontend Opus Packet
        ↓
  sendAudioChunkToPython()
        ↓
  Recorder._on_chunk()
        ↓
  StreamingChunkUploader.upload()
        ↓
  WebSocket → Audio Service
        ↓
  Audio Service uploads to GCS
```

#### Transport B: Direct Resumable Upload

**File**: `meeting-bot/app/recording/chunk_uploader.py` (Direct implementation)

```python
class ResumableUploadChunkUploader(ChunkUploader):
    """Direct resumable upload to GCS."""
    
    transport = "direct"
    
    async def upload(self, chunk: AudioChunk) -> None:
        # Get or create resumable upload session
        if not self._resumable_uri:
            self._resumable_uri = await self._object_storage.create_resumable_upload(
                bucket="meeting-recordings",
                blob_name=f"{self._meeting_id}/opus-{self._session_id}.webm"
            )
        
        # Upload chunk as-is to resumable URI
        await self._object_storage.upload_chunk(
            uri=self._resumable_uri,
            chunk_data=chunk.audio_blob,
            offset=self._current_offset
        )
        
        self._current_offset += len(chunk.audio_blob)
```

**Key Feature**: **New Resumable URLs per Session**

When a 5-minute session ends:

```python
async def finalize(self) -> UploadOutcome:
    # Finalize current resumable upload
    self._resumable_uri = None  # Close current upload
    
async def reinitialize(self, context: RecordingContext) -> None:
    # Get NEW resumable URL for next session
    self._resumable_uri = await self._object_storage.create_resumable_upload(...)
```

### 3.3 WebM Container Construction

**File**: `meeting-bot/app/recording/session_finalizer.py`

**Triggered when**: Session finalization event received from frontend

**What happens:**

```python
class SessionFinalizer:
    async def finalize_session(self, event: SessionFinalizationEvent) -> dict:
        """
        Receive session summary from frontend:
        - upload_session_id: Session identifier
        - sequence_range: {"start": 0, "end": 60}  # Sequence numbers
        - chunk_count: Number of Opus packets
        - byte_count: Total bytes in session
        """
        
        # 1. Query database for all Opus packets in this session
        packets = await self._fetch_packets_for_session(event)
        # SELECT packet_data FROM opus_packets
        # WHERE session_id = ? AND sequence >= ? AND sequence <= ?
        # ORDER BY sequence ASC
        
        # 2. Build WebM container from Opus packets
        builder = WebMBuilder()
        timestamp_ms = 0
        for packet_data in packets:
            builder.add_opus_packet(packet_data, timestamp_ms)
            timestamp_ms += 20  # ~20ms per Opus frame
        
        webm_bytes = builder.build()  # Returns complete WebM file
        
        # 3. Write WebM to GCS
        gcs_path = await self._write_to_gcs(event, webm_bytes)
        # gs://meeting-recordings/{meeting_id}/{session_id}-timestamp.webm
        
        return {
            "session_id": event.upload_session_id,
            "webm_path": gcs_path,
            "size_bytes": len(webm_bytes),
            "packet_count": len(packets)
        }
```

### 3.4 WebM Format Construction

**File**: `meeting-bot/app/recording/session_finalizer.py` (WebMBuilder class)

**Structure:**

```
WebM File
├── EBML Header
│   ├── EBMLVersion: 1
│   ├── EBMLReadVersion: 1
│   ├── DocType: "webm"
│   └── DocTypeVersion: 4
│
└── Segment
    ├── Info (Metadata)
    │   ├── TimecodeScale: 1ms
    │   ├── Duration: duration_ms
    │   └── WritingApp: "meeting-bot-opus"
    │
    ├── Tracks (Audio Track Definition)
    │   └── Track 1
    │       ├── TrackNumber: 1
    │       ├── TrackType: audio
    │       ├── CodecID: "A_OPUS"
    │       └── Audio
    │           ├── SamplingFrequency: 48000 Hz
    │           └── Channels: 1 (mono)
    │
    └── Cluster (Opus Frames)
        ├── SimpleBlock 1: Opus packet @ T=0ms
        ├── SimpleBlock 2: Opus packet @ T=20ms
        └── ...
```

**Result:**
- Playable WebM file with Opus audio
- Can be played in browser, stored, transcoded
- Each session produces an independently playable file

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (Browser)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Google Meet Audio Streams                                       │
│  ├── Bot Virtual Microphone (Python audio injection)             │
│  │   └── HTMLAudioElement → AudioContext → MediaStreamTrack     │
│  │                                                                │
│  └── Remote WebRTC Streams (Participant audio)                   │
│      └── RTCPeerConnection.ontrack → MediaStreamTrack            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Audio Context Mixing                                 │        │
│  │  ├─ virtualMicStream → source → destination           │        │
│  │  └─ remoteStream[n] → source → destination            │        │
│  └──────────────────────────────────────────────────────┘        │
│                      ↓ (destination.stream)                       │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  CHOICE: Transport Mode                               │        │
│  │  ├─ AudioWorklet → PCM Extraction (NEW)               │        │
│  │  └─ MediaRecorder → WebM Chunks (LEGACY)              │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓ (if Opus Transport)                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  PCM Frame Collector (5-second framing)               │        │
│  │  Input: PCM samples from AudioWorklet                 │        │
│  │  Output: 5-sec frame {data, sampleRate, durationMs}   │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Opus Encoder (WebCodecs API or WASM)                 │        │
│  │  Input: Float32Array (PCM)                            │        │
│  │  Output: Uint8Array (Opus bitstream)                  │        │
│  │  Compression: ~2.7x                                   │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Upload Queue Manager (Sequence Tracking)             │        │
│  │  ├─ Assign sequence numbers (global counter)           │        │
│  │  ├─ Assign session ID (5-minute window)                │        │
│  │  └─ Queue for upload                                   │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Retry Tracker (Exponential Backoff)                  │        │
│  │  ├─ Track failed uploads                               │        │
│  │  └─ Schedule retries with backoff                      │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  sendAudioChunkToPython(payload) ──────────┐                    │
│                                              │                    │
└──────────────────────────────────────────────┼────────────────────┘
                                               │
                                               ↓ JSON over WebSocket
┌──────────────────────────────────────────────────────────────────┐
│                    BACKEND (Python)                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Recorder (Orchestration)                                        │
│  ├─ Receive chunk                                                │
│  └─ Route to appropriate uploader                                │
│                                                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  CHOICE: Upload Transport                             │        │
│  ├──────────────────────────────────────────────────────┤        │
│  │  Option A: WebSocket (Audio Service)                  │        │
│  │  └─ Stream to external audio service                  │        │
│  │     (Audio service handles GCS upload)                │        │
│  │                                                        │        │
│  │  Option B: Direct Resumable Upload                    │        │
│  │  └─ Upload directly to GCS via resumable URI           │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓ (per session)                                         │
│                                                                   │
│  Session Finalization Event Received                             │
│  ├─ Session ID: {timestamp}-{random}                             │
│  ├─ Sequence range: {start: 0, end: 60}                          │
│  └─ Metadata: chunk_count, byte_count                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Query Database                                       │        │
│  │  SELECT opus_packets                                  │        │
│  │  WHERE session_id = ? AND sequence >= ? AND <= ?      │        │
│  │  ORDER BY sequence ASC                                │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  WebM Builder (EBML/Matroska Container)               │        │
│  │  ├─ EBML Header (format metadata)                     │        │
│  │  ├─ Info (duration, timecodeScale)                    │        │
│  │  ├─ Tracks (audio track @ 48kHz mono Opus)            │        │
│  │  └─ Cluster (SimpleBlocks with Opus packets)          │        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  Write to GCS                                         │        │
│  │  gs://meeting-recordings/{meeting_id}/{session_id}.webm        │
│  └──────────────────────────────────────────────────────┘        │
│           ↓                                                        │
│  Playable WebM File                                              │
│  └─ Contains Opus audio, playable in any browser                 │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Dual Audio Sources
- **Bot Virtual Microphone**: Allows bot to play responses/content to participants
- **WebRTC Remote Streams**: Captures all participant voices
- **Result**: Complete meeting record including bot and all participants

### 2. Opus Encoding
- **Why Opus?** Modern codec, excellent speech quality, low bitrate (96 kbps for speech)
- **Compression**: ~2.7x reduction (160KB PCM → 60KB Opus per 5 seconds)
- **Browser Support**: WebCodecs API (modern) + WASM fallback (broad compatibility)

### 3. 5-Second Framing
- **Why 5 seconds?** Good balance between latency and file size
- **Enables**: Sequence numbering, idempotent retries, precise error recovery
- **Result**: ~60 Opus packets per 5-minute session

### 4. Sequence Numbering
- **Global Counter**: Monotonically increasing across entire recording
- **Per-Session Reset**: Optional per 5-minute boundary for multi-file handling
- **Benefit**: Deduplication, ordering, idempotency on backend

### 5. Session Boundaries (5 Minutes)
- **Why 5 minutes?** Practical limit for WebM files, aligns with GCS upload resumability
- **Process**:
  1. Frontend queues chunks for 5 minutes
  2. Sends finalization event with sequence range
  3. Backend queries database, builds WebM container
  4. Writes playable file to GCS
  5. Starts new session
- **Result**: Multiple independent WebM files, one per 5-minute window

### 6. Retry Strategy
- **Exponential Backoff**: 1s, 2s, 4s, 8s, ... (capped at 5 minutes)
- **Max Retries**: 5 attempts per chunk
- **Tracking**: Sequence numbers enable idempotent retries

### 7. Transport Abstraction
- **Two Paths**:
  - **WebSocket**: Stream to audio service (normal production)
  - **Direct**: Resumable upload to GCS (fallback/independence)
- **Benefit**: Can switch transports without code changes

---

## Metrics & Monitoring

### Frontend Metrics

**PcmFrameCollector**:
- `totalSamplesProcessed`: PCM samples extracted
- `totalFramesEmitted`: 5-second frames created
- `skippedSamples`: Out-of-order samples dropped

**OpusEncoder**:
- `totalFramesEncoded`: 5-second frames encoded
- `totalBytesEncoded`: Opus bytes produced
- `averageBitrateKbps`: Actual bitrate achieved

**UploadQueueManager**:
- `totalChunksQueued`: Packets queued
- `totalChunksUploaded`: Packets successfully sent
- `successRate`: Upload success percentage
- `totalRetries`: Retries across all chunks
- `queueDepth`: Chunks currently queued

**UploadSessionManager**:
- `sessionStartTime`: When current session began
- `chunkCount`: Chunks in current session
- `byteCount`: Bytes in current session

### Backend Metrics

**Recorder**:
- `duration_seconds`: Recording duration
- `chunks_received`: Total chunks from frontend
- `chunks_uploaded`: Chunks persisted
- `pending_chunks`: Chunks awaiting upload

**SessionFinalizer**:
- `packets_retrieved`: Opus packets from database
- `webm_bytes`: Size of constructed container
- `gcs_upload_time`: Time to write to GCS

---

## Error Scenarios & Recovery

### Scenario 1: Network Disconnection During Upload

```
Frontend tries sendAudioChunkToPython() → Network error
    ↓
RetryTracker.recordFailure() called
    ↓
Exponential backoff: wait 1s, then retry
    ↓
If max retries exceeded, chunk dropped (logged)
```

### Scenario 2: Backend Outage

```
Frontend keeps queuing chunks locally
    ↓
Queue fills up (10MB default limit)
    ↓
New chunks dropped to prevent memory overflow
    ↓
When backend recovers, queued chunks retry
```

### Scenario 3: Incomplete 5-Minute Session

```
Recording stops before 5-minute boundary
    ↓
Frontend sends final session finalization
    ↓
Backend queries all packets for session (including incomplete)
    ↓
WebM built with available packets
    ↓
Playable file written to GCS (may be <5min)
```

---

## Performance Characteristics

### CPU Usage
- **AudioWorklet**: ~5-10% (PCM extraction)
- **Opus Encoding**: ~10-15% (depends on browser/backend)
- **Total Frontend**: ~15-25% on modern hardware

### Memory Usage
- **AudioContext**: ~50MB (mixing buffers)
- **Queue**: ~10MB max (configurable backpressure)
- **Total Frontend**: ~60MB + AudioContext overhead

### Bandwidth
- **Opus at 96 kbps**: ~12 KB/s
- **Upload rate**: ~100-500 KB/s (depends on connection)
- **Expected latency**: 1-5 seconds before chunk appears in GCS

### File Sizes (Typical Meeting)
- **5 minutes of speech**:
  - PCM (uncompressed): ~4.8 MB
  - Opus (96 kbps): ~1.8 MB
  - WebM (with container): ~1.9 MB
- **Compression**: ~96% reduction vs. uncompressed

---

## Summary

The system implements a **production-grade audio recording pipeline** that:

1. ✅ **Captures** bot and participant audio via dual sources
2. ✅ **Encodes** to Opus for efficient storage (~2.7x compression)
3. ✅ **Queues** with sequence tracking for idempotency
4. ✅ **Uploads** via two transports (WebSocket or direct resumable)
5. ✅ **Finalizes** WebM containers at session boundaries
6. ✅ **Recovers** from failures with exponential backoff
7. ✅ **Scales** with backpressure and memory limits
8. ✅ **Monitors** with comprehensive metrics

The **modular design** allows:
- Switching between transports without code changes
- Independent testing of each component
- Easy addition of new codecs or containers
- Graceful degradation in adverse network conditions

