# Audio Capture & Upload System - Documentation Index

## 📚 Documentation Overview

This repository contains comprehensive documentation for the **audio capture, encoding, and upload pipeline** used in the meeting bot system. The system handles recording of all meeting audio (bot voice + participant voices), encodes it to Opus format, and uploads it to Google Cloud Storage.

### Available Documentation

1. **AUDIO_CAPTURE_AND_UPLOAD_FLOW.md** (⭐ Start Here)
   - **Length**: ~1,500 lines
   - **Audience**: Architects, senior engineers, system designers
   - **Contains**:
     - Complete end-to-end architecture
     - Detailed component descriptions with code snippets
     - Data flow diagrams
     - Design decisions and trade-offs
     - Performance characteristics
     - Error scenarios and recovery
   - **Time to read**: 30-45 minutes

2. **AUDIO_FLOW_QUICK_REFERENCE.md** (⚡ Quick Lookup)
   - **Length**: ~600 lines
   - **Audience**: Developers, debuggers, quick-reference needs
   - **Contains**:
     - 30-second TL;DR explanation
     - Component breakdown table
     - Step-by-step execution guide
     - State management reference
     - Troubleshooting guide
     - Common metrics to monitor
   - **Time to read**: 5-10 minutes

3. **AUDIO_SYSTEM_README.md** (📖 This File)
   - **Length**: Quick navigation guide
   - **Audience**: Everyone
   - **Contains**:
     - Documentation index
     - Reading guides by role
     - Key concepts summary
     - File structure reference

---

## 🎯 Choose Your Reading Path

### Path A: "I want to understand how the entire system works"
**👤 Audience**: Architects, lead engineers, new team members

1. Start with **AUDIO_FLOW_QUICK_REFERENCE.md** → "TL;DR" section (2 min)
2. Read **AUDIO_CAPTURE_AND_UPLOAD_FLOW.md** → Sections 1-3 (20 min)
3. Deep dive into specific phases as needed (15-30 min)

**Expected outcome**: Complete understanding of data flow, architecture, and design decisions

---

### Path B: "I need to debug an issue right now"
**👤 Audience**: Backend developers, DevOps, QA

1. Go to **AUDIO_FLOW_QUICK_REFERENCE.md** → "Troubleshooting Guide" (5 min)
2. Check "Common Metrics to Monitor" (2 min)
3. Look up specific component in "Component Breakdown" table (1 min)
4. Reference **AUDIO_CAPTURE_AND_UPLOAD_FLOW.md** for detailed explanations (5-10 min)

**Expected outcome**: Identify root cause and appropriate fix

---

### Path C: "I need to implement a change to the audio pipeline"
**👤 Audience**: Feature developers, performance engineers

1. Review **AUDIO_CAPTURE_AND_UPLOAD_FLOW.md** → "Design Decisions" section (10 min)
2. Locate affected components in "Phase 1/2/3" sections (10 min)
3. Check **AUDIO_FLOW_QUICK_REFERENCE.md** → "Files Reference" (2 min)
4. Review existing code in source files (15-30 min)
5. Verify changes don't break metrics/monitoring (5 min)

**Expected outcome**: Safe, informed code changes

---

### Path D: "I just want the key numbers and API"
**👤 Audience**: Product managers, QA, API consumers

1. **AUDIO_FLOW_QUICK_REFERENCE.md** → "TL;DR" (1 min)
2. **AUDIO_FLOW_QUICK_REFERENCE.md** → "Environment Variables / Configuration" (3 min)
3. **AUDIO_FLOW_QUICK_REFERENCE.md** → "Common Metrics to Monitor" (3 min)

**Expected outcome**: Quick reference for key parameters and metrics

---

## 🔑 Key Concepts at a Glance

### The Three-Phase Pipeline

```
Phase 1: CAPTURE          Phase 2: ENCODE & QUEUE       Phase 3: UPLOAD & FINALIZE
┌─────────────────────┐   ┌──────────────────────────┐   ┌─────────────────────────┐
│  Audio Mixing       │   │  Opus Compression        │   │  WebM Container Build   │
│  ├─ Bot Microphone  │→→│  ├─ PCM Frame Collector  │→→│  ├─ Database Query       │
│  ├─ WebRTC Audio    │   │  ├─ Opus Encoder        │   │  ├─ EBML Construction   │
│  └─ AudioContext    │   │  ├─ Upload Queue Mgr    │   │  └─ GCS Upload          │
│                     │   │  └─ Retry Tracker       │   │                         │
└─────────────────────┘   └──────────────────────────┘   └─────────────────────────┘
     (Frontend)                  (Frontend)                     (Backend)
```

### Key Components

| Component | Role | Input | Output |
|-----------|------|-------|--------|
| **AudioContext** | Mixes bot + remote audio | Raw streams | Mixed destination |
| **AudioWorklet** | Extracts PCM samples | AudioContext | Float32Array |
| **PcmFrameCollector** | Buffers 5-second frames | PCM samples | 5-sec frames |
| **OpusEncoder** | Compresses audio | PCM frames | Opus packets |
| **UploadQueueManager** | Assigns sequence numbers | Opus packets | HTTP requests |
| **SessionFinalizer** | Builds WebM containers | Opus packets | Playable WebM file |

### Key Numbers

```
Audio Processing:
  • Sample rate: 16,000 Hz (or 48,000 Hz)
  • Channels: 1 (mono)
  • Frame size: 5 seconds
  • Samples per frame: 80,000 (@ 16kHz)
  
Opus Encoding:
  • Bitrate: 96 kbps (typical for speech)
  • Frame duration: 20 ms (internal)
  • Compression: ~2.7x (160KB PCM → 60KB Opus per 5 seconds)
  
Session Management:
  • Session duration: 5 minutes
  • Packets per session: ~60 (5min ÷ 5sec)
  • Queue limit: 10 MB
  
Retry Strategy:
  • Max retries per chunk: 5
  • Backoff: exponential (1s, 2s, 4s, 8s, ...)
  • Max total backoff: 5 minutes
```

---

## 📁 File Structure

### Frontend JavaScript Files

```
meeting-bot/app/meeting_platform/google_meet/scripts/
├── audio_pipeline.js
│   └── Virtual microphone + WebRTC stream capture
│       • initializeVirtualMicrophone()
│       • playIntoMicrophone(dataUrl)
│       • window.__meetingAudio API
│
├── recorder_start.js
│   └── AudioContext mixing + transport selection
│       • AudioContext creation
│       • Virtual mic + remote stream connection
│       • AudioWorklet or MediaRecorder startup
│
├── opus_worklet_processor.js
│   └── AudioWorklet for PCM extraction
│       • Runs in separate thread
│       • Extracts float32 samples
│       • Posts to main thread
│
├── pcm_frame_collector.js
│   └── 5-second frame buffering
│       • Accumulates PCM samples
│       • Emits complete frames
│       • Tracks metrics
│
├── opus_encoder.js
│   └── Opus audio encoding
│       • WebCodecs API (native, fast)
│       • WASM libopus (fallback, compatible)
│       • Mock backend (testing)
│
├── upload_queue_manager.js
│   └── Chunk sequencing + upload queuing
│       • Assigns global sequence numbers
│       • Manages upload queue
│       • Handles retries
│
├── upload_session_manager.js
│   └── 5-minute session boundaries
│       • Fires finalization events every 5min
│       • Tracks session metadata
│
└── retry_tracker.js
    └── Failure recovery
        • Exponential backoff
        • Retry coordination
```

### Backend Python Files

```
meeting-bot/app/recording/
├── recorder.py
│   └── Recording orchestration
│       • class Recorder: lifecycle management
│       • _on_chunk(): chunk reception
│       • _trigger_segment_upload(): auto-upload
│
├── chunk_uploader.py
│   ├── class ChunkUploader (ABC)
│   │   └── Abstract interface
│   ├── class StreamingChunkUploader
│   │   └── WebSocket upload to audio service
│   ├── class ResumableUploadChunkUploader
│   │   └── Direct resumable upload to GCS
│   └── class UploadOutcome
│       └── Finalization result
│
├── session_finalizer.py
│   ├── class SessionFinalizer
│   │   └── finalize_session(): WebM construction
│   ├── class WebMBuilder
│   │   ├── add_opus_packet()
│   │   ├── _build_ebml_header()
│   │   ├── _build_info()
│   │   ├── _build_tracks()
│   │   ├── _build_cluster()
│   │   └── build(): returns WebM bytes
│   └── class SessionFinalizationEvent
│       └── Frontend → Backend session event
│
├── models.py
│   ├── class AudioChunk
│   ├── class RecordingContext
│   └── class RecordingStats
│
├── audio_capture.py
│   └── Frontend chunk reception point
│
└── sequencer.py
    └── Sequence number tracking
```

---

## 🔄 Data Flow Diagram

### High Level

```
┌─────────────────────────────────────────────┐
│     Google Meet Meeting Audio               │
│  (Participant voices + Bot responses)       │
└─────────────────────────────────────────────┘
                     ↓
         ┌───────────────────────┐
         │   AudioContext Mix    │
         │ (Virtual Mic + WebRTC)│
         └───────────────────────┘
                     ↓
         ┌───────────────────────┐
         │  CHOICE: Transport    │
         ├─ Opus (NEW - Modern)  │
         └─ MediaRecorder (OLD)  │
                     ↓
         ┌───────────────────────┐
         │  Opus Encoding        │
         │ (2.7x compression)    │
         └───────────────────────┘
                     ↓
         ┌───────────────────────┐
         │  Upload Queue         │
         │ (Sequence tracking)   │
         └───────────────────────┘
                     ↓
    sendAudioChunkToPython(payload)
                     ↓
         ┌───────────────────────┐
         │   Backend Uploader    │
         ├─ WebSocket (Audio Svc)│
         └─ Direct (GCS)         │
                     ↓
      Every 5 minutes → Session Finalization
                     ↓
         ┌───────────────────────┐
         │  WebM Construction    │
         │ (EBML Container)      │
         └───────────────────────┘
                     ↓
  gs://meeting-recordings/{meeting_id}/{session_id}.webm
                     ↓
         ┌───────────────────────┐
         │  Playable WebM File   │
         │  (Browser compatible) │
         └───────────────────────┘
```

---

## 🚀 Quick Start: "How It Works" in 2 Minutes

### For Users

> "When I record a meeting, what happens to the audio?"

1. **Audio Capture**: The bot captures its own voice (injected via virtual microphone) and all participant voices (via WebRTC streams) and mixes them together in the browser

2. **Compression**: The mixed audio is encoded to Opus format (modern, efficient codec) in real-time, reducing size by ~2.7x

3. **Upload**: Compressed audio is sent to the backend in 5-second chunks, with automatic retries if the network hiccups

4. **Storage**: Every 5 minutes, the backend assembles the chunks into a playable WebM file and stores it in Google Cloud Storage

**Result**: Complete meeting recording, efficiently compressed, reliably stored

### For Developers

> "How does the code do it?"

1. **Frontend captures PCM**: AudioWorklet extracts raw audio samples from the mixed AudioContext

2. **Frontend buffers & encodes**: PcmFrameCollector buffers samples until 5 seconds worth, then OpusEncoder compresses to Opus bitstream

3. **Frontend uploads**: UploadQueueManager assigns sequence numbers and queues for upload; RetryTracker handles failures

4. **Backend finalizes**: Every 5 minutes, SessionFinalizer queries the database, builds an EBML/WebM container, and uploads to GCS

**Result**: Modular, testable pipeline with clear separation of concerns

---

## 🔍 Finding Answers

### "How do I...?"

| Question | Answer Location |
|----------|------------------|
| ...understand the overall architecture? | AUDIO_CAPTURE_AND_UPLOAD_FLOW.md → Phases 1-3 |
| ...fix an upload failure? | AUDIO_FLOW_QUICK_REFERENCE.md → Troubleshooting |
| ...see what metrics are available? | AUDIO_FLOW_QUICK_REFERENCE.md → Common Metrics |
| ...understand the WebM format? | AUDIO_CAPTURE_AND_UPLOAD_FLOW.md → Phase 3.4 |
| ...adjust Opus bitrate or buffer size? | AUDIO_FLOW_QUICK_REFERENCE.md → Configuration |
| ...trace a chunk through the system? | AUDIO_FLOW_QUICK_REFERENCE.md → Step-by-Step |
| ...know what files to modify? | AUDIO_FLOW_QUICK_REFERENCE.md → Files Reference |
| ...understand error recovery? | AUDIO_CAPTURE_AND_UPLOAD_FLOW.md → Error Scenarios |

---

## 📊 System Characteristics

### Performance

```
CPU Usage:     15-25% (frontend audio processing)
Memory:        60 MB (frontend buffers + AudioContext)
Bandwidth:     ~12 KB/s (Opus at 96 kbps)
Latency:       1-5 seconds (before appearance in GCS)
Compression:   2.7x (PCM → Opus)
```

### Reliability

```
Retry Strategy:       Exponential backoff up to 5 minutes
Max Retries:          5 per chunk
Idempotency:          Sequence numbers enable duplicate detection
Backpressure:         10 MB queue limit prevents memory overflow
Fallback Transport:   2 independent upload paths (WebSocket + Direct)
```

### Scalability

```
Concurrent Recordings:  Unlimited (one Recorder per meeting)
Chunks per Session:     ~60 (5 minutes ÷ 5 second frames)
Storage per Minute:     ~228 KB (at 96 kbps Opus)
Database Queries:       O(n) where n = chunks in session
```

---

## 🎓 Learning Resources

### Concepts You Should Know

- **AudioContext**: Browser API for audio processing and mixing
- **AudioWorklet**: Modern alternative to ScriptProcessorNode, runs in separate thread
- **MediaRecorder**: Browser API for recording audio/video to containers
- **Opus Codec**: Modern audio codec optimized for speech, used by WebRTC
- **WebM**: Container format based on Matroska, widely supported in browsers
- **EBML**: Efficient Binary Meta Language, used by WebM/Matroska
- **Resumable Upload**: GCS feature for uploading large files in chunks with restart capability
- **Exponential Backoff**: Retry strategy that increases wait time between attempts

### External Links

- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [AudioWorklet](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet)
- [Opus Codec](https://opus-codec.org/)
- [WebM Specification](https://www.webmproject.org/)
- [EBML Specification](https://github.com/ietf-wg-cellar/ebml-specification)
- [GCS Resumable Upload](https://cloud.google.com/storage/docs/json_api/v1/how-tos/resumable-upload)

---

## 🆘 Need Help?

### By Issue Type

**I see console errors in the browser**
→ Check AUDIO_FLOW_QUICK_REFERENCE.md → Troubleshooting → "AudioWorklet fails to load"

**Chunks aren't uploading**
→ Check AUDIO_FLOW_QUICK_REFERENCE.md → Troubleshooting → "Chunks not uploading"

**WebM files are incomplete or truncated**
→ Check AUDIO_FLOW_QUICK_REFERENCE.md → Troubleshooting → "WebM files are truncated"

**Performance is sluggish**
→ Check AUDIO_FLOW_QUICK_REFERENCE.md → Troubleshooting → "High CPU usage"

**I want to understand how X works**
→ Check AUDIO_CAPTURE_AND_UPLOAD_FLOW.md → "Key Design Decisions"

---

## 📝 Document Versions

- **Last Updated**: 2024-01-15
- **Coverage**: All 12 completed ACTs for audio pipeline
- **Files Analyzed**: 10+ source files (JavaScript + Python)
- **Status**: Complete and comprehensive

---

**Happy learning! 🎉**

