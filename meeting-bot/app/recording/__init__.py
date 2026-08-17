"""Audio recording: capture, buffering, ordering, upload.

The pipeline, in order:

    page MediaRecorder
        -> AudioCapture      parse and count
        -> Recorder          orchestrate
        -> ChunkUploader     persist (streamed, or direct to storage)
        -> UploadFinalizer   register, derive artifacts, notify

Each stage is replaceable. Swapping the upload transport does not touch the
recorder; changing what happens after a recording does not touch the uploader.
"""

from app.recording.audio_buffer import AudioBuffer
from app.recording.audio_capture import AudioCapture
from app.recording.chunk_uploader import (
    ChunkUploader,
    DirectChunkUploader,
    StreamingChunkUploader,
    UploadOutcome,
)
from app.recording.models import (
    AudioChunk,
    RecordingContext,
    RecordingStats,
    RecordingStatus,
)
from app.recording.recorder import Recorder
from app.recording.sequencer import ChunkSequencer
from app.recording.upload_finalizer import UploadFinalizer

__all__ = [
    "AudioBuffer",
    "AudioCapture",
    "AudioChunk",
    "ChunkSequencer",
    "ChunkUploader",
    "DirectChunkUploader",
    "Recorder",
    "RecordingContext",
    "RecordingStats",
    "RecordingStatus",
    "StreamingChunkUploader",
    "UploadFinalizer",
    "UploadOutcome",
]
