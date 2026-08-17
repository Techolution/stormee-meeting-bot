"""Meeting orchestration — the core domain.

:class:`MeetingManager` is the application's single entry point into meeting
behaviour; :class:`MeetingSession` runs one meeting by coordinating the browser,
platform, recording, transcription and streaming components.

Both are orchestrators. Neither performs I/O against a browser, a socket or an
HTTP API directly — that work lives in the packages they compose, which is what
keeps this layer readable as a description of what the bot does.
"""

from app.meeting.chat_monitor import ChatMonitor
from app.meeting.lifecycle import LifecycleRunner, LifecycleStep
from app.meeting.meeting_manager import MeetingManager
from app.meeting.meeting_session import MeetingSession
from app.meeting.models import MeetingRequest
from app.meeting.participant_monitor import ParticipantMonitor
from app.meeting.session_dependencies import SessionDependencies

__all__ = [
    "ChatMonitor",
    "LifecycleRunner",
    "LifecycleStep",
    "MeetingManager",
    "MeetingRequest",
    "MeetingSession",
    "ParticipantMonitor",
    "SessionDependencies",
]
