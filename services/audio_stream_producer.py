"""Audio stream producer for publishing audio to Redis.

Provides a singleton producer instance that manages Redis connection pooling
for publishing audio chunks to the audio stream topic, with local buffering
for temporary Redis unavailability and exponential backoff retry logic.
"""

import logging
import redis
import json
import asyncio
from typing import Optional, Any, Dict
from collections import deque
from utilities.env_config import config
from services.reconnection_strategy import ReconnectionStrategy, ErrorType
from utilities.error_handler import log_exception

logger = logging.getLogger(__name__)


class AudioStreamProducer:
    """Singleton audio stream producer for publishing audio to Redis.
    
    Manages a single Redis connection pool for all audio publishing operations,
    preventing resource exhaustion from multiple producer instances.
    """
    
    _instance: Optional['AudioStreamProducer'] = None
    
    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_db: Optional[int] = None,
        buffer_max_chunks: Optional[int] = None,
        buffer_max_memory_mb: Optional[int] = None
    ):
        """Initialize AudioStreamProducer with Redis connection pool and local buffering.
        
        Args:
            redis_host: Redis server host (overrides REDIS_HOST config). Default from config.
            redis_port: Redis server port (overrides REDIS_PORT config). Default from config.
            redis_db: Redis database number (overrides REDIS_DB config). Default from config.
            buffer_max_chunks: Max chunks in local buffer (overrides config). Default from config.
            buffer_max_memory_mb: Max memory for buffer in MB (overrides config). Default from config.
            
        Raises:
            ValueError: If Redis configuration is invalid.
        """
        try:
            # Get Redis configuration with override support
            self._redis_host = redis_host or config.get('REDIS_HOST')
            self._redis_port = redis_port or config.get_int('REDIS_PORT')
            self._redis_db = redis_db or config.get_int('REDIS_DB')
            
            # Get buffer configuration
            self._buffer_max_chunks = buffer_max_chunks or config.get_int('AUDIO_STREAM_BUFFER_MAX_CHUNKS')
            self._buffer_max_memory_bytes = (buffer_max_memory_mb or config.get_int('AUDIO_STREAM_BUFFER_MAX_MEMORY_MB')) * 1024 * 1024
            
            logger.info(
                f"Initializing AudioStreamProducer with Redis connection pool: "
                f"host={self._redis_host}, port={self._redis_port}, db={self._redis_db}"
            )
            
            # Initialize Redis connection pool
            self._redis_pool = redis.ConnectionPool(
                host=self._redis_host,
                port=self._redis_port,
                db=self._redis_db,
                decode_responses=True,
                max_connections=10,
                socket_keepalive=True,
                socket_keepalive_options={},
            )
            
            # Initialize local buffer for temporary Redis unavailability
            self._buffer: deque = deque()
            self._buffer_total_bytes = 0
            
            logger.info(
                f"Initialized local buffer: max_chunks={self._buffer_max_chunks}, "
                f"max_memory_bytes={self._buffer_max_memory_bytes}"
            )
            
            # Test the connection
            self._test_connection()
            
            logger.info("AudioStreamProducer initialized successfully")
        
        except ValueError as e:
            error_msg = f"Invalid Redis configuration: {str(e)}"
            logger.error(error_msg)
            raise
        except Exception as e:
            error_msg = f"Failed to initialize Redis connection pool: {str(e)}"
            logger.error(error_msg)
            raise
    
    def _test_connection(self) -> None:
        """Test Redis connection by executing a PING command.
        
        Raises:
            Exception: If connection test fails.
        """
        try:
            redis_client = redis.Redis(connection_pool=self._redis_pool)
            redis_client.ping()
            logger.debug("Redis connection test successful")
        except Exception as e:
            error_msg = f"Redis connection test failed: {str(e)}"
            logger.error(error_msg)
            raise
    
    @classmethod
    def get_instance(
        cls,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_db: Optional[int] = None
    ) -> 'AudioStreamProducer':
        """Get singleton instance of AudioStreamProducer.
        
        Creates a single producer instance on first access and returns the same
        instance on subsequent calls, ensuring all audio publishing operations
        share a single Redis connection pool.
        
        Args:
            redis_host: Redis server host (only used on first instantiation).
            redis_port: Redis server port (only used on first instantiation).
            redis_db: Redis database number (only used on first instantiation).
            
        Returns:
            AudioStreamProducer: Singleton instance.
        """
        if cls._instance is None:
            cls._instance = cls(redis_host, redis_port, redis_db)
        return cls._instance
    
    def get_connection(self):
        """Get a Redis connection from the pool.
        
        Returns:
            redis.Redis: Redis client instance.
        """
        return redis.Redis(connection_pool=self._redis_pool)
    
    async def publish_audio(
        self,
        audio_chunk: Dict[str, Any],
        meeting_id: str,
        participant_id: str,
        timestamp: int,
        audio_format: str
    ) -> bool:
        """Publish audio chunk to Redis stream with retry logic and local buffering.
        
        Serializes and publishes audio chunk to Redis stream with exponential backoff retry
        logic. If Redis is temporarily unavailable, buffers the chunk locally for later
        flushing when connection recovers. The local buffer size represents the maximum
        data loss window if Redis remains unreachable.
        
        Args:
            audio_chunk: Audio data dictionary containing serializable audio content.
            meeting_id: Unique identifier of the meeting.
            participant_id: Unique identifier of the audio participant.
            timestamp: Unix timestamp (milliseconds) of the audio chunk.
            audio_format: Format of the audio data (e.g., 'pcm', 'opus', 'webm').
            
        Returns:
            bool: True if published successfully, False if all retries exhausted.
        """
        stream_key = f"audio_stream:{meeting_id}"
        message_data = {
            'participant_id': participant_id,
            'timestamp': timestamp,
            'audio_format': audio_format,
            'chunk': json.dumps(audio_chunk),
            'chunk_size': len(str(audio_chunk))
        }
        
        # Initialize retry strategy
        retry_strategy = ReconnectionStrategy(
            initial_delay_ms=1000,
            backoff_factor=2.0,
            max_delay_ms=5000,
            max_attempts=3
        )
        
        context = {
            'meeting_id': meeting_id,
            'participant_id': participant_id,
            'stream_key': stream_key
        }
        
        last_error = None
        
        # Attempt publish with retry logic
        while retry_strategy.should_retry():
            try:
                redis_client = self.get_connection()
                
                # Attempt XADD to Redis stream
                result = redis_client.xadd(stream_key, message_data)
                
                logger.info(
                    f"Published audio chunk to Redis stream {stream_key}: "
                    f"message_id={result}, participant={participant_id}"
                )
                
                # If publish succeeded and buffer has data, flush buffered chunks
                if self._buffer:
                    await self._flush_buffered_chunks(redis_client, stream_key)
                
                return True
            
            except redis.ConnectionError as e:
                last_error = e
                error_type = ErrorType.TRANSIENT
                error_msg = f"Redis connection error in publish_audio: {str(e)}"
                
                logger.warning(f"{error_msg}. Buffering chunk locally...")
                
                # Add to local buffer on connection failure
                self._enqueue_buffered_chunk(message_data)
                
                # Determine if we should retry
                if retry_strategy.should_retry(error_type):
                    delay_seconds = retry_strategy.get_delay_seconds()
                    logger.debug(f"Retrying in {delay_seconds}s (attempt {retry_strategy.get_attempt_count() + 1})")
                    retry_strategy.record_attempt()
                    await asyncio.sleep(delay_seconds)
                else:
                    break
            
            except redis.TimeoutError as e:
                last_error = e
                error_type = ErrorType.TRANSIENT
                error_msg = f"Redis timeout in publish_audio: {str(e)}"
                
                logger.warning(f"{error_msg}. Buffering chunk locally...")
                self._enqueue_buffered_chunk(message_data)
                
                if retry_strategy.should_retry(error_type):
                    delay_seconds = retry_strategy.get_delay_seconds()
                    logger.debug(f"Retrying in {delay_seconds}s (attempt {retry_strategy.get_attempt_count() + 1})")
                    retry_strategy.record_attempt()
                    await asyncio.sleep(delay_seconds)
                else:
                    break
            
            except Exception as e:
                last_error = e
                error_msg = f"Unexpected error in publish_audio: {str(e)}"
                
                logger.warning(f"{error_msg}. Buffering chunk locally...")
                self._enqueue_buffered_chunk(message_data)
                
                if retry_strategy.should_retry():
                    delay_seconds = retry_strategy.get_delay_seconds()
                    logger.debug(f"Retrying in {delay_seconds}s (attempt {retry_strategy.get_attempt_count() + 1})")
                    retry_strategy.record_attempt()
                    await asyncio.sleep(delay_seconds)
                else:
                    break
        
        # All retries exhausted
        if last_error:
            log_exception(
                logger,
                logging.ERROR,
                f"Failed to publish audio chunk to Redis after {retry_strategy.get_attempt_count()} attempts",
                last_error,
                context
            )
        
        logger.error(
            f"Audio publish failed for meeting_id={meeting_id}, participant={participant_id}. "
            f"Chunk buffered locally. Buffer size: {len(self._buffer)}/{self._buffer_max_chunks} chunks, "
            f"Memory: {self._buffer_total_bytes / (1024*1024):.2f}MB/{self._buffer_max_memory_bytes / (1024*1024):.2f}MB"
        )
        
        return False
    
    def _enqueue_buffered_chunk(self, message_data: Dict[str, Any]) -> None:
        """Enqueue audio chunk in local buffer with dual-capacity enforcement.
        
        Enforces max_chunks and max_memory_bytes limits, dropping oldest chunks
        (FIFO head) when capacity exceeded.
        
        Args:
            message_data: Serialized message to buffer.
        """
        chunk_size = len(str(message_data))
        
        # Check dual capacity limits
        would_exceed_count = len(self._buffer) >= self._buffer_max_chunks
        would_exceed_memory = (self._buffer_total_bytes + chunk_size) > self._buffer_max_memory_bytes
        
        # Enforce limits: drop oldest if either exceeded
        if would_exceed_count or would_exceed_memory:
            if self._buffer:
                dropped = self._buffer.popleft()
                dropped_size = len(str(dropped))
                self._buffer_total_bytes -= dropped_size
                logger.warning(
                    f"Local audio buffer overflow. Dropped oldest chunk (size={dropped_size}b). "
                    f"Buffer: {len(self._buffer)}/{self._buffer_max_chunks} chunks, "
                    f"Memory: {self._buffer_total_bytes / (1024*1024):.2f}MB/{self._buffer_max_memory_bytes / (1024*1024):.2f}MB"
                )
        
        # Enqueue new chunk
        self._buffer.append(message_data)
        self._buffer_total_bytes += chunk_size
        
        logger.debug(
            f"Buffered audio chunk (size={chunk_size}b). "
            f"Buffer: {len(self._buffer)}/{self._buffer_max_chunks} chunks"
        )
    
    async def _flush_buffered_chunks(self, redis_client, stream_key: str) -> None:
        """Flush all buffered chunks to Redis stream in FIFO order.
        
        Called when Redis recovers after being temporarily unavailable.
        
        Args:
            redis_client: Redis client instance from pool.
            stream_key: Redis stream key to publish to.
        """
        flushed_count = 0
        
        while self._buffer:
            try:
                chunk = self._buffer.popleft()
                chunk_size = len(str(chunk))
                self._buffer_total_bytes -= chunk_size
                
                # Publish buffered chunk
                result = redis_client.xadd(stream_key, chunk)
                flushed_count += 1
                
                logger.debug(f"Flushed buffered chunk: message_id={result}")
            
            except Exception as e:
                logger.error(f"Error flushing buffered chunk: {str(e)}. Stopping flush operation.")
                break
        
        if flushed_count > 0:
            logger.info(
                f"Successfully flushed {flushed_count} buffered audio chunks to Redis stream. "
                f"Buffer now empty."
            )
    
    async def flush_pending_audio(self) -> None:
        """Flush all buffered audio chunks to Redis before termination.
        
        Called during graceful shutdown to ensure buffered chunks are persisted
        before the process terminates. This is the final opportunity to deliver
        any locally-buffered audio before the producer is shut down.
        """
        if not self._buffer:
            logger.info("No pending audio to flush")
            return
        
        logger.info(
            f"Flushing {len(self._buffer)} pending audio chunks before shutdown. "
            f"Buffer size: {self._buffer_total_bytes / (1024*1024):.2f}MB"
        )
        
        try:
            redis_client = self.get_connection()
            flushed_count = 0
            
            # Flush all buffered chunks in FIFO order
            while self._buffer:
                try:
                    chunk = self._buffer.popleft()
                    chunk_size = len(str(chunk))
                    self._buffer_total_bytes -= chunk_size
                    
                    # Extract stream key from chunk metadata
                    stream_key = chunk.get('stream_key')
                    if not stream_key:
                        # Reconstruct from chunk if needed
                        participant_id = chunk.get('participant_id', 'unknown')
                        # Use a generic stream key if specific one not found
                        stream_key = "audio_stream:unknown"
                    
                    # Publish buffered chunk
                    result = redis_client.xadd(stream_key, chunk)
                    flushed_count += 1
                    logger.debug(f"Flushed audio chunk during shutdown: message_id={result}")
                
                except Exception as e:
                    logger.error(f"Error flushing buffered chunk during shutdown: {str(e)}")
                    # Continue with remaining chunks even if one fails
                    continue
            
            if flushed_count > 0:
                logger.info(
                    f"Successfully flushed {flushed_count} pending audio chunks to Redis during shutdown"
                )
        
        except Exception as e:
            logger.warning(
                f"Failed to flush buffered audio chunks during shutdown: {str(e)}. "
                f"Local buffer will be lost."
            )
    
    def close(self) -> None:
        """Close the Redis connection pool and all connections.
        
        Should be called during application shutdown.
        """
        try:
            self._redis_pool.disconnect()
            logger.info("Redis connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing Redis connection pool: {str(e)}")

