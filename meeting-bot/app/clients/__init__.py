"""Clients for services this bot depends on.

Every network boundary lives here. Domain code calls a client method with typed
arguments; it never builds a URL, chooses a header, or knows an upstream
payload shape. That is what makes the domain testable with a fake and what
makes an upstream contract change a single-file edit.
"""

from app.clients.audio_service import AudioServiceClient
from app.clients.cw_utils import CWUtilsClient, ResumableUploadTarget, UploadedFile
from app.clients.mail import MailClient
from app.clients.meeting_api import MeetingAPIClient
from app.clients.object_storage import ResumableUploadClient, ResumableUploadState

__all__ = [
    "AudioServiceClient",
    "CWUtilsClient",
    "MailClient",
    "MeetingAPIClient",
    "ResumableUploadClient",
    "ResumableUploadState",
    "ResumableUploadTarget",
    "UploadedFile",
]
