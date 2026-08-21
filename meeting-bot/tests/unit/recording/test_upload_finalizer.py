"""Tests for what happens after a recording lands.

Each segment is registered with CW as its own file, so when a meeting ends on a
segment boundary and leaves an empty tail, the question is whether the person
waiting still hears that the recording is ready.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.recording.chunk_uploader import UploadOutcome
from app.recording.models import RecordingContext, RecordingStats
from app.recording.highlights_manager import HighlightsManager
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


# --------------------------------------------------------------------------
# One artifact per segment
# --------------------------------------------------------------------------


def _highlights(cw: FakeCWClient) -> HighlightsManager:
    """As bootstrap builds it: no minimum duration, so no segment is skipped."""
    return HighlightsManager(cw_client=cw, min_duration_seconds=0.0)


async def test_every_segment_of_a_meeting_gets_its_own_artifact(
    context: RecordingContext,
) -> None:
    """The point of segmenting: highlights arrive while the meeting is running.

    Before, an intermediate segment fell into a branch that logged a line and
    requested nothing, so a two-hour meeting produced one artifact at the very
    end rather than one per part.
    """
    cw = FakeCWClient()
    finalizer = UploadFinalizer(cw_client=cw, highlights_manager=_highlights(cw))
    stats = RecordingStats(started_at=datetime.now(timezone.utc) - timedelta(minutes=45))

    for segment in (1, 2):
        await finalizer.finalize(
            context, _uploaded(f"part{segment}.webm"), stats=stats,
            is_final_segment=False, segment_number=segment,
            generate_incremental_highlights=True,
        )
    await finalizer.finalize(
        context, _uploaded("part3.webm"), stats=stats,
        is_final_segment=True, segment_number=3,
        generate_incremental_highlights=True,
    )

    assert len(cw.artifacts) == 3, "one artifact per uploaded segment"
    assert [call["audio_name"] for call in cw.artifacts] == [
        "part1.webm", "part2.webm", "part3.webm",
    ], "each artifact must point at its own segment's audio"


async def test_each_segment_artifact_is_requested_under_its_own_id(
    context: RecordingContext,
) -> None:
    """Distinct request ids are what stop CW treating these as one job."""
    cw = FakeCWClient()
    finalizer = UploadFinalizer(cw_client=cw, highlights_manager=_highlights(cw))
    stats = RecordingStats(started_at=datetime.now(timezone.utc) - timedelta(minutes=30))

    for segment in (1, 2):
        await finalizer.finalize(
            context, _uploaded(f"part{segment}.webm"), stats=stats,
            is_final_segment=segment == 2, segment_number=segment,
            generate_incremental_highlights=True,
        )

    ids = [call.get("request_id") for call in cw.artifacts]
    assert ids == ["meeting-1-segment-1", "meeting-1-segment-2"]
    assert len(set(ids)) == len(ids)


async def test_a_short_trailing_segment_is_not_skipped(
    context: RecordingContext,
) -> None:
    """A meeting ending a few seconds after a cut still has a last part."""
    cw = FakeCWClient()
    finalizer = UploadFinalizer(cw_client=cw, highlights_manager=_highlights(cw))
    stats = RecordingStats(started_at=datetime.now(timezone.utc) - timedelta(seconds=20))

    await finalizer.finalize(
        context, _uploaded("tail.webm"), stats=stats,
        is_final_segment=True, segment_number=2,
        generate_incremental_highlights=True,
    )

    assert len(cw.artifacts) == 1


async def test_without_the_flag_a_recording_still_gets_one_artifact(
    context: RecordingContext,
) -> None:
    """The unsegmented path is unchanged."""
    cw = FakeCWClient()
    finalizer = UploadFinalizer(cw_client=cw, highlights_manager=_highlights(cw))

    await finalizer.finalize(context, _uploaded(), stats=RecordingStats())

    assert len(cw.artifacts) == 1
