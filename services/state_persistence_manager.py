"""State persistence module for AlloyDB.

Provides the StatePersisteceManager class for persisting and retrieving MeetBot state
from AlloyDB using connection pooling.
"""

import logging
from typing import Optional, Dict, Any
import psycopg2
from psycopg2 import pool, Error as DatabaseError
import json
from datetime import datetime

from utilities.env_config import config
from utilities.error_handler import retry_with_exponential_backoff, log_exception

logger = logging.getLogger(__name__)


class PersistenceError(Exception):
    """Base exception for persistence-related errors.
    
    Attributes:
        message: Error message.
        operation: Type of operation that failed ("save" or "retrieve").
        meeting_id: ID of the meeting related to the error.
    """
    def __init__(self, message: str, operation: Optional[str] = None, meeting_id: Optional[str] = None):
        self.message = message
        self.operation = operation
        self.meeting_id = meeting_id
        super().__init__(message)


class DatabaseConnectionError(PersistenceError):
    """Exception raised when database connection fails."""
    pass


class DatabaseOperationError(PersistenceError):
    """Exception raised when database operation fails."""
    pass


class MeetingNotFoundError(PersistenceError):
    """Exception raised when a meeting is not found in the database."""
    pass


class DatabaseUnavailableError(PersistenceError):
    """Exception raised when the database is unavailable or unreachable."""
    pass


class ConnectionTimeoutError(PersistenceError):
    """Exception raised when a database operation times out."""
    pass


class DataCorruptionError(PersistenceError):
    """Exception raised when stored data cannot be deserialized or is corrupted."""
    pass


class StatePersisteceManager:
    """Manages state persistence for MeetBot using AlloyDB.
    
    Handles database connection pooling, state serialization, and retrieval
    with retry logic and error handling.
    """
    
    def __init__(self):
        """Initialize StatePersisteceManager with AlloyDB connection pool.
        
        Reads configuration from:
        - ALLOYDB_HOST: Database host address
        - ALLOYDB_PORT: Database port number
        - ALLOYDB_USER: Database username
        - ALLOYDB_PASSWORD: Database password
        - CONNECTION_POOL_SIZE: Size of the connection pool
        
        Raises:
            DatabaseConnectionError: If configuration is invalid or pool initialization fails.
        """
        try:
            # Get configuration values with error handling
            self._validate_config()
            
            host = config.get('ALLOYDB_HOST')
            port = config.get('ALLOYDB_PORT')
            user = config.get('ALLOYDB_USER')
            password = config.get('ALLOYDB_PASSWORD')
            pool_size = config.get_int('CONNECTION_POOL_SIZE')
            
            logger.info(
                f"Initializing AlloyDB connection pool with pool size: {pool_size}"
            )
            
            # Initialize connection pool
            self._db_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=pool_size,
                host=host,
                port=int(port),
                user=user,
                password=password,
                database='postgres',
                connect_timeout=10
            )
            
            # Test the connection pool
            self._test_connection()
            
            logger.info("AlloyDB connection pool initialized successfully")
            
        except ValueError as e:
            error_msg = f"Invalid configuration: {str(e)}"
            logger.error(error_msg)
            raise DatabaseConnectionError(error_msg) from e
        except DatabaseError as e:
            error_msg = f"Database connection pool initialization failed: {str(e)}"
            log_exception(logger, logging.ERROR, error_msg, e, context={'host': host})
            raise DatabaseConnectionError(error_msg) from e
    
    def _validate_config(self) -> None:
        """Validate that all required configuration keys are present.
        
        Raises:
            ValueError: If any required configuration key is missing.
        """
        required_keys = [
            'ALLOYDB_HOST',
            'ALLOYDB_PORT',
            'ALLOYDB_USER',
            'ALLOYDB_PASSWORD',
            'CONNECTION_POOL_SIZE'
        ]
        
        for key in required_keys:
            try:
                if key == 'CONNECTION_POOL_SIZE':
                    config.get_int(key)
                else:
                    config.get(key)
            except ValueError as e:
                raise ValueError(
                    f"Required configuration key '{key}' is missing or invalid: {str(e)}"
                )
    
    def _test_connection(self) -> None:
        """Test database connection by acquiring and releasing a connection.
        
        Raises:
            DatabaseConnectionError: If connection test fails.
        """
        conn = None
        try:
            conn = self._db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            logger.debug("Database connection test successful")
        except DatabaseError as e:
            error_msg = f"Database connection test failed: {str(e)}"
            log_exception(logger, logging.ERROR, error_msg, e)
            raise DatabaseConnectionError(error_msg) from e
        finally:
            if conn:
                self._db_pool.putconn(conn)
    
    def get_connection(self):
        """Get a connection from the pool.
        
        Returns:
            Database connection object.
            
        Raises:
            DatabaseConnectionError: If unable to get connection from pool.
        """
        try:
            return self._db_pool.getconn()
        except Exception as e:
            error_msg = f"Failed to get connection from pool: {str(e)}"
            log_exception(logger, logging.ERROR, error_msg, e)
            raise DatabaseConnectionError(error_msg) from e
    
    def return_connection(self, conn) -> None:
        """Return a connection to the pool.
        
        Args:
            conn: Database connection to return to pool.
        """
        if conn:
            try:
                self._db_pool.putconn(conn)
            except Exception as e:
                logger.warning(f"Error returning connection to pool: {str(e)}")
    
    def close_pool(self) -> None:
        """Close the connection pool and all connections.
        
        Should be called during application shutdown.
        """
        try:
            self._db_pool.closeall()
            logger.info("AlloyDB connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing connection pool: {str(e)}")
    
    def _handle_persistence_error(
        self,
        exception: Exception,
        operation: str,
        meeting_id: str
    ) -> None:
        """Handle persistence errors with domain-specific classification.
        
        Classifies database exceptions into specific error categories and raises
        the appropriate PersistenceError subclass. This enables callers to distinguish
        between different failure modes and decide whether to retry, use stale state,
        or halt the session.
        
        Args:
            exception: The exception that was raised.
            operation: Type of operation that failed ("save" or "retrieve").
            meeting_id: ID of the meeting related to the error.
            
        Raises:
            MeetingNotFoundError: When a meeting_id query returns no results.
            DatabaseUnavailableError: When database is unreachable or offline.
            ConnectionTimeoutError: When database operation exceeds timeout.
            DataCorruptionError: When data deserialization or parsing fails.
            DatabaseOperationError: For other database operation failures.
        """
        # Build context information for logging
        context = {
            'meeting_id': meeting_id,
            'operation': operation,
            'exception_type': type(exception).__name__
        }
        
        exception_str = str(exception)
        exception_type_name = type(exception).__name__
        
        # Classify the exception
        if isinstance(exception, json.JSONDecodeError):
            # Data corruption: deserialization failed
            error_msg = f"Data corruption detected for meeting_id {meeting_id}: Failed to deserialize stored context"
            log_exception(logger, logging.ERROR, error_msg, exception, context)
            raise DataCorruptionError(
                error_msg,
                operation=operation,
                meeting_id=meeting_id
            ) from exception
        
        elif "timeout" in exception_str.lower() or isinstance(exception, TimeoutError):
            # Connection timeout: operation exceeded maximum time
            error_msg = f"Connection timeout during {operation} operation for meeting_id {meeting_id}"
            log_exception(logger, logging.ERROR, error_msg, exception, context)
            raise ConnectionTimeoutError(
                error_msg,
                operation=operation,
                meeting_id=meeting_id
            ) from exception
        
        elif any(phrase in exception_str.lower() for phrase in [
            "connection refused",
            "connection lost",
            "database offline",
            "no route to host",
            "connection reset",
            "broken pipe"
        ]):
            # Database unavailable: connection issues
            error_msg = f"Database unavailable during {operation} operation for meeting_id {meeting_id}"
            log_exception(logger, logging.ERROR, error_msg, exception, context)
            raise DatabaseUnavailableError(
                error_msg,
                operation=operation,
                meeting_id=meeting_id
            ) from exception
        
        elif "no rows" in exception_str.lower() or "not found" in exception_str.lower():
            # Meeting not found: query returned no results
            error_msg = f"Meeting not found in database: meeting_id {meeting_id}"
            log_exception(logger, logging.WARNING, error_msg, exception, context)
            raise MeetingNotFoundError(
                error_msg,
                operation=operation,
                meeting_id=meeting_id
            ) from exception
        
        else:
            # Generic database operation failure
            error_msg = f"Database operation failed during {operation} for meeting_id {meeting_id}: {exception_str}"
            log_exception(logger, logging.ERROR, error_msg, exception, context)
            raise DatabaseOperationError(
                error_msg,
                operation=operation,
                meeting_id=meeting_id
            ) from exception
    
    def _ensure_table_exists(self, conn) -> None:
        """Ensure the state persistence table exists, creating it if necessary.
        
        Args:
            conn: Database connection.
            
        Raises:
            DatabaseOperationError: If table creation fails.
        """
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meeting_state (
                    meeting_id VARCHAR(255) PRIMARY KEY,
                    context_data JSONB NOT NULL,
                    schema_version INT NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_updated_at (updated_at)
                )
            """)
            cursor.close()
            conn.commit()
            logger.debug("Meeting state table ensured to exist")
        except DatabaseError as e:
            if conn:
                conn.rollback()
            error_msg = f"Failed to ensure table existence: {str(e)}"
            log_exception(logger, logging.ERROR, error_msg, e)
            raise DatabaseOperationError(error_msg) from e
    
    @retry_with_exponential_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0, max_delay=60.0)
    def save(self, meeting_context: Dict[str, Any]) -> bool:
        """Save meeting context to AlloyDB with retry logic.
        
        Serializes the meeting context dictionary with schema version tracking
        for compatibility with evolving context structures. If the record exists,
        it is updated; otherwise, a new record is created.
        
        Args:
            meeting_context: Dictionary containing meeting context data.
                Must contain 'meeting_id' key.
        
        Returns:
            True if save was successful.
            
        Raises:
            DatabaseOperationError: If save operation fails after retries.
        """
        conn = None
        try:
            # Extract meeting_id from context
            meeting_id = meeting_context.get('meeting_id')
            if not meeting_id:
                raise ValueError("meeting_context must contain 'meeting_id' key")
            
            conn = self.get_connection()
            
            # Ensure table exists
            self._ensure_table_exists(conn)
            
            cursor = conn.cursor()
            
            # Serialize context data to JSON
            context_json = json.dumps(meeting_context)
            schema_version = 1
            timestamp = datetime.utcnow()
            
            # Upsert operation: insert or update based on meeting_id
            cursor.execute("""
                INSERT INTO meeting_state (meeting_id, context_data, schema_version, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (meeting_id) DO UPDATE SET
                    context_data = EXCLUDED.context_data,
                    schema_version = EXCLUDED.schema_version,
                    updated_at = EXCLUDED.updated_at
            """, (meeting_id, context_json, schema_version, timestamp, timestamp))
            
            cursor.close()
            conn.commit()
            
            logger.info(
                f"Successfully saved meeting state for meeting_id: {meeting_id}",
                extra={'meeting_id': meeting_id}
            )
            return True
            
        except ValueError as e:
            if conn:
                conn.rollback()
            error_msg = f"Invalid meeting context: {str(e)}"
            logger.error(error_msg)
            raise DatabaseOperationError(error_msg, operation='save', meeting_id='unknown') from e
        except DatabaseError as e:
            if conn:
                conn.rollback()
            meeting_id = meeting_context.get('meeting_id', 'unknown')
            try:
                self._handle_persistence_error(e, 'save', meeting_id)
            except PersistenceError:
                raise  # Re-raise the classified persistence error
        except json.JSONDecodeError as e:
            if conn:
                conn.rollback()
            meeting_id = meeting_context.get('meeting_id', 'unknown')
            try:
                self._handle_persistence_error(e, 'save', meeting_id)
            except PersistenceError:
                raise  # Re-raise the classified persistence error
        finally:
            self.return_connection(conn)
    
    @retry_with_exponential_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0, max_delay=60.0)
    def retrieve(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve meeting context from AlloyDB with retry logic.
        
        Queries AlloyDB by meeting_id and reconstructs the meeting context from
        stored JSON data. Returns None if the meeting_id is not found.
        
        Args:
            meeting_id: Unique identifier of the meeting to retrieve.
            
        Returns:
            Dictionary containing reconstructed meeting context, or None if not found.
            
        Raises:
            DatabaseOperationError: If retrieve operation fails after retries.
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Query the database for the meeting state
            cursor.execute("""
                SELECT context_data, schema_version, updated_at
                FROM meeting_state
                WHERE meeting_id = %s
            """, (meeting_id,))
            
            row = cursor.fetchone()
            cursor.close()
            
            if row is None:
                logger.info(
                    f"No state found in database for meeting_id: {meeting_id}",
                    extra={'meeting_id': meeting_id}
                )
                return None
            
            # Unpack the row
            context_json, schema_version, updated_at = row
            
            # Deserialize JSON context data
            meeting_context = json.loads(context_json)
            
            logger.info(
                f"Successfully retrieved meeting state for meeting_id: {meeting_id} (schema_version={schema_version}, updated_at={updated_at})",
                extra={'meeting_id': meeting_id, 'schema_version': schema_version}
            )
            
            return meeting_context
            
        except DatabaseError as e:
            try:
                self._handle_persistence_error(e, 'retrieve', meeting_id)
            except PersistenceError:
                raise  # Re-raise the classified persistence error
        except json.JSONDecodeError as e:
            try:
                self._handle_persistence_error(e, 'retrieve', meeting_id)
            except PersistenceError:
                raise  # Re-raise the classified persistence error
        finally:
            self.return_connection(conn)

