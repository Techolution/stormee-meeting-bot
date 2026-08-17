"""Google Meet platform implementation.

Layered so that Meet's habit of changing its UI stays contained:

  ``selectors.py``  Every DOM selector, named for intent.
  ``scripts/``      Browser-side JavaScript as real ``.js`` files.
  ``actions.py``    Individual UI operations — click, type, toggle.
  ``platform.py``   The flows those operations compose into.

A Meet redesign is normally a change to the first two only.
"""

from app.meeting_platform.google_meet.actions import GoogleMeetActions
from app.meeting_platform.google_meet.platform import GoogleMeetPlatform

__all__ = ["GoogleMeetActions", "GoogleMeetPlatform"]
