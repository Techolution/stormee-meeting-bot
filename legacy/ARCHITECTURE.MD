# Meeting Bot Architechure
```text
                         ┌──────────────────────────────┐
                         │        Python Bot            │
                         │                              │
                         │  TTS / generated audio       │
                         └──────────────┬───────────────┘
                                        │
                                        │ audio URL / data URL
                                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         PLAYWRIGHT PAGE                              │
│                                                                      │
│  INITIALIZE_SEPRATE_AUDIO_CHANNELS_FOR_REMOTE_AND_INPUT              │
│                                                                      │
│  ┌──────────────────── VIRTUAL MICROPHONE ────────────────────────┐  │
│  │                                                                │  │
│  │  HTMLAudioElement                                              │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │  MediaElementSource                                            │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │  Mic Gain                                                      │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │  MediaStreamDestination                                        │  │
│  │       │                                                        │  │
│  │       │ stream                                                  │  │
│  │       ├───────────────────────┐                                │  │
│  │       │                       │                                │  │
│  │       ▼                       ▼                                │  │
│  │  getUserMedia()          Recording Mixer                       │  │
│  │       │                       │                                │  │
│  │       ▼                       │                                │  │
│  │   Google Meet                │                                │  │
│  │   microphone                │                                │  │
│  │                               │                                │  │
│  └───────────────────────────────┼────────────────────────────────┘  │
│                                  │                                   │
│                                  │                                   │
│  ┌────────────────── REMOTE WEBRTC AUDIO ─────────────────────────┐  │
│  │                                                                │  │
│  │   Google Meet                                                  │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │   RTCPeerConnection                                            │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │   "track" event                                                │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │   remoteAudioStreams[]                                         │  │
│  │       │                                                        │  │
│  │       ├───────────────────────┐                                │  │
│  │       │                       │                                │  │
│  │       ▼                       ▼                                │  │
│  │   Remote processing     Recording Mixer                        │  │
│  │                                                                │  │
│  └───────────────────────────────┼────────────────────────────────┘  │
│                                  │                                   │
│                                  ▼                                   │
│                    ┌─────────────────────────┐                       │
│                    │   Recording AudioContext│                       │
│                    │                         │                       │
│                    │  Bot audio ───────┐     │                       │
│                    │                    ├──→ Mixer                    │
│                    │  Remote audio ─────┘     │                       │
│                    │                         │                       │
│                    └────────────┬────────────┘                       │
│                                 │                                    │
│                                 ▼                                    │
│                    MediaStreamDestination                            │
│                                 │                                    │
│                                 ▼                                    │
│                         Mixed Audio Track                             │
│                                 │                                    │
│                                 ▼                                    │
│                          MediaRecorder                               │
│                         audio/webm;opus                               │
│                                 │                                    │
│                         every 5 seconds                              │
│                                 │                                    │
│                                 ▼                                    │
│                        sendAudioChunkToPython                         │
│                                                                      │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   │ Playwright expose_function
                                   ▼
                         ┌─────────────────────┐
                         │       Python        │
                         │                     │
                         │ _handle_audio_chunk │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ WebSocket Manager   │
                         └──────────┬──────────┘
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                    Connected             Offline
                          │                   │
                          ▼                   ▼
                    WebSocket          Audio Queue
                          │                   │
                          │            reconnect
                          │                   │
                          └─────────┬─────────┘
                                    ▼
                              Backend Server
```

## The three independent pipelines

The important part is that you now have **three separate responsibilities**.

### 1. Bot audio → Meet

```text
Python
  ↓
play_audio_url()
  ↓
__meetingAudio.playIntoMic()
  ↓
HTMLAudioElement
  ↓
Web Audio API
  ↓
MediaStreamDestination
  ↓
virtual microphone MediaStreamTrack
  ↓
getUserMedia override
  ↓
Google Meet
```

This controls **what Meet hears from your bot**.

---

### 2. Meet remote audio → your application

```text
Google Meet
  ↓
RTCPeerConnection
  ↓
track event
  ↓
remoteAudioStreams[]
```

This gives you the participants' audio.

Your existing interception:

```javascript
pc.addEventListener("track", ...)
```

is responsible for this.

You should **not route remote audio through the virtual microphone**.

---

### 3. Recording

This is the new piece:

```text
Bot virtual mic stream ─────┐
                            │
                            ▼
                    Recording AudioContext
                            ▲
                            │
Remote WebRTC streams ──────┘
                            │
                            ▼
                  MediaStreamDestination
                            │
                            ▼
                       MediaRecorder
                            │
                            ▼
                     WebM / Opus
                            │
                       5 sec chunks
                            │
                            ▼
                       Python
```

So your recording contains:

```text
┌──────────────────────────────┐
│        FINAL RECORDING       │
│                              │
│  🔊 Bot speech               │
│  🔊 Participant 1            │
│  🔊 Participant 2            │
│  🔊 Participant N            │
│                              │
│       ↓ mixed together       │
│                              │
│       WebM / Opus            │
└──────────────────────────────┘
```

## Your key browser objects

I'd keep the browser state organized roughly like this:

```javascript
window.__meetingAudio
```

owns the **virtual microphone**:

```text
__meetingAudio
├── initializeVirtualMic()
├── playIntoMic(url)
├── stopMic()
├── setMicVolume(volume)
├── getVirtualMicStream()
└── getMicState()
```

Then:

```javascript
window.remoteAudioStreams
```

owns **remote Meet audio**:

```text
remoteAudioStreams[]
├── participant/stream 1
├── participant/stream 2
└── participant/stream N
```

And:

```javascript
window.recordingAudioContext
window.recordingDestination
window.mediaRecorder
```

own **recording**.

That separation is important.

---

# Lifecycle

Your initialization sequence should be:

```text
1. Launch Chromium
        ↓
2. add_init_script()
        ↓
3. Install getUserMedia override
        ↓
4. Install RTCPeerConnection wrapper
        ↓
5. Create/navigate Meet page
        ↓
6. Meet initializes WebRTC
        ↓
7. Remote tracks arrive
        ↓
8. remoteAudioStreams[] populated
        ↓
9. initializeVirtualMic()
        ↓
10. start_audio_recording()
        ↓
11. Recording mixer connects:
       ├── virtual mic stream
       └── remote streams
        ↓
12. MediaRecorder.start(5000)
        ↓
13. Bot calls play_audio_url()
        ↓
14. Bot audio goes to:
       ├── Meet
       └── recorder
        ↓
15. Remote audio goes to:
       ├── Meet's normal playback
       └── recorder
        ↓
16. WebM chunks → Python
        ↓
17. WebSocket → backend
```

## One thing I'd be particularly careful about

Don't make this:

```text
Bot audio
   ↓
virtual microphone
   ↓
Meet
   ↓
capture Meet's microphone somehow
   ↓
recording
```

Instead do:

```text
                 ┌──→ Meet
                 │
Bot audio ───────┤
                 │
                 └──→ Recorder
```

That's much cleaner and avoids feedback/echo/loop problems.

Likewise:

```text
Remote audio
    ├──→ normal Meet playback
    └──→ Recorder
```

rather than trying to capture the browser's final speaker output.

---

### In short

Your final design is:

```text
                    BOT AUDIO
                       │
                       ▼
                Virtual Mic Pipeline
                  │            │
                  │            └──────────────┐
                  ▼                           │
               Google Meet                   │
                                              ▼
REMOTE WEBRTC ──→ remoteAudioStreams ──→ RECORDING MIXER
                                              ▲
                                              │
                           ┌──────────────────┘
                           │
                           ▼
                    MediaRecorder
                           │
                    WebM/Opus chunks
                           │
                           ▼
                         Python
                           │
                           ▼
                       WebSocket
                           │
                           ▼
                        Backend
```