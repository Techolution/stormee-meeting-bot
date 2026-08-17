"""Tests for caption reassembly.

This is the most subtle logic in the codebase and the place a regression is
least likely to be noticed by hand — a transcript that is quietly wrong still
looks like a transcript. Each test names the caption behaviour it pins down.
"""

from __future__ import annotations

from app.transcription.caption_aggregator import CaptionAggregator
from app.transcription.models import TranscriptSource
from tests.conftest import caption


def test_growing_block_yields_one_segment_not_one_per_poll() -> None:
    """A speaker mid-sentence is one utterance, however many times it is polled."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "Let us")])
    aggregator.ingest([caption("Alice", "Let us start")])
    aggregator.ingest([caption("Alice", "Let us start the review")])

    # Nothing is emitted while the block is still on screen.
    assert aggregator.transcript() == []

    finished = aggregator.flush()
    assert len(finished) == 1
    assert finished[0].speaker == "Alice"
    assert finished[0].text == "Let us start the review"
    assert finished[0].source is TranscriptSource.CAPTION


def test_segment_completes_when_block_scrolls_away() -> None:
    """A block leaving the caption area is what ends an utterance."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "First point")])
    finished = aggregator.ingest([caption("Bob", "Second point")])

    assert [segment.text for segment in finished] == ["First point"]


def test_partial_redraw_does_not_truncate_text() -> None:
    """A momentary shorter reading must not shorten what was already captured."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "The quarterly numbers look strong")])
    aggregator.ingest([caption("Alice", "The quarterly")])

    assert aggregator.flush()[0].text == "The quarterly numbers look strong"


def test_scrolled_window_is_spliced_on_overlap() -> None:
    """When the platform drops the head of a long utterance, the tail is appended."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "we should ship the release on Friday")])
    # The visible window has scrolled: the start is gone, the end has grown.
    aggregator.ingest([caption("Alice", "the release on Friday afternoon")])

    assert aggregator.flush()[0].text == "we should ship the release on Friday afternoon"


def test_unrelated_text_from_same_speaker_starts_a_new_segment() -> None:
    """A speaker beginning a new sentence ends the previous one."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "Good morning everyone")])
    finished = aggregator.ingest([caption("Alice", "Completely different subject now")])

    assert [segment.text for segment in finished] == ["Good morning everyone"]
    assert aggregator.flush()[0].text == "Completely different subject now"


def test_short_coincidental_overlap_is_not_spliced() -> None:
    """A few shared characters are coincidence, not continuation."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "we agree")])
    finished = aggregator.ingest([caption("Alice", "ee totally unrelated")])

    # Splicing on "ee" would produce "we agreee totally unrelated".
    assert [segment.text for segment in finished] == ["we agree"]


def test_concurrent_speakers_are_tracked_independently() -> None:
    """Two people talking at once produce two separate utterances."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "I think"), caption("Bob", "Actually")])
    aggregator.ingest([caption("Alice", "I think we should"), caption("Bob", "Actually wait")])

    finished = aggregator.flush()
    by_speaker = {segment.speaker: segment.text for segment in finished}
    assert by_speaker == {"Alice": "I think we should", "Bob": "Actually wait"}


def test_empty_and_blank_captions_are_ignored() -> None:
    """Whitespace-only readings never become segments."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "   "), caption("Bob", "")])

    assert aggregator.flush() == []
    assert aggregator.transcript() == []


def test_transcript_is_ordered_by_time_spoken() -> None:
    """The transcript reads in the order things were said, not completed."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("Alice", "one")])
    aggregator.ingest([caption("Bob", "two")])
    aggregator.ingest([caption("Carol", "three")])
    aggregator.flush()

    assert [segment.text for segment in aggregator.transcript()] == ["one", "two", "three"]


def test_missing_speaker_is_labelled_rather_than_dropped() -> None:
    """Unattributed speech is still transcript."""
    aggregator = CaptionAggregator()

    aggregator.ingest([caption("", "someone said this")])

    assert aggregator.flush()[0].speaker == "Unknown"


def test_reset_clears_everything() -> None:
    aggregator = CaptionAggregator()
    aggregator.ingest([caption("Alice", "hello")])
    aggregator.flush()

    aggregator.reset()

    assert aggregator.transcript() == []
    assert aggregator.suppressed_count == 0
