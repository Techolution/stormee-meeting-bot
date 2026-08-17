"""Redis-based meeting state manager for tracking bot lifecycle events.

Provides a plug-and-play state management system using Redis to track:
- Meeting join/leave status
- Recording start/stop status
- Caption start/stop status
- Chat scraping start/stop status
- Participant count changes

Can be disabled or removed without affecting core functionality.
"""

import logging
import json
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
import redis
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError

from utilities.env_config import config

logger = logging.getLogger(__name__)


class MeetingState(str, Enum):
    """Enumeration of possible meeting states."""
    INITIALIZED = "initialized"
    JOINING = "joining"
    JOINED = "joined"
    IN_MEETING = "in_meeting"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    CAPTION_STARTED = "caption_started"
    CAPTION_STOPPED = "caption_stopped"
    CHAT_SCRAPING_STARTED = "chat_scraping_started"
    CHAT_SCRAPING_STOPPED = "chat_scraping_stopped"
    PARTICIPANT_COUNT_CHANGED = "participant_count_changed"
    LEFT = "left"
    ERROR = "error"


class RedisStateManager:
    """Manages meeting state persistence using Redis.
    
    Features:
    - Automatic TTL-based state expiration
    - Graceful degradation if Redis is unavailable
    - JSON serialization for complex state objects
    - Thread-safe operations
    - Detailed logging for debugging
    """
    
    def __init__(self):
        """Initialize Redis connection pool.
        
        Reads configuration from environment:
        - REDIS_HOST: Redis server hostname
        - REDIS_PORT: Redis server port
        - REDIS_DB: Redis database number
        - REDIS_PASSWORD: Optional Redis password
        - MEETING_STATE_TTL: State expiration time in seconds
        """
        self.redis_client: Optional[redis.Redis] = None
        self.is_enabled = False
        self.ttl = 3600  # Default 1 hour
        self.initialization_error: Optional[str] = None
        
        try:
            # Check if state manager is enabled
            try:
                redis_enabled_raw = config.get_bool("REDIS_ENABLED")
            except (ValueError, KeyError, TypeError):
                redis_enabled_raw = True
            
            if not redis_enabled_raw:
                self.is_enabled = False
                logger.info(
                    "\n" + "="*70
                    + "\n⚪ Redis State Manager: DISABLED via configuration (REDIS_ENABLED=false)"
                    + "\n" + "="*70
                )
                return
            
            # Get configuration
            redis_host = config.get("REDIS_HOST", default="localhost")
            redis_port = config.get_int("REDIS_PORT")
            redis_db = config.get_int("REDIS_DB")
            redis_password = config.get("REDIS_PASSWORD", default=None)
            self.ttl = config.get_int("MEETING_STATE_TTL")
            
            logger.info(
                f"\n" + "="*70
                + f"\n🔄 Redis State Manager: Connecting..."
                + f"\n   Host: {redis_host}:{redis_port}"
                + f"\n   Database: {redis_db}"
                + f"\n   State TTL: {self.ttl}s"
                + f"\n" + "="*70
            )
            
            # Create Redis connection
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password if redis_password else None,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
            
            # Test connection
            self.redis_client.ping()
            self.is_enabled = True
            
            logger.info(
                f"\n" + "="*70
                + f"\n✅ Redis State Manager: CONNECTED SUCCESSFULLY"
                + f"\n   Host: {redis_host}:{redis_port}"
                + f"\n   Database: {redis_db}"
                + f"\n   State TTL: {self.ttl}s"
                + f"\n   Status: Ready to track meeting states"
                + f"\n" + "="*70
                + "\n"
            )
            
        except ConnectionError as e:
            self.is_enabled = False
            self.redis_client = None
            self.initialization_error = str(e)
            logger.error(
                f"\n" + "="*70
                + f"\n❌ Redis State Manager: CONNECTION FAILED"
                + f"\n   Error: Connection refused to {config.get('REDIS_HOST', default='localhost')}:{config.get_int('REDIS_PORT')}"
                + f"\n   Details: {e}"
                + f"\n   Action: Ensure Redis server is running and accessible"
                + f"\n   Status: State tracking DISABLED (meeting bot will work normally)"
                + f"\n" + "="*70
                + "\n"
            )
        except Exception as e:
            self.is_enabled = False
            self.redis_client = None
            self.initialization_error = str(e)
            error_type = type(e).__name__
            logger.error(
                f"\n" + "="*70
                + f"\n❌ Redis State Manager: INITIALIZATION FAILED"
                + f"\n   Error Type: {error_type}"
                + f"\n   Details: {e}"
                + f"\n   Status: State tracking DISABLED (meeting bot will work normally)"
                + f"\n" + "="*70
                + "\n"
            )
    
    async def set_state(
        self,
        meeting_id: str,
        state: MeetingState,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Set the state of a meeting.
        
        Args:
            meeting_id: Unique identifier for the meeting
            state: The state to set (MeetingState enum)
            metadata: Optional additional data to store with the state
        
        Returns:
            True if state was set successfully, False if disabled or error
        """
        if not self.is_enabled or not self.redis_client:
            return False
        
        try:
            key = f"meeting:{meeting_id}:state"
            
            state_data = {
                "state": state.value,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {}
            }
            
            # Store state as JSON with TTL
            self.redis_client.setex(
                key,
                self.ttl,
                json.dumps(state_data)
            )
            
            # Also store in history
            history_key = f"meeting:{meeting_id}:history"
            self.redis_client.lpush(
                history_key,
                json.dumps(state_data)
            )
            
            # Set history TTL
            self.redis_client.expire(history_key, self.ttl)
            
            logger.debug(
                f"State updated for {meeting_id}: {state.value}"
            )
            return True
            
        except (ConnectionError, RedisTimeoutError) as e:
            logger.warning(
                f"Redis connection error while setting state for {meeting_id}: {e}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Error setting state for {meeting_id}: {e}"
            )
            return False
    
    async def get_state(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Get the current state of a meeting.
        
        Args:
            meeting_id: Unique identifier for the meeting
        
        Returns:
            Dictionary with state data or None if not found/disabled
        """
        if not self.is_enabled or not self.redis_client:
            return None
        
        try:
            key = f"meeting:{meeting_id}:state"
            data = self.redis_client.get(key)
            
            if not data:
                return None
            
            return json.loads(data)
            
        except (ConnectionError, RedisTimeoutError) as e:
            logger.warning(
                f"Redis connection error while getting state for {meeting_id}: {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Error getting state for {meeting_id}: {e}"
            )
            return None
    
    async def get_state_history(
        self,
        meeting_id: str,
        limit: int = 100,
    ) -> list:
        """Get the state history for a meeting.
        
        Args:
            meeting_id: Unique identifier for the meeting
            limit: Maximum number of history items to return
        
        Returns:
            List of state history items (most recent first)
        """
        if not self.is_enabled or not self.redis_client:
            return []
        
        try:
            history_key = f"meeting:{meeting_id}:history"
            data = self.redis_client.lrange(history_key, 0, limit - 1)
            
            if not data:
                return []
            
            return [json.loads(item) for item in data]
            
        except (ConnectionError, RedisTimeoutError) as e:
            logger.warning(
                f"Redis connection error while getting history for {meeting_id}: {e}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error getting history for {meeting_id}: {e}"
            )
            return []
    
    async def delete_state(self, meeting_id: str) -> bool:
        """Delete all state data for a meeting.
        
        Args:
            meeting_id: Unique identifier for the meeting
        
        Returns:
            True if deleted successfully, False if disabled or error
        """
        if not self.is_enabled or not self.redis_client:
            return False
        
        try:
            state_key = f"meeting:{meeting_id}:state"
            history_key = f"meeting:{meeting_id}:history"
            
            # Delete both state and history
            self.redis_client.delete(state_key)
            self.redis_client.delete(history_key)
            
            logger.debug(f"State deleted for {meeting_id}")
            return True
            
        except (ConnectionError, RedisTimeoutError) as e:
            logger.warning(
                f"Redis connection error while deleting state for {meeting_id}: {e}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Error deleting state for {meeting_id}: {e}"
            )
            return False
    
    async def cleanup(self) -> None:
        """Cleanup Redis connection."""
        try:
            if self.redis_client:
                self.redis_client.close()
                logger.info("Redis connection closed")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")


# Global singleton instance
_state_manager: Optional[RedisStateManager] = None


def get_state_manager() -> RedisStateManager:
    """Get or create the global state manager instance.
    
    Returns:
        RedisStateManager instance (may be disabled if Redis unavailable)
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = RedisStateManager()
    return _state_manager

