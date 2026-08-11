"""Audio queue manager for buffering chunks during WebSocket disconnections."""

import logging
import sys
from typing import List, Dict, Optional, Any
from collections import deque

logger = logging.getLogger(__name__)


class AudioQueueManager:
    """Singleton audio queue manager for buffering chunks during WebSocket unavailability.
    
    Provides:
    - FIFO buffering of audio chunks with metadata preservation
    - Dual capacity limits: chunk count and memory size (bytes)
    - Overflow handling with head-drop when capacity exceeded
    - Size estimation and state queries
    """
    
    _instance: Optional['AudioQueueManager'] = None
    
    def __init__(self, max_chunks: int = 100, max_memory_bytes: int = 10485760):
        """Initialize AudioQueueManager with capacity limits.
        
        Args:
            max_chunks: Maximum number of chunks to buffer (default 100)
            max_memory_bytes: Maximum memory to buffer (default 10MB = 10485760 bytes)
        """
        self.max_chunks = max_chunks
        self.max_memory_bytes = max_memory_bytes
        self.queue: deque = deque()
        self.total_memory_bytes = 0
        logger.debug(
            f"AudioQueueManager initialized: max_chunks={max_chunks}, "
            f"max_memory_bytes={max_memory_bytes}"
        )
    
    @classmethod
    def get_instance(cls, max_chunks: int = 100, max_memory_bytes: int = 10485760) -> 'AudioQueueManager':
        """Get singleton instance of AudioQueueManager.
        
        Args:
            max_chunks: Maximum number of chunks (only used on first instantiation)
            max_memory_bytes: Maximum memory bytes (only used on first instantiation)
            
        Returns:
            AudioQueueManager: Singleton instance
        """
        if cls._instance is None:
            cls._instance = cls(max_chunks, max_memory_bytes)
        return cls._instance
    
    def enqueue(self, chunk: Dict[str, Any]) -> bool:
        """Enqueue audio chunk, enforcing dual capacity limits with head-drop on overflow.
        
        Calculates chunk size as audioBlob byte count. If adding chunk would exceed
        chunk count OR memory limits, drops oldest chunk (FIFO head) before enqueuing.
        
        Args:
            chunk: Audio chunk dictionary with keys: meetingId, chunkId, timestamp, audioBlob (list)
            
        Returns:
            bool: True if chunk added successfully, False if dropped due to capacity.
        """
        # Calculate chunk size
        audio_blob = chunk.get('audioBlob', [])
        chunk_size = len(audio_blob)
        
        # Check capacity constraints
        would_exceed_count = len(self.queue) >= self.max_chunks
        would_exceed_memory = (self.total_memory_bytes + chunk_size) > self.max_memory_bytes
        
        # Enforce dual limits: drop oldest if either limit exceeded
        if would_exceed_count or would_exceed_memory:
            if self.queue:
                dropped = self.queue.popleft()
                dropped_size = len(dropped.get('audioBlob', []))
                self.total_memory_bytes -= dropped_size
                
                reason = "count" if would_exceed_count else "memory"
                logger.warning(
                    f"Audio queue at capacity ({reason}); "
                    f"dropped oldest chunk {dropped.get('chunkId')}"
                )
        
        # Enqueue chunk
        self.queue.append(chunk)
        self.total_memory_bytes += chunk_size
        
        logger.debug(
            f"Enqueued chunk {chunk.get('chunkId')}: "
            f"queue_size={len(self.queue)}, memory={self.total_memory_bytes} bytes"
        )
        
        return True
    
    def dequeue(self) -> Optional[Dict[str, Any]]:
        """Dequeue and return the oldest buffered audio chunk (FIFO).
        
        Returns:
            dict: Audio chunk dictionary if queue not empty, None otherwise.
        """
        if not self.queue:
            return None
        
        chunk = self.queue.popleft()
        chunk_size = len(chunk.get('audioBlob', []))
        self.total_memory_bytes -= chunk_size
        
        logger.debug(
            f"Dequeued chunk {chunk.get('chunkId')}: "
            f"queue_size={len(self.queue)}, memory={self.total_memory_bytes} bytes"
        )
        
        return chunk
    
    def dequeue_all(self) -> List[Dict[str, Any]]:
        """Dequeue all buffered chunks as a list and clear queue.
        
        Returns:
            list: List of audio chunk dictionaries; empty list if queue was empty.
        """
        chunks = list(self.queue)
        self.queue.clear()
        self.total_memory_bytes = 0
        
        logger.info(f"Dequeued all {len(chunks)} buffered chunks")
        return chunks
    
    def get_queue_size(self) -> int:
        """Get the current number of chunks in queue.
        
        Returns:
            int: Number of buffered chunks.
        """
        return len(self.queue)
    
    def get_memory_usage(self) -> int:
        """Get the current memory usage in bytes.
        
        Returns:
            int: Total bytes of all buffered audio blobs.
        """
        return self.total_memory_bytes
    
    def is_empty(self) -> bool:
        """Check if queue is empty.
        
        Returns:
            bool: True if no chunks buffered, False otherwise.
        """
        return len(self.queue) == 0
    
    def is_at_capacity(self) -> bool:
        """Check if queue is at or exceeding capacity limits.
        
        Returns:
            bool: True if at chunk count OR memory limit, False otherwise.
        """
        return (len(self.queue) >= self.max_chunks) or (self.total_memory_bytes >= self.max_memory_bytes)
    
    def clear(self) -> None:
        """Clear all buffered chunks and reset state."""
        chunk_count = len(self.queue)
        self.queue.clear()
        self.total_memory_bytes = 0
        logger.info(f"Cleared audio queue ({chunk_count} chunks dropped)")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics for monitoring.
        
        Returns:
            dict: Statistics including queue_size, memory_bytes, capacity_percent.
        """
        queue_size = len(self.queue)
        memory_usage = self.total_memory_bytes
        
        # Calculate capacity percentage (worst of two limits)
        count_percent = (queue_size / self.max_chunks) * 100 if self.max_chunks > 0 else 0
        memory_percent = (memory_usage / self.max_memory_bytes) * 100 if self.max_memory_bytes > 0 else 0
        capacity_percent = max(count_percent, memory_percent)
        
        return {
            'queue_size': queue_size,
            'memory_bytes': memory_usage,
            'capacity_percent': capacity_percent,
            'max_chunks': self.max_chunks,
            'max_memory_bytes': self.max_memory_bytes,
        }

