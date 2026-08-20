"""Integration-ish test for Recorder segment uploads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from app.recording.recorder import Recorder
from app.recording.chunk_uploader import DirectChunkUploader
from app.recording.upload_finalizer import UploadFinalizer
from app.recording.models import RecordingContext, RecordingStats
from tests.conftest import FakePlatform, FakeCWClient, FakeStorage, make_chunk


pytestmark = pytest.mark.asyncio


async def test_recorder_auto_segment_triggers_finalizer() -> None:
    platform = FakePlatform()
    cw = FakeCWClient()
    storage = FakeStorage()

    context = RecordingContext(meeting_id="rec-int-1", project_id="project-test")

    uploader = DirectChunkUploader(cw_client=cw, storage=storage, stats=RecordingStats())
    finalizer = UploadFinalizer(cw_client=cw)

    # Set max_duration_seconds small so the first chunk triggers segment upload.
    recorder = Recorder(platform=platform, uploader=uploader, context=context, finalizer=finalizer, max_duration_seconds=1)

    await recorder.start()

    # Simulate recording started in the past so duration threshold is met.
    recorder._stats.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)

    # Send one chunk which should be uploaded and cause auto-segmentation.
    await recorder._on_chunk(make_chunk(0, size=256))

    # Give background tasks a moment to run (finalizer runs in background).
    await asyncio.sleep(0.1)

    # CW client should have recorded a confirm_upload call for the segment.
    assert cw.confirmed, "expected the finalizer to confirm the upload with CW"
