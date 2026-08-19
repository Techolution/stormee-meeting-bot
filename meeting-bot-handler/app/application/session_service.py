"""Session lifecycle: the durable business state of a meeting.

Every state transition a session can make lives here, so the orchestrator reads
as a sequence of intents rather than a sequence of field assignments. This layer
never speaks HTTP; the bot pod is somebody else's problem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.domain.enums import BotStatus, MeetingStatus, RecordingStatus, TranscriptionStatus
from app.domain.exceptions import SessionAlreadyExistsError, SessionNotFoundError
from app.domain.models import BotSession, MeetingEvent, MeetingRecording
from app.repositories.session_repository import SessionRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionService:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

    # --- Creation and retrieval ----------------------------------------------
    async def create_session(self, session: BotSession) -> BotSession:
        existing = await self._repo.get_by_session_id(session.session_id)
        if existing is not None:
            raise SessionAlreadyExistsError(
                f"Session {session.session_id} already exists",
                details={"session_id": session.session_id},
            )

        session.meeting_status = MeetingStatus.CREATED
        session.bot_status = BotStatus.PENDING
        session.created_at = session.created_at or _now()
        session.updated_at = session.created_at
        created = await self._repo.create(session)
        await self.record_event(created, "session.created", {"meeting_id": created.meeting_id})
        return created

    async def get_session(self, session_id: str) -> Optional[BotSession]:
        return await self._repo.get_by_session_id(session_id)

    async def require_session(self, session_id: str) -> BotSession:
        """Fetch a session or raise, so callers stop re-writing the same guard."""
        session = await self._repo.get_by_session_id(session_id)
        if session is None:
            raise SessionNotFoundError(
                f"Session '{session_id}' does not exist",
                details={"session_id": session_id},
            )
        return session

    async def get_by_meeting_id(self, meeting_id: str) -> Optional[BotSession]:
        return await self._repo.get_by_meeting_id(meeting_id)

    async def list_sessions(self, active_only: bool = False) -> List[BotSession]:
        return await self._repo.list_sessions(active_only=active_only)

    async def update_session(self, session: BotSession) -> BotSession:
        session.updated_at = _now()
        return await self._repo.update(session)

    # --- Bot assignment -------------------------------------------------------
    async def assign_bot(
        self,
        session: BotSession,
        service_url: str,
        pod_name: Optional[str] = None,
        pod_ip: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> BotSession:
        session.service_url = service_url
        session.pod_name = pod_name
        session.pod_ip = pod_ip
        session.worker_id = worker_id or pod_name
        await self.record_event(
            session, "bot.assigned", {"pod_name": pod_name, "service_url": service_url}
        )
        return await self.update_session(session)

    async def clear_assignment(self, session: BotSession) -> BotSession:
        session.service_url = None
        session.pod_name = None
        session.pod_ip = None
        session.worker_id = None
        return await self.update_session(session)

    # --- Meeting lifecycle transitions ---------------------------------------
    async def mark_starting(self, session: BotSession) -> BotSession:
        session.meeting_status = MeetingStatus.STARTING
        session.bot_status = BotStatus.STARTING
        session.starting_at = session.starting_at or _now()
        return await self.update_session(session)

    async def mark_started(self, session: BotSession, bot_session_id: Optional[str] = None) -> BotSession:
        session.meeting_status = MeetingStatus.ACTIVE
        session.bot_status = BotStatus.RUNNING
        session.started_at = session.started_at or _now()
        if bot_session_id:
            session.bot_session_id = bot_session_id
        await self.record_event(session, "meeting.active", {"bot_session_id": bot_session_id})
        return await self.update_session(session)

    async def mark_leaving(self, session: BotSession) -> BotSession:
        session.meeting_status = MeetingStatus.LEAVING
        session.bot_status = BotStatus.STOPPING
        session.leaving_at = _now()
        return await self.update_session(session)

    async def mark_completed(self, session: BotSession) -> BotSession:
        session.meeting_status = MeetingStatus.COMPLETED
        session.bot_status = BotStatus.STOPPED
        session.completed_at = _now()
        if session.active_recording_status == RecordingStatus.RECORDING:
            # leave finalizes a running recording on the bot side.
            session.active_recording_status = RecordingStatus.STOPPED
        if session.transcription_status == TranscriptionStatus.RUNNING:
            session.transcription_status = TranscriptionStatus.COMPLETED
        await self.record_event(session, "meeting.completed", {})
        return await self.update_session(session)

    async def mark_failed(self, session: BotSession, error: str) -> BotSession:
        session.meeting_status = MeetingStatus.FAILED
        session.bot_status = BotStatus.FAILED
        session.failed_at = _now()
        session.last_error = error
        await self.record_event(session, "meeting.failed", {"error": error})
        return await self.update_session(session)

    # --- Recording ------------------------------------------------------------
    async def create_recording(self, session: BotSession, status: RecordingStatus) -> MeetingRecording:
        recording = MeetingRecording(
            recording_id=uuid.uuid4().hex,
            session_id=session.session_id,
            meeting_id=session.meeting_id,
            status=status,
            started_at=_now(),
            created_at=_now(),
        )
        return await self._repo.add_recording(recording)

    async def get_active_recording(self, session_id: str) -> Optional[MeetingRecording]:
        return await self._repo.get_active_recording(session_id)

    async def update_recording(self, recording: MeetingRecording) -> MeetingRecording:
        return await self._repo.update_recording(recording)

    async def set_recording_status(self, session: BotSession, status: RecordingStatus) -> BotSession:
        session.active_recording_status = status
        return await self.update_session(session)

    async def set_transcription_status(self, session: BotSession, status: TranscriptionStatus) -> BotSession:
        session.transcription_status = status
        return await self.update_session(session)

    # --- Events ---------------------------------------------------------------
    async def record_event(self, session: BotSession, event_type: str, payload: dict) -> MeetingEvent:
        event = MeetingEvent(
            event_id=uuid.uuid4().hex,
            session_id=session.session_id,
            event_type=event_type,
            payload=payload,
            created_at=_now(),
        )
        return await self._repo.add_event(event)
