"""WebSocket event handlers for Socket.IO server.

Provides centralized event handler definitions and registration for all WebSocket events,
including client connections, disconnections, audio chunk reception, and error handling.
Integrates with CW API for resumable uploads and manages out-of-order chunk buffering.
"""

import logging
import uuid
import socketio
import asyncio
import httpx
from utilities.cw_utils import CWCaller
from services.chunk_upload_manager import get_chunk_upload_manager
from utilities.env_config import config
from typing import Dict
from utilities.mail_utils import email_sender

logger = logging.getLogger(__name__)


async def _upload_to_gcs(
    client: httpx.AsyncClient,
    meeting_id: str,
    session,
    buffer_data: bytes,
    is_final: bool = False
) -> bool:
    """Upload buffered data to GCS via resumable protocol.
    
    Args:
        client: httpx.AsyncClient instance
        meeting_id: Meeting identifier
        session: UploadSession with resumable_url and byte tracking
        buffer_data: Raw bytes to upload
        is_final: True if this is the final (possibly < 256KB) upload
    
    Returns:
        True if upload successful, False otherwise
    """
    buffer_size = len(buffer_data)
    start_byte = session.uploaded_bytes
    end_byte = start_byte + buffer_size - 1
    
    # Content-Range format: bytes start-end/total
    # For non-final uploads, total is unknown (*), for final it's the total size
    if is_final:
        total_size = start_byte + buffer_size
        content_range = f"bytes {start_byte}-{end_byte}/{total_size}"
    else:
        content_range = f"bytes {start_byte}-{end_byte}/*"
    
    logger.info(
        f"[{meeting_id}] Uploading {buffer_size} bytes to GCS: {content_range}"
    )
    
    try:
        headers = {
            "Content-Type": "audio/webm;codecs=opus",
            "Content-Length": str(buffer_size),
            "Content-Range": content_range
        }
        
        response = await client.put(
            session.resumable_url,
            content=buffer_data,
            headers=headers
        )
        
        # Handle GCS responses
        if response.status_code == 308:
            # Resume Incomplete: intermediate success, expect more data
            logger.info(
                f"[{meeting_id}] GCS accepted {buffer_size} bytes "
                f"(308 Resume Incomplete) - total so far: {end_byte + 1}"
            )
            session.uploaded_bytes += buffer_size
            session.total_uploaded_chunks += 1
            return True
        elif response.status_code in (200, 201):
            # Upload complete: final object written
            logger.info(
                f"[{meeting_id}] GCS upload completed "
                f"(status {response.status_code}) - total: {end_byte + 1} bytes"
            )
            session.uploaded_bytes += buffer_size
            session.total_uploaded_chunks += 1
            return True
        else:
            logger.error(
                f"[{meeting_id}] Unexpected GCS response: "
                f"status={response.status_code}, body={response.text[:200]}"
            )
            return False
            
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[{meeting_id}] GCS upload failed: "
            f"status={e.response.status_code}, body={e.response.text[:300]}"
        )
        return False
    except Exception as e:
        logger.error(
            f"[{meeting_id}] Error uploading to GCS: {e}",
            exc_info=True
        )
        return False


async def _upload_sequential_chunks(
    sio: socketio.AsyncServer,
    meeting_id: str,
    session,
    chunk_manager,
    is_final: bool = False
) -> bool:
    """Buffer WebSocket chunks and upload to GCS when buffer reaches 256KB or recording ends.
    
    Buffers incoming audio chunks until 256KB is accumulated, then uploads via GCS resumable
    protocol with correct Content-Range header tracking cumulative bytes.
    On recordingEnded (is_final=True), uploads remaining buffer as final chunk.
    
    Args:
        sio: Socket.IO AsyncServer instance
        meeting_id: Meeting identifier
        session: UploadSession with upload_buffer and uploaded_bytes
        chunk_manager: ChunkUploadManager instance
        is_final: True when called from recordingEnded to flush remaining buffer
    
    Returns:
        bool: True if all buffered data uploaded successfully, False otherwise
    """
    if not session.resumable_url:
        logger.warning(f"[{meeting_id}] No resumable URL available, skipping upload")
        return False
    
    ready_chunks = chunk_manager.get_next_sequential_chunks(meeting_id)
    
    if not ready_chunks:
        logger.debug(f"[{meeting_id}] No sequential chunks ready for buffering")
        # If final and buffer has data, upload it
        if is_final and len(session.upload_buffer) > 0:
            logger.info(f"[{meeting_id}] Final flush: uploading remaining {len(session.upload_buffer)} bytes")
            async with httpx.AsyncClient(timeout=300.0) as client:
                result = await _upload_to_gcs(client, meeting_id, session, bytes(session.upload_buffer), is_final=True)
                if result:
                    for chunk_id in session.buffered_chunk_ids_in_upload_buffer:
                        chunk_manager.track_uploaded_chunk(meeting_id, chunk_id)
                    session.buffered_chunk_ids_in_upload_buffer.clear()
                    session.upload_buffer.clear()
                return result
        return True
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Add sequential chunks to buffer
            for chunk_id, chunk_data in ready_chunks:
                audio_blob = chunk_data.get('audioBlob', [])
                if isinstance(audio_blob, list):
                    audio_bytes = bytes(audio_blob)
                else:
                    audio_bytes = audio_blob
                
                session.upload_buffer.extend(audio_bytes)
                session.buffered_chunk_ids_in_upload_buffer.append(chunk_id)
                logger.debug(
                    f"[{meeting_id}] Buffered chunk {chunk_id}: "
                    f"{len(audio_bytes)} bytes, buffer now: {len(session.upload_buffer)} bytes"
                )
            
            # Upload when buffer reaches 256KB (non-final) or on final flush
            min_chunk_size = 256 * 1024  # 256KB minimum for non-final uploads
            
            if len(session.upload_buffer) >= min_chunk_size or is_final:
                if is_final:
                    # Upload all remaining data as final
                    logger.info(
                        f"[{meeting_id}] Final upload: {len(session.upload_buffer)} bytes "
                        f"(is_final=True)"
                    )
                    result = await _upload_to_gcs(
                        client, meeting_id, session,
                        bytes(session.upload_buffer),
                        is_final=True
                    )
                else:
                    # Upload 256KB chunks, keep remainder for next batch
                    while len(session.upload_buffer) >= min_chunk_size:
                        chunk_to_upload = bytes(session.upload_buffer[:min_chunk_size])
                        result = await _upload_to_gcs(
                            client, meeting_id, session,
                            chunk_to_upload,
                            is_final=False
                        )
                        if not result:
                            return False
                        # Remove uploaded data from buffer
                        del session.upload_buffer[:min_chunk_size]
                        for chunk_id in session.buffered_chunk_ids_in_upload_buffer:
                            chunk_manager.track_uploaded_chunk(meeting_id, chunk_id)
                        session.buffered_chunk_ids_in_upload_buffer.clear()
                        logger.debug(
                            f"[{meeting_id}] Uploaded 256KB, remaining buffer: {len(session.upload_buffer)} bytes"
                        )
                
                if not result:
                    return False
                if is_final:
                    for chunk_id in session.buffered_chunk_ids_in_upload_buffer:
                        chunk_manager.track_uploaded_chunk(meeting_id, chunk_id)
                    session.buffered_chunk_ids_in_upload_buffer.clear()
                    session.upload_buffer.clear()
            else:
                logger.debug(
                    f"[{meeting_id}] Buffer accumulating: {len(session.upload_buffer)} bytes "
                    f"(waiting for 256KB threshold)"
                )
        
        logger.info(
            f"[{meeting_id}] Upload processing complete. "
            f"Chunks buffered: {len(ready_chunks)}, "
            f"GCS uploads: {session.total_uploaded_chunks}, "
            f"Total bytes uploaded: {session.uploaded_bytes}"
        )
        return True
    
    except Exception as e:
        logger.error(
            f"[{meeting_id}] Error in sequential chunk upload: {e}",
            exc_info=True
        )
        return False


async def _wait_for_pending_chunks(
    sio: socketio.AsyncServer,
    meeting_id: str,
    session,
    chunk_manager,
    queued_chunks: int,
    max_attempts: int = 5,
    poll_interval_seconds: float = 1.0,
) -> Dict[str, int]:
    """Wait for queued client chunks to arrive and flush any uploadable batches."""
    stats = chunk_manager.get_session_stats(meeting_id)

    for attempt in range(max_attempts):
        async with session.lock:
            upload_ok = await _upload_sequential_chunks(sio, meeting_id, session, chunk_manager)
            stats = chunk_manager.get_session_stats(meeting_id)

        no_server_buffer = stats['buffered_count'] == 0
        received_at_least_expected = stats['uploaded_count'] >= queued_chunks or queued_chunks == 0

        if upload_ok and no_server_buffer and received_at_least_expected:
            return stats

        logger.info(
            f"[{meeting_id}] Waiting for pending chunks "
            f"(attempt {attempt + 1}/{max_attempts}): "
            f"uploaded={stats['uploaded_count']}, buffered={stats['buffered_count']}, "
            f"queued_hint={queued_chunks}"
        )
        await asyncio.sleep(poll_interval_seconds)

    return chunk_manager.get_session_stats(meeting_id)


def register_websocket_handlers(sio: socketio.AsyncServer) -> None:
    """Register all WebSocket event handlers with the Socket.IO server.
    
    Args:
        sio: Socket.IO AsyncServer instance to register handlers with
    """
    
    @sio.event
    async def connect(sid: str, environ: dict) -> None:
        """Handle client WebSocket connection.
        
        Called when a client establishes a new WebSocket connection.
        Client-side buffering in stormee_meet_bot_service.py handles re-transmission
        of buffered chunks on reconnection.
        
        Args:
            sid: Socket.IO session ID for the connected client
            environ: ASGI environment dictionary with request context
        """
        logger.info(f"Client connected via WebSocket: {sid}")
    
    @sio.event
    async def disconnect(sid: str) -> None:
        """Handle client WebSocket disconnection.
        
        Called when a connected client closes its WebSocket connection.
        Client-side buffering in stormee_meet_bot_service.py will handle queuing
        of subsequent chunks until reconnection is established.
        
        Args:
            sid: Socket.IO session ID of the disconnected client
        """
        logger.info(f"Client disconnected: {sid}")
    
    @sio.event
    async def audioChunk(sid: str, data: dict) -> None:
        """Handle incoming audio chunks and upload to CW API via resumable upload.
        
        Receives audio chunks from client (which has already buffered them during
        WebSocket disconnection if necessary), manages resumable uploads via CW API,
        and handles out-of-order chunks via sequential buffering.
        
        Client-side buffering in stormee_meet_bot_service.py ensures chunks are
        transmitted in order. Server-side manages only the CW API resumable upload.
        
        Args:
            sid: Socket.IO session ID of the sending client
            data: Dictionary containing:
                - meetingId (str): Meeting identifier
                - chunkId (str): Unique chunk identifier (format: "meeting-N")
                - timestamp (str): ISO timestamp of chunk generation
                - audioBlob (list): Byte array of audio data
        """
        try:
            meeting_id = data.get('meetingId')
            chunk_id = data.get('chunkId')
            timestamp = data.get('timestamp')
            audio_blob = data.get('audioBlob')
            audio_size = len(audio_blob) if audio_blob else 0
            
            logger.info(
                f"Audio chunk received: meeting={meeting_id}, chunk={chunk_id}, "
                f"size={audio_size} bytes"
            )
            
            # Initialize chunk manager and get/create session
            chunk_manager = get_chunk_upload_manager()
            session = chunk_manager.get_or_create_session(meeting_id)

            async with session.lock:
                # Fetch resumable URL on first chunk
                if session.resumable_url is None:
                    logger.info(f"[{meeting_id}] First chunk received, fetching resumable URL from CW API")
                    try:
                        cw_caller = CWCaller()
                        rec_id = uuid.uuid4()
                        payload = {
                            'project_id': data.get("projectId"),
                            'filenames': [f"{meeting_id.replace('/', '_').replace(':', '_')}_{rec_id}.webm"],
                            'resumable': True,
                            'content_type': 'audio/webm;codecs=opus'
                        }
                        resumable_url, public_url = await cw_caller.fetch_resumable_url_from_backend(payload)
                        chunk_manager.set_resumable_url(meeting_id, resumable_url, public_url)
                        logger.info(f"[{meeting_id}] Resumable URL fetched successfully with contentType=audio/webm;codecs=opus")
                    except Exception as e:
                        logger.error(f"[{meeting_id}] Failed to fetch resumable URL: {e}")
                        return
                
                # Buffer chunk (handles out-of-order detection)
                is_sequential, buffer_status = chunk_manager.buffer_chunk(meeting_id, data)
                
                # Try to upload sequential chunks to CW API
                await _upload_sequential_chunks(sio, meeting_id, session, chunk_manager)
            
            # Log buffering status if out-of-order
            if not is_sequential:
                stats = chunk_manager.get_session_stats(meeting_id)
                logger.warning(
                    f"[{meeting_id}] {buffer_status} | "
                    f"buffered={stats['buffered_count']}, "
                    f"uploaded={stats['uploaded_count']}"
                )
            
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}", exc_info=True)
    
    @sio.event
    async def recordingEnded(sid: str, data: dict) -> dict:
        """Handle recording end event and confirm upload completion.
        
        Invoked when audio recording stops. Finalizes chunk processing,
        verifies all uploads are complete, and confirms upload to backend
        to trigger processing and auto-ingest.
        
        Args:
            sid: Socket.IO session ID of the sending client
            data: Dictionary containing:
                - meetingId (str): Meeting identifier
                - projectId (str): Project identifier for upload confirmation
                - timestamp (float): Unix timestamp when recording ended
                - eventType (str): 'recordingEnded'
                - status (str): 'stopped'
                - queuedChunks (int): Number of chunks still pending transmission
                - artifactUserName (str): Name of user who created artifact
                - artifactUserEmail (str): Email of user who created artifact
        """
        try:
            meeting_id = data.get('meetingId')
            project_id = data.get('projectId')
            queued_chunks = data.get('queuedChunks', 0)
            timestamp = data.get('timestamp')
            user_name = data.get('artifactUserName', '')
            user_email = data.get('artifactUserEmail', '')
            
            logger.info(
                f"Recording ended: meeting={meeting_id}, "
                f"queuedChunks={queued_chunks}, project_id={project_id}"
            )
            logger.debug(
                f"Recording end details: timestamp={timestamp}, event_type={data.get('eventType')}"
            )
            
            if not meeting_id:
                logger.error(f"Missing required field: meetingId")
                return {"status": "error", "reason": "missing_meeting_id"}
            
            # Check upload session
            chunk_manager = get_chunk_upload_manager()
            session = chunk_manager.get_session(meeting_id)
            
            if not session:
                logger.warning(
                    f"No upload session found for meeting {meeting_id}, "
                    f"skipping upload confirmation"
                )
                return {"status": "ok", "meetingId": meeting_id, "uploaded_chunks": 0}
            
            async with session.lock:
                session.is_finalizing = True
                
                # Give last chunks time to arrive (race condition: chunks in transit)
                logger.info(
                    f"[{meeting_id}] Recording ended. Waiting for stragglers "
                    f"(buffer_size={len(session.upload_buffer)} bytes, queuedChunks={queued_chunks})"
                )
            
            # Grace period: wait up to 3 seconds for any in-flight chunks
            for attempt in range(3):
                await asyncio.sleep(1.0)
                async with session.lock:
                    # Try to upload any newly arrived chunks
                    await _upload_sequential_chunks(
                        sio, meeting_id, session, chunk_manager,
                        is_final=False  # Don't finalize yet, just flush accumulated
                    )
                    
                    buffered_now = chunk_manager.get_buffered_chunk_count(meeting_id)
                    buffer_size = len(session.upload_buffer)
                    logger.debug(
                        f"[{meeting_id}] Grace period attempt {attempt + 1}: "
                        f"buffered_chunks={buffered_now}, buffer_size={buffer_size} bytes"
                    )
                    
                    if buffered_now == 0 and buffer_size == 0:
                        logger.info(f"[{meeting_id}] All chunks received, finalizing now")
                        break
            
            # Final flush: upload all remaining buffered data as final chunk
            async with session.lock:
                logger.info(
                    f"[{meeting_id}] Final flush: "
                    f"buffer_size={len(session.upload_buffer)} bytes, "
                    f"total_uploaded={session.total_uploaded_chunks} GCS requests"
                )
                
                # Final upload: flushes remaining buffer as final (allowed to be < 256KB)
                final_upload_ok = await _upload_sequential_chunks(
                    sio, meeting_id, session, chunk_manager,
                    is_final=True  # Signal to flush all remaining data
                )
                
                # Get final stats
                stats = chunk_manager.get_session_stats(meeting_id)
            
            total_uploaded = stats['uploaded_count']
            total_buffered = stats['buffered_count']
            bytes_uploaded = session.uploaded_bytes
            gcs_uploads = session.total_uploaded_chunks
            
            logger.info(
                f"[{meeting_id}] Recording ended: "
                f"websocket_chunks={total_uploaded}, buffered={total_buffered}, "
                f"gcs_uploads={gcs_uploads}, total_bytes={bytes_uploaded}"
            )
            
            # Warn if there are still buffered chunks
            if total_buffered > 0:
                logger.warning(
                    f"[{meeting_id}] {total_buffered} WebSocket chunks still buffered after finalization. "
                    f"Buffer size: {len(session.upload_buffer)} bytes. Client may not have sent all chunks."
                )
                return {
                    "status": "incomplete",
                    "meetingId": meeting_id,
                    "uploaded_chunks": total_uploaded,
                    "uploaded_bytes": bytes_uploaded,
                    "buffered_chunks": total_buffered,
                }

            if not final_upload_ok and len(session.upload_buffer) > 0:
                logger.error(
                    f"[{meeting_id}] Final upload failed with {len(session.upload_buffer)} bytes still pending"
                )
                return {
                    "status": "error",
                    "meetingId": meeting_id,
                    "reason": "final_upload_failed",
                    "uploaded_chunks": total_uploaded,
                    "uploaded_bytes": bytes_uploaded,
                }
            
            # Confirm upload only if actual GCS uploads happened and we have project_id
            if project_id and session.public_url and gcs_uploads > 0:
                try:
                    logger.info(
                        f"[{meeting_id}] Confirming upload with backend "
                        f"[project_id={project_id}, gcs_uploads={gcs_uploads}, bytes={bytes_uploaded}, "
                        f"public_url={session.public_url}]"
                    )
                    
                    # Single file from the one resumable_url session
                    audio_filename = session.public_url.split("/")[-1]
                    files = [{
                        "filename": audio_filename,
                        "url": session.public_url
                    }]
                    
                    # Call confirm upload API
                    cw_caller = CWCaller()
                    result = await cw_caller.confirm_upload(
                        project_id=project_id,
                        files=files,
                        is_ai=False,
                        artifact_user_name=user_name,
                        artifact_user_email=user_email,
                        auto_ingest=True,
                    )
                    if result and "uploaded_files" in result and len(result.get("uploaded_files"))>0:
                        
                        # Create background tasks for artifact generation and email notification
                        asyncio.create_task(
                            cw_caller.generate_meeting_mode_artifact(
                                audio_name=audio_filename,
                                project_id=project_id,
                                display_name=meeting_id,
                                user_email=user_email,
                                user_name=user_name,
                            )
                        )
                        
                        asyncio.create_task(
                            email_sender.send_meeting_file_uploaded_email(
                                user_name=user_name,
                                user_email=user_email,
                                project_name=project_id,
                                project_url=f"https://dev.appmod.ai/mode/Project%20Mode/projects/{project_id}",
                                meeting_title=meeting_id,
                                file_type="recording"
                            )
                        )

                    
                    logger.info(
                        f"[{meeting_id}] Upload confirmed successfully. Response: {result}"
                    )
                    response_payload = {
                        "status": "ok",
                        "meetingId": meeting_id,
                        "uploaded_chunks": total_uploaded,
                        "uploaded_bytes": bytes_uploaded,
                    }
                    
                except Exception as e:
                    logger.error(
                        f"[{meeting_id}] Failed to confirm upload: {e}", exc_info=True
                    )
                    return {
                        "status": "error",
                        "meetingId": meeting_id,
                        "reason": "confirm_upload_failed",
                    }
            else:
                logger.warning(
                    f"[{meeting_id}] Skipping confirmation: "
                    f"project_id={project_id}, public_url={bool(session.public_url)}, "
                    f"bytes_uploaded={bytes_uploaded}"
                )
                response_payload = {
                    "status": "ok",
                    "meetingId": meeting_id,
                    "uploaded_chunks": total_uploaded,
                    "uploaded_bytes": bytes_uploaded,
                }
            
            # Clear session after processing
            chunk_manager.clear_session(meeting_id)
            logger.info(f"[{meeting_id}] Upload session cleared")
            return response_payload
        
        except Exception as e:
            logger.error(
                f"Error in recordingEnded handler: {e}", 
                exc_info=True
            )
            return {"status": "error", "reason": "recording_ended_exception"}
    
    @sio.event
    async def error(sid: str, data: dict) -> None:
        """Handle WebSocket connection errors.
        
        Called when an error occurs on the client connection.
        
        Args:
            sid: Socket.IO session ID of the client with error
            data: Error data/message from the client
        """
        logger.error(
            f"WebSocket error for client {sid}: {data}"
        )
    
    logger.info("WebSocket event handlers registered successfully")
