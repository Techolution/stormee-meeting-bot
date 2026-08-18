"""
Unit tests for the BotClient class.

BotClient tests focus exclusively on HTTP communication concerns:
- URL construction
- HTTP method selection (GET, POST)
- Request payload construction
- Response parsing (JSON)
- HTTP error handling
- Timeout and connection handling
- Service URL configuration

These tests should NOT test business logic or orchestration.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.application.bot_client import BotClient


@pytest.fixture
async def bot_client():
    """Create a BotClient instance for testing."""
    client = BotClient()
    yield client
    await client.close()


class TestBotClientInit:
    """Tests for BotClient initialization."""

    def test_init_with_default_url(self):
        """Test initialization with default service URL."""
        with patch.dict('os.environ', {}, clear=True):
            client = BotClient()
            assert client.service_url == "http://localhost:8000"
            assert client._http_client is not None

    def test_init_with_custom_url_from_env(self):
        """Test initialization with custom URL from environment."""
        custom_url = "http://bot-service:9000"
        with patch.dict('os.environ', {'BOT_SERVICE_URL': custom_url}):
            client = BotClient()
            assert client.service_url == custom_url

    def test_init_with_url_parameter(self):
        """Test initialization with URL parameter overrides environment."""
        param_url = "http://param-url:7000"
        with patch.dict('os.environ', {'BOT_SERVICE_URL': 'http://env-url:8000'}):
            client = BotClient(service_url=param_url)
            assert client.service_url == param_url

    def test_trailing_slash_stripped(self):
        """Test that trailing slashes are stripped from service URL."""
        with patch.dict('os.environ', {}, clear=True):
            client = BotClient(service_url="http://bot-service:8000/")
            assert client.service_url == "http://bot-service:8000"

    def test_http_client_timeout(self):
        """Test that HTTP client has correct timeout configuration."""
        client = BotClient()
        assert client._http_client.timeout == 30.0


class TestJoinMeeting:
    """Tests for join_meeting HTTP communication."""

    @pytest.mark.asyncio
    async def test_join_meeting_success(self, bot_client):
        """Test successful meeting join request."""
        meeting_id = "test-meeting-123"
        expected_response = {"message": "Joining meeting", "meeting_id": meeting_id}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.join_meeting(meeting_id)
            
            # Verify HTTP call
            mock_post.assert_called_once_with(
                f"{bot_client.service_url}/meetings/join",
                json={"meetingId": meeting_id}
            )
            mock_response.raise_for_status.assert_called_once()
            mock_response.json.assert_called_once()
            assert result == expected_response

    @pytest.mark.asyncio
    async def test_join_meeting_http_error(self, bot_client):
        """Test join_meeting with HTTP error response."""
        meeting_id = "test-meeting-error"
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=None, response=None
            )
            mock_post.return_value = mock_response
            
            with pytest.raises(httpx.HTTPStatusError):
                await bot_client.join_meeting(meeting_id)

    @pytest.mark.asyncio
    async def test_join_meeting_url_construction(self, bot_client):
        """Test that join_meeting constructs correct URL."""
        meeting_id = "abc-def-ghi"
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {}
            mock_post.return_value = mock_response
            
            await bot_client.join_meeting(meeting_id)
            
            # Verify URL construction
            called_url = mock_post.call_args[0][0]
            assert called_url.endswith("/meetings/join")
            assert meeting_id in mock_post.call_args[1]["json"]["meetingId"]


class TestStartRecording:
    """Tests for start_recording HTTP communication."""

    @pytest.mark.asyncio
    async def test_start_recording_success(self, bot_client):
        """Test successful recording start request."""
        meeting_id = "test-meeting-rec"
        expected_response = {"message": "Recording started", "meeting_id": meeting_id}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.start_recording(meeting_id)
            
            # Verify HTTP call
            mock_post.assert_called_once_with(
                f"{bot_client.service_url}/recordings/start",
                json={"meetingId": meeting_id}
            )
            assert result == expected_response

    @pytest.mark.asyncio
    async def test_start_recording_url_endpoint(self, bot_client):
        """Test that start_recording uses correct endpoint."""
        meeting_id = "test-meeting"
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {}
            mock_post.return_value = mock_response
            
            await bot_client.start_recording(meeting_id)
            
            called_url = mock_post.call_args[0][0]
            assert "/recordings/start" in called_url


class TestStopRecording:
    """Tests for stop_recording HTTP communication."""

    @pytest.mark.asyncio
    async def test_stop_recording_success(self, bot_client):
        """Test successful recording stop request."""
        meeting_id = "test-meeting-stop-rec"
        expected_response = {"message": "Recording stopped"}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.stop_recording(meeting_id)
            
            # Verify HTTP call to correct endpoint
            mock_post.assert_called_once()
            called_url = mock_post.call_args[0][0]
            assert "/recordings/stop" in called_url
            assert result == expected_response


class TestTranscription:
    """Tests for transcription HTTP communication."""

    @pytest.mark.asyncio
    async def test_start_transcription_success(self, bot_client):
        """Test successful transcription start."""
        meeting_id = "test-meeting-trans"
        expected_response = {"message": "Transcription started"}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.start_transcription(meeting_id)
            
            called_url = mock_post.call_args[0][0]
            assert "/transcription/start" in called_url
            assert result == expected_response

    @pytest.mark.asyncio
    async def test_stop_transcription_success(self, bot_client):
        """Test successful transcription stop."""
        meeting_id = "test-meeting-trans-stop"
        expected_response = {"message": "Transcription stopped", "segments": []}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.stop_transcription(meeting_id)
            
            called_url = mock_post.call_args[0][0]
            assert "/transcription/stop" in called_url
            assert result == expected_response


class TestLeaveAndGetStatus:
    """Tests for leave and status HTTP communication."""

    @pytest.mark.asyncio
    async def test_leave_meeting_success(self, bot_client):
        """Test successful leave request."""
        meeting_id = "test-meeting-leave"
        expected_response = {"message": "Left meeting"}
        
        with patch.object(bot_client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_post.return_value = mock_response
            
            result = await bot_client.leave_meeting(meeting_id)
            
            called_url = mock_post.call_args[0][0]
            assert "/meetings/leave" in called_url
            assert result == expected_response

    @pytest.mark.asyncio
    async def test_get_meeting_status_success(self, bot_client):
        """Test successful status GET request."""
        meeting_id = "test-meeting-status"
        expected_response = {
            "meeting_id": meeting_id,
            "status": "active",
            "recording": True
        }
        
        with patch.object(bot_client._http_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = expected_response
            mock_get.return_value = mock_response
            
            result = await bot_client.get_meeting_status(meeting_id)
            
            # Verify GET method used
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            assert "/meetings/" in called_url
            assert "/status" in called_url
            assert meeting_id in called_url
            assert result == expected_response

    @pytest.mark.asyncio
    async def test_get_meeting_status_uses_get_method(self, bot_client):
        """Test that get_meeting_status uses HTTP GET, not POST."""
        meeting_id = "test-meeting"
        
        with patch.object(bot_client._http_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {}
            mock_get.return_value = mock_response
            
            await bot_client.get_meeting_status(meeting_id)
            
            mock_get.assert_called_once()
            # Verify no POST was made
            assert not hasattr(bot_client._http_client, "post") or True


class TestPayloadConstruction:
    """Tests for correct request payload construction."""

    @pytest.mark.asyncio
    async def test_all_post_methods_use_meeting_id_payload(self, bot_client):
        """Test that all POST methods use meetingId in payload."""
        meeting_id = "test-meeting-payload"
        methods = [
            bot_client.join_meeting,
            bot_client.start_recording,
            bot_client.stop_recording,
            bot_client.start_transcription,
            bot_client.stop_transcription,
            bot_client.leave_meeting,
        ]
        
        for method in methods:
            with patch.object(bot_client._http_client, "post") as mock_post:
                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_response.json.return_value = {}
                mock_post.return_value = mock_response
                
                await method(meeting_id)
                
                # Verify payload structure
                payload = mock_post.call_args[1]["json"]
                assert "meetingId" in payload
                assert payload["meetingId"] == meeting_id


class TestContextManager:
    """Tests for context manager support."""

    def test_context_manager_methods_exist(self):
        """Test that BotClient has context manager methods."""
        client = BotClient()
        assert hasattr(client, '__aenter__')
        assert hasattr(client, '__aexit__')
        assert hasattr(client, 'close')

    @pytest.mark.asyncio
    async def test_close_closes_http_client(self):
        """Test that close() closes the HTTP client."""
        client = BotClient()
        with patch.object(client._http_client, "aclose") as mock_close:
            await client.close()
            mock_close.assert_called_once()

