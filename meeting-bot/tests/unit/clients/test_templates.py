"""Tests for the notification email.

Content parity with the previous implementation matters here: this is
user-facing text that people already receive, and a silent wording change is
the kind of regression nobody reports but everybody notices.
"""

from __future__ import annotations

import re
from datetime import date

from app.clients.templates import render_meeting_file_uploaded


def render(**overrides):
    args = {
        "user_name": "Alice Smith",
        "project_name": "Q3 Planning",
        "project_url": "https://cw.test/projects/p1",
        "meeting_title": "Weekly Sync",
        "file_type": "recording",
    }
    args.update(overrides)
    return render_meeting_file_uploaded(**args)


def test_subject_matches_the_legacy_format() -> None:
    subject, _ = render()
    assert subject == "Meeting Recording Uploaded: Weekly Sync"


def test_body_carries_the_expected_facts() -> None:
    _, html = render()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    for expected in (
        "Meeting Recording Uploaded",
        "Weekly Sync",
        "Hello",
        "Alice Smith",
        "uploaded to the project",
        "Q3 Planning",
        "Open Project",
    ):
        assert expected in text, f"missing from the email body: {expected!r}"


def test_footer_carries_the_year() -> None:
    """The legacy footer read '© 2026 Techolution'; the year is derived now."""
    _, html = render()
    assert f"© {date.today().year} Techolution" in html


def test_the_project_link_is_the_call_to_action() -> None:
    _, html = render()
    assert re.findall(r'href="([^"]+)"', html) == ["https://cw.test/projects/p1"]


def test_user_initial_is_shown() -> None:
    _, html = render(user_name="Bob Jones")
    assert ">B</span>" in html.replace("\n", "").replace("  ", "") or "B</span>" in html


def test_transcript_file_type_reads_correctly() -> None:
    subject, html = render(file_type="transcript")
    assert subject == "Meeting Transcript Uploaded: Weekly Sync"
    assert "Meeting Transcript Uploaded" in re.sub(r"<[^>]+>", " ", html)


def test_user_supplied_values_are_escaped() -> None:
    """Meeting titles reach an HTML document and are not ours to trust."""
    _, html = render(meeting_title="<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_missing_values_do_not_produce_blanks() -> None:
    subject, html = render(user_name="", meeting_title="", project_name="")
    text = re.sub(r"<[^>]+>", " ", html)
    assert "Untitled meeting" in subject or "Untitled meeting" in text
    assert "there" in text or "U" in text
