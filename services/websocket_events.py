"""WebSocket event handlers for Socket.IO server.

Provides centralized event handler definitions and registration for all WebSocket events,
including client connections, disconnections, audio chunk reception, and error handling.
Integrates with CW API for resumable uploads and manages out-of-order chunk buffering.
"""

import logging
import socketio
# import asyncio
# from utilities.cw_utils import CWCaller
# from services.chunk_upload_manager import get_chunk_upload_manager
# from utilities.env_config import config

logger = logging.getLogger(__name__)


def register_websocket_handlers(sio: socketio.AsyncServer) -> None:
    """Register all WebSocket event handlers with the Socket.IO server.
    
    Args:
        sio: Socket.IO AsyncServer instance to register handlers with
    """
    
    @sio.event
    async def connect(sid: str, environ: dict) -> None:
        """Handle client WebSocket connection.
        
        Called when a client establishes a new WebSocket connection.
        
        Args:
            sid: Socket.IO session ID for the connected client
            environ: ASGI environment dictionary with request context
        """
        logger.info(f"Client connected via WebSocket: {sid}")
    
    @sio.event
    async def disconnect(sid: str) -> None:
        """Handle client WebSocket disconnection.
        
        Called when a connected client closes its WebSocket connection.
        
        Args:
            sid: Socket.IO session ID of the disconnected client
        """
        logger.info(f"Client disconnected: {sid}")
    
    @sio.event
    async def audioChunk(sid: str, data: dict) -> None:
        """Handle incoming audio chunks with CW API integration and chunk buffering.
        
        Manages resumable uploads via CW API, handles out-of-order chunks by buffering,
        and uploads chunks in correct sequential order.
        
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
            
            # # Initialize chunk manager and get/create session
            # chunk_manager = get_chunk_upload_manager()
            # session = chunk_manager.get_or_create_session(meeting_id)
            
            # # Fetch resumable URL on first chunk
            # if session.resumable_url is None:
            #     logger.info(f"[{meeting_id}] First chunk received, fetching resumable URL from CW API")
            #     try:
            #         cw_caller = CWCaller()
            #         # Call CW API to fetch resumable upload URL
            #         payload = {
            #             'meetingId': meeting_id,
            #             'projectId': config.get('PROJECT_ID')
            #         }
            #         resumable_url = await cw_caller.fetch_resumable_url_from_backend(payload)
            #         chunk_manager.set_resumable_url(meeting_id, resumable_url)
            #         logger.info(f"[{meeting_id}] Resumable URL fetched successfully")
            #     except Exception as e:
            #         logger.error(f"[{meeting_id}] Failed to fetch resumable URL: {e}")
            #         return
            
            # # Buffer the chunk (handles out-of-order detection)
            # is_sequential, buffer_status = chunk_manager.buffer_chunk(meeting_id, data)
            
            # # Try to upload sequential chunks
            # await _upload_sequential_chunks(meeting_id, session)
            
            # # Log buffering status if out-of-order
            # if not is_sequential:
            #     stats = chunk_manager.get_session_stats(meeting_id)
            #     logger.warning(
            #         f"[{meeting_id}] {buffer_status} | "
            #         f"buffered={stats['buffered_count']}, "
            #         f"uploaded={stats['uploaded_count']}"
            #     )
            
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}", exc_info=True)
    
    @sio.event
    async def recordingEnded(sid: str, data: dict) -> None:
        """Handle recording end event from bot.
        
        Invoked when audio recording stops. Allows external systems to finalize
        chunk processing and complete streaming storage operations.
        
        Args:
            sid: Socket.IO session ID of the sending client
            data: Dictionary containing:
                - meetingId (str): Meeting identifier
                - timestamp (float): Unix timestamp when recording ended
                - eventType (str): 'recordingEnded'
                - status (str): 'stopped'
                - queuedChunks (int): Number of chunks still pending transmission
        """
        meeting_id = data.get('meetingId')
        queued_chunks = data.get('queuedChunks', 0)
        timestamp = data.get('timestamp')
        
        logger.info(
            f"Recording ended: meeting={meeting_id}, "
            f"queuedChunks={queued_chunks}"
        )
        logger.debug(
            f"Recording end details: timestamp={timestamp}, event_type={data.get('eventType')}"
        )
        
        # TODO: Finalize streaming storage
        # Example implementations:
        # - await finalize_audio_file(meeting_id)
        # - await close_file_handle(meeting_id)
        # - await update_database_status(meeting_id, 'completed')
        # - await retry_pending_chunks(meeting_id, queued_chunks) if queued_chunks > 0
    
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

