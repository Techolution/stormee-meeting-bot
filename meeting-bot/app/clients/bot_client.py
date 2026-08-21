"""
HTTP client for communicating with individual meeting-bot instances.

The handler talks to the Bot through this client. It must not contain Kubernetes logic.
Implements async HTTP client with lazy-initialized connection pool, exponential backoff
retry logic, exception handling, structured logging, and in-memory metrics tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.exceptions import (
    BotClientConnectionError,
    BotClientResponseError,
    BotClientTimeoutError,
    ConfigurationError,
)

logger = logging.getLogger(__name__)


class BotClient:
    """Async HTTP client for bot service communication with resilience.

    Features:
    - Lazy-initialized httpx.AsyncClient for connection pooling
    - Exponential backoff retry logic (5xx retryable, 4xx non-retryable)
    - Timeout exception handling (immediate escalation)
    - Custom error exception propagation
    - Structured request/response logging
    - In-memory metrics tracking
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
    ) -> None:
        """Initialize BotClient with configuration.

        Args:
            base_url: Base URL for the bot service (e.g., 'http://bot:8000').
            timeout_seconds: Request timeout in seconds (default: 5.0).
            max_retries: Maximum number of retry attempts (default: 2).

        Raises:
            ConfigurationError: If base_url is empty.
        """
        if not base_url or not base_url.strip():
            raise ConfigurationError("BotClient base_url must not be empty")

        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

        # Metrics
        self._request_count = 0
        self._error_count = 0
        self._timeout_count = 0
        self._latency_sum_ms = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the pooled client, creating it on first use.

        Uses asyncio.Lock for thread-safe lazy initialization.
        """
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self._timeout_seconds),
                        headers={
                            "User-Agent": "BotClient/1.0",
                            "Accept": "application/json",
                        },
                        follow_redirects=True,
                    )
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client and reset the connection."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> BotClient:
        """Support async context manager entry."""
        await self._get_client()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Support async context manager exit."""
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        expected_statuses: Iterable[int] = (200, 201, 202, 204),
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a request with exponential backoff retry logic.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: Request path (appended to base_url).
            operation: Operation name for logging (e.g., 'start_recording').
            expected_statuses: HTTP statuses considered successful.
            **kwargs: Additional arguments passed to httpx.AsyncClient.request().

        Returns:
            httpx.Response object on success.

        Raises:
            BotClientTimeoutError: On timeout (no retry).
            BotClientConnectionError: On connection failure after retries.
            BotClientResponseError: On non-success status after retries.
        """
        client = await self._get_client()
        url = f"{self._base_url}/{path.lstrip('/')}"
        expected = frozenset(expected_statuses)

        for attempt in range(1, self._max_retries + 2):
            start_time = time.perf_counter()

            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException as error:
                self._timeout_count += 1
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._latency_sum_ms += elapsed_ms
                logger.error(
                    "Bot request timeout",
                    extra={
                        "operation": operation,
                        "attempt": attempt,
                        "reason": f"timeout after {self._timeout_seconds}s",
                        "latency_ms": round(elapsed_ms, 2),
                    },
                )
                raise BotClientTimeoutError(
                    f"{operation} timed out after {self._timeout_seconds}s"
                ) from error
            except httpx.ConnectError as error:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._latency_sum_ms += elapsed_ms
                if attempt < self._max_retries + 1:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Bot connection failed, retrying",
                        extra={
                            "operation": operation,
                            "attempt": attempt,
                            "reason": f"connection error: {error}",
                            "backoff_seconds": backoff,
                        },
                    )
                    await asyncio.sleep(backoff)
                    continue

                self._error_count += 1
                logger.error(
                    "Bot connection failed after retries",
                    extra={
                        "operation": operation,
                        "attempts": attempt,
                        "reason": str(error),
                    },
                )
                raise BotClientConnectionError(
                    f"{operation} failed to connect after {attempt} attempts"
                ) from error
            except httpx.TransportError as error:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._latency_sum_ms += elapsed_ms
                if attempt < self._max_retries + 1:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Bot transport error, retrying",
                        extra={
                            "operation": operation,
                            "attempt": attempt,
                            "reason": f"transport error: {error}",
                            "backoff_seconds": backoff,
                        },
                    )
                    await asyncio.sleep(backoff)
                    continue

                self._error_count += 1
                logger.error(
                    "Bot transport error after retries",
                    extra={
                        "operation": operation,
                        "attempts": attempt,
                        "reason": str(error),
                    },
                )
                raise BotClientConnectionError(
                    f"{operation} transport error after {attempt} attempts"
                ) from error

            # Handle response status codes
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._latency_sum_ms += elapsed_ms

            if response.status_code in expected:
                self._request_count += 1
                logger.debug(
                    "Bot request succeeded",
                    extra={
                        "operation": operation,
                        "status": response.status_code,
                        "attempt": attempt,
                        "latency_ms": round(elapsed_ms, 2),
                    },
                )
                return response

            # 4xx errors: non-retryable, fail immediately
            if 400 <= response.status_code < 500:
                self._error_count += 1
                body = response.text[:300] if response.content else ""
                logger.error(
                    "Bot request client error",
                    extra={
                        "operation": operation,
                        "status": response.status_code,
                        "body": body,
                        "attempt": attempt,
                    },
                )
                raise BotClientResponseError(
                    f"{operation} returned {response.status_code}",
                    http_status=response.status_code,
                    attempts=attempt,
                )

            # 5xx errors: retryable
            if attempt < self._max_retries + 1:
                backoff = 0.5 * (2 ** (attempt - 1))
                logger.warning(
                    "Bot request server error, retrying",
                    extra={
                        "operation": operation,
                        "status": response.status_code,
                        "attempt": attempt,
                        "backoff_seconds": backoff,
                    },
                )
                await asyncio.sleep(backoff)
                continue

            # 5xx after max retries: fail
            self._error_count += 1
            body = response.text[:300] if response.content else ""
            logger.error(
                "Bot request server error after retries",
                extra={
                    "operation": operation,
                    "status": response.status_code,
                    "body": body,
                    "attempts": attempt,
                },
            )
            raise BotClientResponseError(
                f"{operation} returned {response.status_code} after {attempt} attempts",
                http_status=response.status_code,
                attempts=attempt,
            )

    async def get(
        self,
        path: str,
        *,
        operation: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform a GET request and return the JSON response.

        Args:
            path: Request path.
            operation: Operation name for logging.
            **kwargs: Additional arguments passed to request().

        Returns:
            Parsed JSON response as dict.
        """
        response = await self.request("GET", path, operation=operation, **kwargs)
        return response.json()

    async def post(
        self,
        path: str,
        *,
        operation: str,
        json: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform a POST request and return the JSON response.

        Args:
            path: Request path.
            operation: Operation name for logging.
            json: JSON payload to send.
            **kwargs: Additional arguments passed to request().

        Returns:
            Parsed JSON response as dict.
        """
        response = await self.request(
            "POST", path, operation=operation, json=json, **kwargs
        )
        return response.json()

    def metrics(self) -> dict[str, Any]:
        """Return in-memory metrics collected during client lifetime.

        Returns:
            Dict with request_count, error_count, timeout_count, latency_ms_total,
            and latency_ms_avg.
        """
        avg_latency = (
            self._latency_sum_ms / self._request_count
            if self._request_count > 0
            else 0.0
        )
        return {
            "request_count": self._request_count,
            "error_count": self._error_count,
            "timeout_count": self._timeout_count,
            "latency_ms_total": round(self._latency_sum_ms, 2),
            "latency_ms_avg": round(avg_latency, 2),
        }

