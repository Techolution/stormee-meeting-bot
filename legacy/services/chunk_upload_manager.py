"""Chunk upload manager for handling out-of-order audio chunks and resumable uploads.

Manages per-meeting upload sessions with chunk buffering, sequential ordering,
and integration with CW API for resumable uploads.
"""

import logging
from typing import Dict, Optional, List, Tuple, Set
from dataclasses import dataclass, field
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class UploadSession:
    """Tracks upload state for a single meeting."""
    meeting_id: str
    resumable_url: Optional[str] = None
    public_url: Optional[str] = None
    next_expected_chunk_id: int = 0
    buffered_chunks: Dict[int, dict] = field(default_factory=dict)  # chunk_id -> chunk_data
    uploaded_chunk_ids: Set[int] = field(default_factory=set)
    buffered_chunk_ids_in_upload_buffer: List[int] = field(default_factory=list)
    uploaded_bytes: int = 0  # Cumulative bytes uploaded to GCS via resumable protocol
    upload_buffer: bytearray = field(default_factory=bytearray)  # 256KB buffer for GCS resumable uploads
    total_uploaded_chunks: int = 0  # Count of actual uploads (not WebSocket chunks)
    is_finalizing: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ChunkUploadManager:
    """Manages audio chunk buffering and upload state for multiple meetings.
    
    Handles:
    - Per-meeting upload sessions with resumable URLs
    - Out-of-order chunk buffering and reordering
    - Sequential chunk upload tracking
    - Session finalization on recording end
    """
    
    def __init__(self, buffer_timeout_seconds: int = 30):
        """Initialize ChunkUploadManager.
        
        Args:
            buffer_timeout_seconds: Max time to wait for out-of-order chunks (default 30s)
        """
        self.sessions: Dict[str, UploadSession] = {}
        self.buffer_timeout_seconds = buffer_timeout_seconds

    @staticmethod
    def _extract_chunk_id(chunk: dict) -> int:
        """Extract the numeric suffix from a chunk identifier."""
        return int(chunk.get('chunkId', '').split('-')[-1])
    
    def get_or_create_session(self, meeting_id: str) -> UploadSession:
        """Get or create an upload session for a meeting.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            UploadSession: Existing or newly created session
        """
        if meeting_id not in self.sessions:
            self.sessions[meeting_id] = UploadSession(meeting_id=meeting_id)
            logger.info(f"Created new upload session: {meeting_id}")
        return self.sessions[meeting_id]
    
    def set_resumable_url(self, meeting_id: str, resumable_url: str, public_url: str) -> None:
        """Set the resumable upload URL for a meeting session.
        
        Called after fetching URL from CW API for first chunk.
        
        Args:
            meeting_id: Meeting identifier
            resumable_url: Resumable upload URL from backend
        """
        session = self.get_or_create_session(meeting_id)
        session.resumable_url = resumable_url
        session.public_url = public_url
        logger.debug(f"Set resumable URL for {meeting_id}")
    
    def buffer_chunk(self, meeting_id: str, chunk: dict) -> Tuple[bool, str]:
        """Buffer an incoming audio chunk.
        
        Handles out-of-order chunks by storing them until expected sequence is reached.
        
        Args:
            meeting_id: Meeting identifier
            chunk: Chunk dict with keys: meetingId, chunkId, timestamp, audioBlob
            
        Returns:
            Tuple of (is_sequential, status_message)
        """
        session = self.get_or_create_session(meeting_id)
        chunk_id = self._extract_chunk_id(chunk)

        if chunk_id in session.buffered_chunks or chunk_id in session.uploaded_chunk_ids:
            status = f"Duplicate chunk {chunk_id} ignored"
            logger.debug(f"[{meeting_id}] {status}")
            return False, status
        
        # Check if this is the expected next chunk
        is_sequential = (chunk_id == session.next_expected_chunk_id)

        # Always buffer the chunk first; draining happens in get_next_sequential_chunks.
        session.buffered_chunks[chunk_id] = chunk

        if is_sequential:
            status = f"Sequential chunk {chunk_id} (expected)"
        else:
            status = f"Out-of-order chunk {chunk_id} (expected {session.next_expected_chunk_id}), buffering"
        logger.debug(f"[{meeting_id}] {status}")
        
        return is_sequential, status
    
    def get_next_sequential_chunks(self, meeting_id: str) -> List[Tuple[int, dict]]:
        """Get chunks ready for upload in sequential order.
        
        Returns all consecutive chunks starting from next_expected_chunk_id.
        Stops at first gap in sequence.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            List of chunks ready to upload in order
        """
        session = self.get_or_create_session(meeting_id)
        ready_chunks: List[Tuple[int, dict]] = []
        current_id = session.next_expected_chunk_id
        
        while current_id in session.buffered_chunks:
            ready_chunks.append((current_id, session.buffered_chunks.pop(current_id)))
            session.next_expected_chunk_id = current_id + 1
            current_id += 1
        
        if ready_chunks:
            chunk_ids = [str(session.next_expected_chunk_id - len(ready_chunks) + i) for i in range(len(ready_chunks))]
            logger.debug(f"[{meeting_id}] {len(ready_chunks)} sequential chunks ready: {chunk_ids}")
        
        return ready_chunks
    
    def get_buffered_chunk_count(self, meeting_id: str) -> int:
        """Get count of buffered out-of-order chunks.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            Number of buffered chunks awaiting sequence
        """
        session = self.sessions.get(meeting_id)
        return len(session.buffered_chunks) if session else 0
    
    def track_uploaded_chunk(self, meeting_id: str, chunk_id: int) -> None:
        """Track that a chunk was successfully uploaded.
        
        Args:
            meeting_id: Meeting identifier
            chunk_id: Numeric chunk ID that was uploaded
        """
        session = self.sessions.get(meeting_id)
        if session:
            session.uploaded_chunk_ids.add(chunk_id)

    def requeue_chunks(self, meeting_id: str, chunks: List[Tuple[int, dict]]) -> None:
        """Restore a drained chunk batch after a failed upload attempt."""
        if not chunks:
            return

        session = self.sessions.get(meeting_id)
        if not session:
            return

        for chunk_id, chunk in chunks:
            if chunk_id not in session.uploaded_chunk_ids:
                session.buffered_chunks[chunk_id] = chunk

        first_chunk_id = chunks[0][0]
        session.next_expected_chunk_id = min(session.next_expected_chunk_id, first_chunk_id)

        logger.warning(
            f"[{meeting_id}] Re-queued {len(chunks)} chunk(s) after failed upload; "
            f"next_expected={session.next_expected_chunk_id}"
        )
    
    def get_session_stats(self, meeting_id: str) -> Dict[str, int]:
        """Get statistics for an upload session.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            Dict with uploaded_count, buffered_count, next_expected_id
        """
        session = self.sessions.get(meeting_id)
        if not session:
            return {'uploaded_count': 0, 'buffered_count': 0, 'next_expected_id': 0}
        
        return {
            'uploaded_count': len(session.uploaded_chunk_ids),
            'buffered_count': len(session.buffered_chunks),
            'next_expected_id': session.next_expected_chunk_id
        }
    
    def get_remaining_chunks(self, meeting_id: str) -> List[dict]:
        """Get all remaining buffered chunks (in any order).
        
        Used during session finalization to flush pending chunks.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            List of all buffered chunks
        """
        session = self.sessions.get(meeting_id)
        if not session:
            return []
        
        # Return chunks sorted by ID to maintain order
        chunks = [
            session.buffered_chunks[chunk_id]
            for chunk_id in sorted(session.buffered_chunks.keys())
        ]
        return chunks
    
    def finalize_session(self, meeting_id: str) -> Dict[str, int]:
        """Finalize a session and return statistics.
        
        Called when recording ends to prepare for final uploads.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            Session statistics at time of finalization
        """
        session = self.sessions.get(meeting_id)
        if not session:
            return {'uploaded_count': 0, 'buffered_count': 0, 'next_expected_id': 0}
        
        session.is_finalizing = True
        stats = {
            'uploaded_count': len(session.uploaded_chunk_ids),
            'buffered_count': len(session.buffered_chunks),
            'next_expected_id': session.next_expected_chunk_id
        }
        
        logger.info(
            f"[{meeting_id}] Finalizing session: "
            f"uploaded={stats['uploaded_count']}, "
            f"buffered={stats['buffered_count']}"
        )
        
        return stats
    
    def clear_session(self, meeting_id: str) -> None:
        """Clear session data after upload complete.
        
        Args:
            meeting_id: Meeting identifier
        """
        if meeting_id in self.sessions:
            del self.sessions[meeting_id]
            logger.info(f"Cleared upload session: {meeting_id}")
    
    def get_session(self, meeting_id: str) -> Optional[UploadSession]:
        """Get upload session for a meeting.
        
        Args:
            meeting_id: Meeting identifier
            
        Returns:
            UploadSession if exists, None otherwise
        """
        return self.sessions.get(meeting_id)


# Global instance
_chunk_manager: Optional[ChunkUploadManager] = None


def get_chunk_upload_manager() -> ChunkUploadManager:
    """Get or create global ChunkUploadManager instance.
    
    Returns:
        ChunkUploadManager: Singleton instance
    """
    global _chunk_manager
    if _chunk_manager is None:
        _chunk_manager = ChunkUploadManager()
    return _chunk_manager
