"""
Unit tests for the BotHandler class.

After refactoring, BotHandler tests focus on **orchestration logic only**.
HTTP communication is delegated to BotClient, which is mocked here.

Tests cover:
- Orchestration methods delegate to BotClient correctly
- Results from BotClient are returned to caller
- Exceptions from BotClient are properly propagated
- Handler lifecycle management (close, context manager)
- BotClient dependency injection

HTTP communication details are tested in test_bot_client.py.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.application.bot_handler import BotHandler
from app.application.bot_client import BotClient


@pytest.fixture
def mock_bot_client():
    """Create a mocked BotClient for testing."""
    mock_client = MagicMock(spec=BotClient)
    # All methods are async, so wrap them with AsyncMock
    mock_client.join_meeting = AsyncMock(return_value={"message": "Joined"})
    mock_client.start_recording = AsyncMock(return_value={"message": "Recording started"})
    mock_client.stop_recording = AsyncMock(return_value={"message": "Recording stopped"})
    mock_client.start_transcription = AsyncMock(return_value={"message": "Transcription started"})
    mock_client.stop_transcription = AsyncMock(return_value={"message": "Transcription stopped"})
    mock_client.leave_meeting = AsyncMock(return_value={"message": "Left meeting"})
    mock_client.get_meeting_status = AsyncMock(return_value={"status": "active"})
    mock_client.close = AsyncMock()
    return mock_client


@pytest.fixture
async def bot_handler(mock_bot_client):
    """Create a BotHandler instance with mocked BotClient for testing."""
    handler = BotHandler(bot_client=mock_bot_client)
    yield handler
    # Cleanup
    await handler.close()


class TestStartBot:
    """Tests for start_bot orchestration."""

    @pytest.mark.asyncio
    async def test_start_bot_delegates_to_bot_client(self, bot_handler, mock_bot_client):
        """Test that start_bot delegates to BotClient.join_meeting."""
        session_id = "test-meeting-123"
        expected_response = {"message": "Joined meeting", "session_id": session_id}
        mock_bot_client.join_meeting.return_value = expected_response
        
        result = await bot_handler.start_bot(session_id)
        
        # Verify delegation to BotClient
        mock_bot_client.join_meeting.assert_called_once_with(session_id)
        # Verify result is returned
        assert result == expected_response

    @pytest.mark.asyncio
    async def test_start_bot_propagates_bot_client_errors(self, bot_handler, mock_bot_client):
        """Test that start_bot propagates BotClient exceptions."""
        session_id = "test-meeting-456"
        mock_bot_client.join_meeting.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=None, response=None
        )
        
        with pytest.raises(httpx.HTTPStatusError):
            await bot_handler.start_bot(session_id)


class TestRecording:
    """Tests for recording orchestration methods."""

    @pytest.mark.asyncio
    async def test_start_recording_delegates(self, bot_handler, mock_bot_client):
        """Test that start_recording delegates to BotClient."""
        session_id = "test-meeting-rec"
        expected = {"message": "Recording started"}
        mock_bot_client.start_recording.return_value = expected
        
        result = await bot_handler.start_recording(session_id)
        
        mock_bot_client.start_recording.assert_called_once_with(session_id)
        assert result == expected

    @pytest.mark.asyncio
    async def test_stop_recording_delegates(self, bot_handler, mock_bot_client):
        """Test that stop_recording delegates to BotClient."""
        session_id = "test-meeting-stop-rec"
        expected = {"message": "Recording stopped"}
        mock_bot_client.stop_recording.return_value = expected
        
        result = await bot_handler.stop_recording(session_id)
        
        mock_bot_client.stop_recording.assert_called_once_with(session_id)
        assert result == expected


class TestTranscription:
    """Tests for transcription orchestration methods."""

    @pytest.mark.asyncio
    async def test_start_transcription_delegates(self, bot_handler, mock_bot_client):
        """Test that start_transcription delegates to BotClient."""
        session_id = "test-meeting-trans"
        expected = {"message": "Transcription started"}
        mock_bot_client.start_transcription.return_value = expected
        
        result = await bot_handler.start_transcription(session_id)
        
        mock_bot_client.start_transcription.assert_called_once_with(session_id)
        assert result == expected

    @pytest.mark.asyncio
    async def test_stop_transcription_delegates(self, bot_handler, mock_bot_client):
        """Test that stop_transcription delegates to BotClient."""
        session_id = "test-meeting-trans-stop"
        expected = {"message": "Transcription stopped"}
        mock_bot_client.stop_transcription.return_value = expected
        
        result = await bot_handler.stop_transcription(session_id)
        
        mock_bot_client.stop_transcription.assert_called_once_with(session_id)
        assert result == expected


class TestLeaveAndStop:
    """Tests for leave and stop orchestration methods."""

    @pytest.mark.asyncio
    async def test_leave_delegates(self, bot_handler, mock_bot_client):
        """Test that leave delegates to BotClient.leave_meeting."""
        session_id = "test-meeting-leave"
        expected = {"message": "Left meeting"}
        mock_bot_client.leave_meeting.return_value = expected
        
        result = await bot_handler.leave(session_id)
        
        mock_bot_client.leave_meeting.assert_called_once_with(session_id)
        assert result == expected

    @pytest.mark.asyncio
    async def test_stop_delegates(self, bot_handler, mock_bot_client):
        """Test that stop delegates to BotClient.leave_meeting (equivalent)."""
        session_id = "test-meeting-stop"
        expected = {"message": "Left meeting"}
        mock_bot_client.leave_meeting.return_value = expected
        
        result = await bot_handler.stop(session_id)
        
        # stop() calls leave_meeting
        mock_bot_client.leave_meeting.assert_called_once_with(session_id)
        assert result == expected

    @pytest.mark.asyncio
    async def test_leave_propagates_errors(self, bot_handler, mock_bot_client):
        """Test that leave propagates BotClient errors."""
        session_id = "test-meeting-error"
        mock_bot_client.leave_meeting.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=None, response=None
        )
        
        with pytest.raises(httpx.HTTPStatusError):
            await bot_handler.leave(session_id)


class TestGetStatus:
    """Tests for get_status orchestration method."""

    @pytest.mark.asyncio
    async def test_get_status_delegates(self, bot_handler, mock_bot_client):
        """Test that get_status delegates to BotClient.get_meeting_status."""
        session_id = "test-meeting-status"
        expected_status = {"status": "active", "recording": True}
        mock_bot_client.get_meeting_status.return_value = expected_status
        
        result = await bot_handler.get_status(session_id)
        
        mock_bot_client.get_meeting_status.assert_called_once_with(session_id)
        assert result == expected_status

    @pytest.mark.asyncio
    async def test_get_status_propagates_errors(self, bot_handler, mock_bot_client):
        """Test that get_status propagates BotClient errors."""
        session_id = "test-meeting-error"
        mock_bot_client.get_meeting_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=None, response=None
        )
        
        with pytest.raises(httpx.HTTPStatusError):
            await bot_handler.get_status(session_id)


class TestBotHandlerDependencyInjection:
    """Tests for BotHandler dependency injection."""

    def test_init_with_provided_bot_client(self, mock_bot_client):
        """Test initialization with provided BotClient."""
        handler = BotHandler(bot_client=mock_bot_client)
        assert handler.bot_client is mock_bot_client

    def test_init_creates_default_bot_client(self):
        """Test initialization creates BotClient if not provided."""
        handler = BotHandler()
        assert isinstance(handler.bot_client, BotClient)

    def test_context_manager(self, mock_bot_client):
        """Test context manager support."""
        handler = BotHandler(bot_client=mock_bot_client)
        assert hasattr(handler, '__aenter__')
        assert hasattr(handler, '__aexit__')

    @pytest.mark.asyncio
    async def test_close_delegates_to_bot_client(self, bot_handler, mock_bot_client):
        """Test that close() delegates to BotClient.close()."""
        await bot_handler.close()
        mock_bot_client.close.assert_called_once()

