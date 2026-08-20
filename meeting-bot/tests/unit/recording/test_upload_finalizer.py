"""Tests for what happens after a recording lands.

Each segment is registered with CW as its own file, so when a meeting ends on a
segment boundary and leaves an empty tail, the question is whether the person
waiting still hears that the recording is ready.
"""

from __future__ import annotations

import pytest

from app.recording.chunk_uploader import UploadOutcome
from app.recording.models import RecordingContext, RecordingStats
from app.recording.upload_finalizer import UploadFinalizer
from tests.conftest import FakeCWClient, FakeMailClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def context() -> RecordingContext:
    return RecordingContext(
        meeting_id="meeting-1",
        project_id="project-test",
        meeting_title="Weekly Sync",
        user_name="Test User",
        user_email="test@example.com",
    )


def _uploaded(name: str = "recording.webm") -> UploadOutcome:
    return UploadOutcome(
        complete=True,
        uploaded_chunks=1,
        uploaded_bytes=1024,
        public_url=f"https://storage.test.invalid/public/{name}",
    )


def _nothing() -> UploadOutcome:
    return UploadOutcome(complete=False, detail="no audio was captured")


async def test_the_user_is_told_when_a_meeting_ends_on_a_segment_boundary(
    context: RecordingContext,
) -> None:
    """An empty final segment still ends a recording whose earlier parts landed."""
    mail = FakeMailClient()
    finalizer = UploadFinalizer(cw_client=FakeCWClient(), mail_client=mail)

    await finalizer.finalize(
        context, _uploaded(), stats=RecordingStats(),
        is_final_segment=False, segment_number=1,
    )
    registered = await finalizer.finalize(
        context, _nothing(), stats=RecordingStats(),
        is_final_segment=True, segment_number=2,
    )

    assert registered is False, "there is no file to register"
    assert len(mail.sent) == 1, "but the recording is finished and available"


async def test_a_recording_that_captured_nothing_sends_no_mail(
    context: RecordingContext,
) -> None:
    """Nothing was uploaded, so there is nothing to tell the user about."""
    mail = FakeMailClient()
    finalizer = UploadFinalizer(cw_client=FakeCWClient(), mail_client=mail)

    registered = await finalizer.finalize(context, _nothing(), stats=RecordingStats())

    assert registered is False
    assert mail.sent == []
