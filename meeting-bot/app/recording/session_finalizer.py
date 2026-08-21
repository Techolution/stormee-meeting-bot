"""Session Finalizer - Constructs WebM containers from Opus sequences.

Receives session finalization events from frontend with sequence ranges,
retrrieves Opus packets from database, and constructs playable WebM files.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import struct

logger = logging.getLogger(__name__)


@dataclass
class SessionFinalizationEvent:
    """Received when frontend session finishes (5 minutes or recording stop)."""
    meeting_id: str
    upload_session_id: str
    start_time: datetime
    end_time: datetime
    sequence_range: dict  # {"start": int, "end": int}
    duration_ms: int
    chunk_count: int
    byte_count: int
    status: str  # "complete"


class WebMBuilder:
    """Constructs EBML/WebM containers from Opus audio packets.
    
    WebM is Matroska container with EBML header and audio tracks.
    Used for playback across browsers without codec-specific handling.
    """
    
    # EBML element IDs (in hex, big-endian)
    EBML_HEADER = 0x1A45DFA3
    SEGMENT = 0x18538067
    INFO = 0x1549A966
    TRACKS = 0x1654AE6B
    CLUSTER = 0x1F43B675
    TIMESTAMP_BLOCK = 0xA3  # Block ID in cluster
    SIMPLE_BLOCK = 0xA3
    TRACK = 0xAE
    TRACK_NUMBER = 0xD7
    TRACK_UID = 0x73C5
    TRACK_TYPE = 0x83
    CODEC_ID = 0x86
    CODEC_NAME = 0x258688
    AUDIO = 0xE1
    SAMPLE_RATE = 0xB5
    CHANNELS = 0x9F
    BIT_DEPTH = 0x6264
    
    # Opus codec constants
    CODEC_OPUS = "A_OPUS"
    TRACK_TYPE_AUDIO = 1
    SAMPLE_RATE_OPUS = 48000  # Opus internal rate
    CHANNELS_MONO = 1
    
    def __init__(self):
        """Initialize WebM builder."""
        self.buffer = io.BytesIO()
        self.packets: list[bytes] = []
        self.duration_ms = 0
        self.first_packet_timestamp = 0
        
    def add_opus_packet(self, packet_data: bytes, timestamp_ms: int) -> None:
        """Add an Opus encoded packet.
        
        Args:
            packet_data: Raw Opus frame bytes
            timestamp_ms: Packet timestamp in milliseconds
        """
        self.packets.append((packet_data, timestamp_ms))
        self.duration_ms = max(self.duration_ms, timestamp_ms + 20)  # ~20ms per frame
    
    def _encode_vint(self, value: int, width: int = 1) -> bytes:
        """Encode variable-length integer (VINT) for EBML.
        
        Args:
            value: Integer to encode
            width: Number of bytes to use
        """
        if width == 1:
            return bytes([value & 0xFF])
        elif width == 2:
            return struct.pack(">H", value & 0xFFFF)
        elif width == 4:
            return struct.pack(">I", value & 0xFFFFFFFF)
        else:
            raise ValueError(f"Unsupported VINT width: {width}")
    
    def _encode_element_id(self, element_id: int) -> bytes:
        """Encode EBML element ID."""
        if element_id < 256:
            return bytes([element_id])
        elif element_id < 65536:
            return struct.pack(">H", element_id)
        else:
            return struct.pack(">I", element_id)
    
    def _write_element(self, element_id: int, data: bytes) -> bytes:
        """Write an EBML element: ID + size + data."""
        element_bytes = self._encode_element_id(element_id)
        size_bytes = self._encode_vint(len(data), width=1)
        return element_bytes + size_bytes + data
    
    def _build_ebml_header(self) -> bytes:
        """Build EBML header element."""
        header_data = io.BytesIO()
        
        # EBMLVersion (1)
        header_data.write(self._write_element(0x4286, b"\x01"))
        
        # EBMLReadVersion (1)
        header_data.write(self._write_element(0x42F7, b"\x01"))
        
        # EBMLMaxIDLength (4)
        header_data.write(self._write_element(0x42F2, b"\x04"))
        
        # EBMLMaxSizeLength (8)
        header_data.write(self._write_element(0x42F3, b"\x08"))
        
        # DocType ("webm")
        header_data.write(self._write_element(0x4282, b"webm"))
        
        # DocTypeVersion (4)
        header_data.write(self._write_element(0x4287, b"\x04"))
        
        # DocTypeReadVersion (2)
        header_data.write(self._write_element(0x4285, b"\x02"))
        
        header_bytes = header_data.getvalue()
        return self._write_element(self.EBML_HEADER, header_bytes)
    
    def _build_info(self) -> bytes:
        """Build Info element (segment metadata)."""
        info_data = io.BytesIO()
        
        # TimecodeScale (1000000 = 1ms)
        info_data.write(self._write_element(0x2AD7B1, struct.pack(">I", 1000000)))
        
        # Duration (in timecode units, so milliseconds)
        duration_bytes = struct.pack(">d", float(self.duration_ms))
        info_data.write(self._write_element(0x4489, duration_bytes))
        
        # WritingApp
        info_data.write(self._write_element(0x5741, b"meeting-bot-opus"))
        
        # DateUTC (nanoseconds since 2001-01-01)
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        info_data.write(self._write_element(0x4461, struct.pack(">Q", now_ns)))
        
        info_bytes = info_data.getvalue()
        return self._write_element(self.INFO, info_bytes)
    
    def _build_tracks(self) -> bytes:
        """Build Tracks element (audio track definition)."""
        track_data = io.BytesIO()
        
        # TrackNumber (1)
        track_data.write(self._write_element(0xD7, b"\x01"))
        
        # TrackUID (1)
        track_data.write(self._write_element(0x73C5, b"\x01"))
        
        # TrackType (audio = 1)
        track_data.write(self._write_element(0x83, b"\x01"))
        
        # CodecID ("A_OPUS")
        track_data.write(self._write_element(0x86, b"A_OPUS"))
        
        # Audio element
        audio_data = io.BytesIO()
        
        # SamplingFrequency (Opus is 48kHz internally)
        audio_data.write(self._write_element(0xB5, struct.pack(">d", 48000.0)))
        
        # Channels (mono = 1)
        audio_data.write(self._write_element(0x9F, b"\x01"))
        
        audio_bytes = audio_data.getvalue()
        track_data.write(self._write_element(self.AUDIO, audio_bytes))
        
        track_bytes = track_data.getvalue()
        
        # Wrap in TrackEntry
        tracks_data = self._write_element(self.TRACK, track_bytes)
        return self._write_element(self.TRACKS, tracks_data)
    
    def _build_cluster(self) -> bytes:
        """Build Cluster element (containing audio frames)."""
        cluster_data = io.BytesIO()
        
        # Cluster timestamp (0, since frames are relative to cluster)
        cluster_data.write(self._write_element(0xE7, b"\x00"))
        
        # Simple blocks (Opus frames)
        for packet_bytes, timestamp_ms in self.packets:
            # SimpleBlock format:
            # - Track number (vint)
            # - Timestamp (int16, relative to cluster)
            # - Flags (keyframe, etc)
            # - Frame data
            block_data = io.BytesIO()
            block_data.write(b"\x01")  # Track 1
            block_data.write(struct.pack(">h", int(timestamp_ms)))  # Timestamp
            block_data.write(b"\x80")  # Flags (keyframe)
            block_data.write(packet_bytes)  # Opus frame
            
            block_bytes = block_data.getvalue()
            cluster_data.write(self._write_element(self.SIMPLE_BLOCK, block_bytes))
        
        cluster_bytes = cluster_data.getvalue()
        return self._write_element(self.CLUSTER, cluster_bytes)
    
    def build(self) -> bytes:
        """Build complete WebM file.
        
        Returns:
            Complete WebM file bytes
        """
        if not self.packets:
            logger.warning("Building WebM with no packets")
        
        output = io.BytesIO()
        
        # EBML Header
        output.write(self._build_ebml_header())
        
        # Segment container
        segment_data = io.BytesIO()
        segment_data.write(self._build_info())
        segment_data.write(self._build_tracks())
        segment_data.write(self._build_cluster())
        
        segment_bytes = segment_data.getvalue()
        output.write(self._write_element(self.SEGMENT, segment_bytes))
        
        return output.getvalue()


class SessionFinalizer:
    """Finalizes upload sessions and constructs WebM containers.
    
    Called by frontend via /api/sessions/finalize endpoint when:
    - 5-minute session boundary is reached
    - Recording is stopped
    """
    
    def __init__(self, storage_client=None, database_client=None):
        """Initialize session finalizer.
        
        Args:
            storage_client: GCS storage client for writing WebM files
            database_client: Database client for querying Opus packets
        """
        self.storage_client = storage_client
        self.database_client = database_client
    
    async def finalize_session(self, event: SessionFinalizationEvent) -> dict:
        """Finalize a session and construct WebM container.
        
        Args:
            event: Session finalization event from frontend
        
        Returns:
            Result dict with WebM file path and metadata
        """
        logger.info(
            f"Finalizing session {event.upload_session_id} for meeting {event.meeting_id}",
            extra={
                "meeting_id": event.meeting_id,
                "session_id": event.upload_session_id,
                "sequence_range": event.sequence_range,
                "chunk_count": event.chunk_count,
                "byte_count": event.byte_count,
            },
        )
        
        try:
            # Query Opus packets from database for this session
            packets = await self._fetch_packets_for_session(event)
            
            if not packets:
                logger.warning(
                    f"No packets found for session {event.upload_session_id}"
                )
                return {
                    "success": False,
                    "error": "No packets found",
                    "session_id": event.upload_session_id,
                }
            
            # Build WebM container
            builder = WebMBuilder()
            timestamp_ms = 0
            for packet_data in packets:
                builder.add_opus_packet(packet_data, timestamp_ms)
                timestamp_ms += 20  # Assume 20ms per frame
            
            webm_bytes = builder.build()
            
            # Write to GCS
            gcs_path = await self._write_to_gcs(event, webm_bytes)
            
            logger.info(
                f"Session {event.upload_session_id} finalized, WebM at {gcs_path}"
            )
            
            return {
                "success": True,
                "session_id": event.upload_session_id,
                "webm_path": gcs_path,
                "size_bytes": len(webm_bytes),
                "duration_ms": builder.duration_ms,
                "packet_count": len(packets),
            }
        
        except Exception as error:
            logger.error(
                f"Failed to finalize session {event.upload_session_id}: {error}"
            )
            return {
                "success": False,
                "error": str(error),
                "session_id": event.upload_session_id,
            }
    
    async def _fetch_packets_for_session(self, event: SessionFinalizationEvent) -> list[bytes]:
        """Fetch Opus packets for session from database.
        
        Args:
            event: Session finalization event
        
        Returns:
            List of Opus packet bytes in order
        """
        # TODO: Query database for Opus packets with sequence in range
        # SELECT packet_data FROM opus_packets
        # WHERE meeting_id = ? AND session_id = ?
        # AND sequence >= ? AND sequence <= ?
        # ORDER BY sequence ASC
        
        if self.database_client:
            try:
                packets = await self.database_client.query_packets(
                    meeting_id=event.meeting_id,
                    session_id=event.upload_session_id,
                    sequence_start=event.sequence_range["start"],
                    sequence_end=event.sequence_range["end"],
                )
                return packets
            except Exception as e:
                logger.error(f"Database query failed: {e}")
                return []
        
        # Fallback: return empty list (will be logged as warning)
        return []
    
    async def _write_to_gcs(self, event: SessionFinalizationEvent, webm_bytes: bytes) -> str:
        """Write WebM file to GCS.
        
        Args:
            event: Session finalization event
            webm_bytes: Complete WebM file bytes
        
        Returns:
            GCS path (gs://bucket/path/to/file.webm)
        """
        # TODO: Write to GCS bucket
        # gs://meeting-recordings/meeting-{meeting_id}/{session_id}.webm
        
        timestamp = event.end_time.isoformat().replace(":", "-").replace(".", "-")
        gcs_path = (
            f"gs://meeting-recordings/"
            f"{event.meeting_id}/"
            f"{event.upload_session_id}-{timestamp}.webm"
        )
        
        if self.storage_client:
            try:
                await self.storage_client.upload(
                    bucket="meeting-recordings",
                    path=f"{event.meeting_id}/{event.upload_session_id}-{timestamp}.webm",
                    data=webm_bytes,
                    content_type="video/webm",
                )
                logger.info(f"Uploaded WebM to {gcs_path}")
            except Exception as e:
                logger.error(f"Failed to upload to GCS: {e}")
                raise
        else:
            logger.debug(f"No storage client; would upload to {gcs_path}")
        
        return gcs_path

