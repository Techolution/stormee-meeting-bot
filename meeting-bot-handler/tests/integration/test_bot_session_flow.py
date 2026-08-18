"""
Integration tests for the complete bot session lifecycle.

Tests cover the full end-to-end flow:
1. Start a session (bot joins meeting)
2. Start recording
3. Start transcription
4. Get status
5. Stop recording
6. Stop transcription
7. Leave session

These tests use mocked httpx to simulate the bot service responses.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.application.bot_handler import BotHandler
from app.bootstrap import create_bot_handler


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_bot_handler():
    """Create a mock BotHandler."""
    handler = MagicMock(spec=BotHandler)
    handler.start_bot = AsyncMock()
    handler.start_recording = AsyncMock()
    handler.stop_recording = AsyncMock()
    handler.start_transcription = AsyncMock()
    handler.stop_transcription = AsyncMock()
    handler.leave = AsyncMock()
    handler.stop = AsyncMock()
    handler.get_status = AsyncMock(return_value={"status": "active", "recording": True})
    return handler


class TestBotSessionLifecycle:
    """Test the complete bot session lifecycle."""

    def test_start_session(self, client, mock_bot_handler):
        """Test starting a session."""
        session_id = "test-meeting-123"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/start")
            
            assert response.status_code == 202
            data = response.json()
            assert data["session_id"] == session_id
            assert "started" in data["message"].lower()
            mock_bot_handler.start_bot.assert_called_once_with(session_id)

    def test_start_recording(self, client, mock_bot_handler):
        """Test starting recording."""
        session_id = "test-meeting-456"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/recording/start")
            
            assert response.status_code == 202
            data = response.json()
            assert data["session_id"] == session_id
            assert "recording" in data["message"].lower()
            mock_bot_handler.start_recording.assert_called_once_with(session_id)

    def test_stop_recording(self, client, mock_bot_handler):
        """Test stopping recording."""
        session_id = "test-meeting-789"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/recording/stop")
            
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id
            mock_bot_handler.stop_recording.assert_called_once_with(session_id)

    def test_start_transcription(self, client, mock_bot_handler):
        """Test starting transcription."""
        session_id = "test-meeting-trans1"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/transcription/start")
            
            assert response.status_code == 202
            data = response.json()
            assert data["session_id"] == session_id
            assert "transcription" in data["message"].lower()
            mock_bot_handler.start_transcription.assert_called_once_with(session_id)

    def test_stop_transcription(self, client, mock_bot_handler):
        """Test stopping transcription."""
        session_id = "test-meeting-trans2"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/transcription/stop")
            
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id
            mock_bot_handler.stop_transcription.assert_called_once_with(session_id)

    def test_get_session_status(self, client, mock_bot_handler):
        """Test getting session status."""
        session_id = "test-meeting-status"
        expected_status = {"status": "active", "recording": True, "transcription": True}
        mock_bot_handler.get_status.return_value = expected_status
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.get(f"/bot-sessions/{session_id}/status")
            
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id
            assert data["status"] == expected_status
            mock_bot_handler.get_status.assert_called_once_with(session_id)

    def test_leave_session(self, client, mock_bot_handler):
        """Test leaving a session."""
        session_id = "test-meeting-leave"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/leave")
            
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id
            assert "left" in data["message"].lower()
            mock_bot_handler.leave.assert_called_once_with(session_id)

    def test_stop_session(self, client, mock_bot_handler):
        """Test stopping a session."""
        session_id = "test-meeting-stop"
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_bot_handler):
            response = client.post(f"/bot-sessions/{session_id}/stop")
            
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id
            assert "stopped" in data["message"].lower()
            mock_bot_handler.stop.assert_called_once_with(session_id)


class TestBotSessionErrors:
    """Test error handling in bot session endpoints."""

    def test_start_session_error(self, client):
        """Test error handling when start_bot fails."""
        session_id = "test-meeting-error"
        mock_handler = MagicMock(spec=BotHandler)
        mock_handler.start_bot = AsyncMock(side_effect=Exception("Bot service unavailable"))
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_handler):
            response = client.post(f"/bot-sessions/{session_id}/start")
            
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "Failed to start session" in data["detail"]

    def test_get_status_error(self, client):
        """Test error handling when get_status fails."""
        session_id = "test-meeting-status-error"
        mock_handler = MagicMock(spec=BotHandler)
        mock_handler.get_status = AsyncMock(side_effect=httpx.HTTPStatusError(
            "404 Not Found", request=None, response=None
        ))
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_handler):
            response = client.get(f"/bot-sessions/{session_id}/status")
            
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "Failed to get session status" in data["detail"]


class TestBotSessionSequenceFlow:
    """Test the complete sequence of operations."""

    def test_full_session_lifecycle(self, client):
        """Test the full session lifecycle: start -> record -> transcribe -> leave."""
        session_id = "test-meeting-full-flow"
        mock_handler = MagicMock(spec=BotHandler)
        mock_handler.start_bot = AsyncMock()
        mock_handler.start_recording = AsyncMock()
        mock_handler.start_transcription = AsyncMock()
        mock_handler.get_status = AsyncMock(return_value={"status": "active"})
        mock_handler.stop_recording = AsyncMock()
        mock_handler.stop_transcription = AsyncMock()
        mock_handler.leave = AsyncMock()
        
        with patch('app.api.routes.bot.create_bot_handler', return_value=mock_handler):
            # Start session
            response = client.post(f"/bot-sessions/{session_id}/start")
            assert response.status_code == 202
            
            # Start recording
            response = client.post(f"/bot-sessions/{session_id}/recording/start")
            assert response.status_code == 202
            
            # Start transcription
            response = client.post(f"/bot-sessions/{session_id}/transcription/start")
            assert response.status_code == 202
            
            # Get status
            response = client.get(f"/bot-sessions/{session_id}/status")
            assert response.status_code == 200
            assert response.json()["session_id"] == session_id
            
            # Stop recording
            response = client.post(f"/bot-sessions/{session_id}/recording/stop")
            assert response.status_code == 200
            
            # Stop transcription
            response = client.post(f"/bot-sessions/{session_id}/transcription/stop")
            assert response.status_code == 200
            
            # Leave session
            response = client.post(f"/bot-sessions/{session_id}/leave")
            assert response.status_code == 200
            
            # Verify all methods were called with correct session_id
            mock_handler.start_bot.assert_called_once_with(session_id)
            mock_handler.start_recording.assert_called_once_with(session_id)
            mock_handler.start_transcription.assert_called_once_with(session_id)
            mock_handler.get_status.assert_called_once_with(session_id)
            mock_handler.stop_recording.assert_called_once_with(session_id)
            mock_handler.stop_transcription.assert_called_once_with(session_id)
            mock_handler.leave.assert_called_once_with(session_id)

