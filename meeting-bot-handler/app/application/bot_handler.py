from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
import uuid
import httpx

from app.application.bot_client import BotClient
from app.application.bot_service_resolver import BotServiceResolver
from app.application.session_service import SessionService
from app.domain.enums import BotSessionStatus, RecordingStatus, TranscriptionStatus
from app.domain.models import MeetingRecording
from app.domain.exceptions import (
    InvalidSessionStateError,
    SessionNotFoundError,
)

logger = logging.getLogger(__name__)


class BotHandler:
    """Control plane application orchestrator."""

    def __init__(
        self,
        session_service: SessionService,
        bot_resolver: BotServiceResolver,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self._session_service = session_service
        self.bot_resolver = bot_resolver
        self.http_client = http_client or httpx.AsyncClient(timeout=30.0)

    def _get_client(self, session: Any) -> BotClient:
        target = self.bot_resolver.resolve(session)
        return BotClient(service_url=target.service_url, http_client=self.http_client)

    async def start_bot(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)
        
        # Mark session as starting
        session.status = BotSessionStatus.STARTING
        await self._session_service.update_session(session)

        # Send join request (Worker returns HTTP 202 Accepted)
        res = await client.join_meeting(
            meeting_id=session.meeting_id,
            meeting_url=session.meeting_url,
            user_name=getattr(session, "user_name", None),
            user_email=getattr(session, "user_email", None),
            project_id=getattr(session, "project_id", None),
            project_name=getattr(session, "project_name", None),
            meeting_title=getattr(session, "meeting_title", None),
        )

        return {"status": "STARTING", "session_id": session_id, "result": res}

    async def start_recording(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)

        # 1. Dispatch start command to worker pod
        res = await client.start_recording(session.meeting_id)

        # 2. Track new entry in meeting_recordings table
        recording = MeetingRecording(
            recording_id=uuid.uuid4().hex,
            session_id=session.session_id,
            meeting_id=session.meeting_id,
            status=RecordingStatus.RECORDING,
            started_at=datetime.now(timezone.utc),
        )
        await self._session_service.create_recording(recording)

        # 3. Update top-level session active recording status
        session.active_recording_status = RecordingStatus.RECORDING
        await self._session_service.update_session(session)

        return {"status": "RECORDING", "recording_id": recording.recording_id, "detail": res}


    async def stop_recording(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)

        # 1. Dispatch stop command to worker pod
        res = await client.stop_recording(session.meeting_id)

        # 2. Get active recording take and update status/metrics
        active_rec = await self._session_service.get_active_recording(session_id)
        if active_rec:
            # Reconcile final stats from GET /recordings/{meetingId}/status
            rec_status = await client.get_recording_status(session.meeting_id)
            active_rec.status = RecordingStatus.STOPPED
            active_rec.stopped_at = datetime.now(timezone.utc)
            active_rec.chunks_uploaded = rec_status.get("chunksUploaded", 0)
            active_rec.bytes_uploaded = rec_status.get("bytesUploaded", 0)
            await self._session_service.update_recording(active_rec)

        # 3. Update top-level session
        session.active_recording_status = RecordingStatus.STOPPED
        await self._session_service.update_session(session)

        return {"status": "STOPPED", "session_id": session_id, "detail": res}

    async def start_transcription(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)
        
        res = await client.start_transcription(session.meeting_id)
        
        session.transcription_status = TranscriptionStatus.RUNNING
        await self._session_service.update_session(session)
        return res

    async def stop_transcription(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)
        
        res = await client.stop_transcription(session.meeting_id)
        
        session.transcription_status = TranscriptionStatus.COMPLETED
        await self._session_service.update_session(session)
        return res

    async def leave(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        client = self._get_client(session)
        
        session.status = BotSessionStatus.LEAVING
        await self._session_service.update_session(session)

        res = await client.leave_meeting(session.meeting_id)

        session.status = BotSessionStatus.COMPLETED
        await self._session_service.update_session(session)
        return res

    async def stop(self, session_id: str) -> Dict[str, Any]:
        return await self.leave(session_id)

    async def get_status(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_service.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' does not exist.")

        # Reconcile runtime worker status with DB
        try:
            client = self._get_client(session)
            runtime_status = await client.get_meeting_status(session.meeting_id)
            
            # Map session_state from worker to DB status if active
            if runtime_status.get("session_state") == "in_meeting":
                session.status = BotSessionStatus.RUNNING
                await self._session_service.update_session(session)
        except Exception as e:
            logger.warning(f"Could not reach bot worker for status reconciliation: {e}")
            runtime_status = None

        return {
            "session_id": session.session_id,
            "meeting_id": session.meeting_id,
            "status": session.status.value if hasattr(session.status, "value") else str(session.status),
            "runtime": runtime_status,
        }