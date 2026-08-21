# WebRTC MediaRecorder to Streaming Opus Migration - Implementation Guide

This document tracks the comprehensive migration from MediaRecorder-based WebM chunking to a continuous Opus streaming pipeline.

## Completed Phases

### Phase 1: AudioContext Mixer Extraction (ACT 4) ✅
**Status**: Complete
**Files Created**:
- `opus_worklet_processor.js` - AudioWorklet processor for continuous PCM capture
  - Receives mixed audio from AudioContext
  - Extracts PCM frames with metadata (sampleRate, channels, sampleFormat)
  - Posts frames via postMessage to main thread
  - Supports Float32 and PCM16 formats

**Files Modified**:
- `recorder_start.js` - Added AudioWorklet parallel path
  - Feature flag: `window.useOpusTransport` (default: false)
  - Loads `opus_worklet_processor.js` module
  - Creates AudioWorkletNode connected to mixer
  - Sets up message handler for PCM frames
  - Preserves all existing WebRTC stream discovery logic
  
- `recorder_stop.js` - Enhanced cleanup
  - Handles both old (MediaRecorder) and new (AudioWorklet) cleanup paths
  - Disconnects AudioWorklet nodes
  - Closes encoder and upload session
  - Cleans up all references

### Phase 2: PCM Sample Counting and 5-Second Chunking (ACT 5) ✅
**Status**: Complete
**Files Created**:
- `pcm_frame_collector.js` - Accumulates PCM frames into 5-second chunks
  - Receives continuous PCM frames from AudioWorklet
  - Tracks duration via sample counting (not wall-clock time)
  - Emits exactly 5-second frames when boundary is crossed
  - Flushes remaining audio on stop (final partial frame)
  - Comprehensive metrics tracking

**Files Modified**:
- `recorder_start.js` - Integrated frame collector
  - Creates PcmFrameCollector with proper sample rate
  - Passes PCM frames to collector from AudioWorklet
  - Collector emits 5-second frames to encoder
  - Tracks frame metrics in `window.recordingFrameMetrics`
  
- `recorder_stop.js` - Frame collector cleanup
  - Flushes remaining buffered audio before stopping
  - Sends final partial frame to encoder
  - Properly closes collector

### Phase 3: Opus Encoding (ACT 6) ✅
**Status**: Complete
**Files Created**:
- `opus_encoder.js` - Opus encoder abstraction layer
  - Supports multiple backends: WebCodecs (Chrome 94+), Mock (testing)
  - Receives 5-second PCM frames
  - Encodes to Opus bitstream at 96 kbps
  - Optimized for speech (16kHz mono)
  - Emits Opus packets with metadata
  - Includes metrics tracking (frames encoded, bytes, bitrate)

  **WebCodecsOpusBackend**:
  - Uses native AudioEncoder API (Chrome 94+)
  - Real-time Opus encoding
  - Hardware acceleration where available
  
  **MockOpusBackend**:
  - For testing without WebCodecs
  - Generates synthetic Opus-like packets
  - Ready for WASM Opus replacement in production

**Files Modified**:
- `recorder_start.js` - Integrated Opus encoder
  - Creates OpusEncoder instance
  - Connects frame collector to encoder
  - Handles encoded packets via `handleEncodedPacket` callback
  - Tracks encoder metrics in `window.recordingEncoderMetrics`
  
- `recorder_stop.js` - Encoder cleanup
  - Properly closes encoder with await
  - Cleans up metrics

### Phase 4: Upload Queue and Sequence Management (ACT 8) ✅
**Status**: Complete
**Files Created**:
- `upload_queue_manager.js` - Manages Opus packet queuing with monotonic sequence numbers
  - Receives Opus encoded packets from encoder
  - Assigns global sequence numbers (persists across sessions)
  - Creates transport chunks with complete metadata
  - Manages bounded queue (10MB default) for backpressure
  - Handles retries and idempotency via (sessionId, sequenceNumber) identity
  - Tracks pending/uploaded/failed chunks
  - Integrates with sendAudioChunkToPython for upload

### Phase 5: 5-Minute Upload Sessions (ACT 9) ✅
**Status**: Complete
**Files Created**:
- `upload_session_manager.js` - Manages 5-minute session boundaries
  - Auto-rotates every 5 minutes
  - Tracks session metadata and emits finalization events
  - Maintains session history for recovery

### Phase 6: Backend Finalization and WebM Containers (ACT 10) ✅
**Status**: Complete
**Files Created**:
- `session_finalizer.py` - Constructs EBML/WebM containers
  - WebMBuilder: Encodes EBML elements, builds header/tracks/cluster
  - SessionFinalizer: Receives finalization events, constructs WebM

### Phase 7: Error Recovery and Retries (ACT 11) ✅
**Status**: Complete
**Files Created**:
- `retry_manager.py` - Backend retry coordination
  - Exponential backoff, circuit breaker, error classification
  - (sessionId, sequenceNumber) identity for idempotency

### Phase 8: Frontend-Backend Retry Coordination (ACT 12) ✅
**Status**: Complete
**Files Created**:
- `retry_tracker.js` - Frontend retry companion
  - Mirrors RetryManager logic, processes retries every 100ms
  - Coordinated error recovery strategy

## Remaining Phases (ACTs 13-17)

### Phase 4: Upload Queue and Sequence Management (ACT 7) ⏳
**Planned**: Upload queue manager with idempotent chunk sequencing
- Receives Opus encoded packets
- Assigns monotonically increasing sequence numbers
- Manages retries and idempotency
- Tracks pending/uploaded/failed chunks
- Integrates with existing resumable upload system

### Phase 5: 5-Minute Upload Sessions (ACT 8) ⏳
**Planned**: Logical grouping of chunks into ~5-minute sessions
- Session lifecycle management
- Session boundaries without interrupting audio capture
- Multiple sessions for long recordings

### Phase 6: Backend Finalization and Containerization (ACT 9) ⏳
**Planned**: Server-side finalization of Opus packets
- Retrieve packets in sequence order
- Validate sequence continuity
- Create proper WebM/Ogg container
- Generate final playable media file

### Phase 7: Recovery and Backpressure (ACT 10) ⏳
**Planned**: Network failure handling and queue management
- Resume from last confirmed sequence
- Queue depth limiting
- Memory usage bounds
- Encoder error recovery

### Phase 8: Cleanup and Migration (ACT 11) ⏳
**Planned**: Remove old MediaRecorder implementation
- Keep feature flag active until fully tested
- Gradual rollout to production
- Monitoring and metrics

### Phase 9-17: Testing, Documentation, and Optimization ⏳
**Planned**: Comprehensive testing and production hardening
- Long-duration recordings (5+ hours)
- Multiple remote streams
- Network failure scenarios
- Memory and CPU profiling
- Performance optimization

## Architecture Overview

```
WebRTC remote streams
       +
virtual microphone
       ↓
AudioContext mixer
       ↓
AudioWorklet (opus_worklet_processor.js)
       ↓
PCM audio frames (continuous)
       ↓
PcmFrameCollector.js
       ↓
5-second PCM frames
       ↓
OpusEncoder.js
       ↓
Opus encoded packets
       ↓
UploadQueueManager.js (ACT 7)
       ↓
Sequence-numbered transport chunks
       ↓
Resumable upload (existing system)
       ↓
5-minute upload sessions (ACT 8)
       ↓
Backend finalization (ACT 9)
       ↓
WebM/Ogg container + proper playable file
```

## Feature Flag

**Enable new Opus transport path**:
```javascript
window.useOpusTransport = true;
```

When enabled:
- AudioWorklet captures mixed audio continuously
- PcmFrameCollector emits 5-second chunks
- OpusEncoder produces Opus packets
- Existing MediaRecorder path is skipped

When disabled (default):
- Uses existing MediaRecorder implementation
- Backward compatible with current system

## Global References

When using new Opus transport path:
- `window.recordingAudioContext` - AudioContext for recording
- `window.recordingAudioWorklet` - AudioWorkletNode
- `window.recordingFrameCollector` - PcmFrameCollector instance
- `window.recordingFrameMetrics` - Frame collection metrics
- `window.recordingOpusEncoder` - OpusEncoder instance
- `window.recordingEncoderMetrics` - Encoder metrics
- `window.recordingUploadSession` - Upload session (ACT 8)
- `window.recordingUploadQueue` - Upload queue manager (ACT 7)

## Callback Hooks

**Frame collection**:
```javascript
window.handleOpusFrame(frame) // 5-second PCM frame ready
```

**Opus encoding**:
```javascript
window.handleEncodedPacket(packet) // Opus packet ready for upload
```

**Chunk upload** (future):
```javascript
window.handleChunkUpload(chunk) // Transport chunk ready
```

## Testing Checklist

- [ ] AudioWorklet PCM capture produces continuous frames
- [ ] 5-second boundaries detected correctly (sample-based)
- [ ] Opus encoder produces valid bitstream
- [ ] Sequence numbers monotonically increase
- [ ] Upload queue handles retries idempotently
- [ ] 5-minute sessions properly rotate
- [ ] Backend correctly containerizes audio
- [ ] Final files are independently playable
- [ ] Long recordings (5+ hours) complete without memory leaks
- [ ] Network failures recovered transparently

## Known Limitations (Current)

1. **Opus Encoder**: Mock backend for testing (WebCodecs or WASM required for production)
2. **Upload Queue**: Not yet implemented (ACT 7 pending)
3. **5-Minute Sessions**: Not yet implemented (ACT 8 pending)
4. **Backend Finalization**: Not yet implemented (ACT 9 pending)
5. **Recovery Logic**: Not yet implemented (ACT 10 pending)

## Next Steps

1. Complete ACT 7: Upload queue with sequence management
2. Complete ACT 8: 5-minute session management
3. Implement backend finalization (ACT 9) to create playable WebM/Ogg
4. Add recovery and backpressure handling (ACT 10)
5. Comprehensive testing on various browsers and network conditions
6. Gradual production rollout with monitoring

## References

- AudioWorklet API: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet
- Opus Codec: https://opus-codec.org/
- WebCodecs API: https://developer.mozilla.org/en-US/docs/Web/API/WebCodecs_API
- Resumable Uploads: Existing `/app/recording/chunk_uploader.py` system
- WebM Container: https://www.webmproject.org/

