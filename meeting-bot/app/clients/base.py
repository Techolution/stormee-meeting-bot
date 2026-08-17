"""Shared HTTP client behaviour.

Every outbound integration needs the same things: a connection pool that
outlives a single call, a timeout, retries on transient failures, consistent
logging, and translation of transport errors into
:class:`~app.core.exceptions.ExternalServiceError`. Putting that in one base
class keeps each concrete client down to the endpoints it actually owns.

Clients are constructed once and closed at shutdown. Creating an
``httpx.AsyncClient`` per request — as the previous implementation did — throws
away connection pooling and makes every call pay a fresh TLS handshake.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

#: Statuses worth retrying: the upstream is briefly unavailable, not wrong.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class BaseHTTPClient:
    """Async HTTP client with retries, structured logging and error translation."""

    #: Name used in logs and error messages. Override in subclasses.
    service_name: str = "http"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_seconds
        self._default_headers = dict(headers or {})
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the pooled client, creating it on first use."""
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self._timeout),
                        headers={"accept": "application/json", **self._default_headers},
                        follow_redirects=True,
                    )
        return self._client

    async def aclose(self) -> None:
        """Release the connection pool. Call once, at shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> BaseHTTPClient:
        await self._get_client()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        expected_statuses: Iterable[int] = (200, 201, 202, 204),
        retry_statuses: Iterable[int] = RETRYABLE_STATUS_CODES,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a request, retrying transient failures.

        Args:
            method: HTTP verb.
            path: Absolute URL, or a path appended to ``base_url``.
            operation: Short name used in logs, e.g. ``"upload_file"``.
            expected_statuses: Statuses treated as success.
            retry_statuses: Statuses that trigger a retry.
            **kwargs: Forwarded to ``httpx.AsyncClient.request``.

        Raises:
            ExternalServiceError: On non-success status after retries, or on a
                transport error.
        """
        if not self.is_configured:
            raise ExternalServiceError(self.service_name, "no base URL configured")

        client = await self._get_client()
        url = self._url(path)
        expected = frozenset(expected_statuses)
        retryable = frozenset(retry_statuses)
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 2):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException as error:
                last_error = error
                self._log_retry(operation, attempt, f"timeout after {self._timeout}s")
            except httpx.TransportError as error:
                last_error = error
                self._log_retry(operation, attempt, f"transport error: {error}")
            else:
                if response.status_code in expected:
                    logger.debug(
                        "Upstream call succeeded",
                        extra={
                            "service": self.service_name,
                            "operation": operation,
                            "status": response.status_code,
                            "attempt": attempt,
                        },
                    )
                    return response

                if response.status_code in retryable and attempt <= self._max_retries:
                    self._log_retry(operation, attempt, f"status {response.status_code}")
                    last_error = None
                else:
                    body = response.text[:300] if response.content else ""
                    logger.error(
                        "Upstream call failed",
                        extra={
                            "service": self.service_name,
                            "operation": operation,
                            "status": response.status_code,
                            "body": body,
                        },
                    )
                    raise ExternalServiceError(
                        self.service_name,
                        f"{operation} returned {response.status_code}",
                        status=response.status_code,
                        details={"body": body},
                    )

            if attempt <= self._max_retries:
                await asyncio.sleep(self._retry_backoff * (2 ** (attempt - 1)))

        raise ExternalServiceError(
            self.service_name,
            f"{operation} failed after {self._max_retries + 1} attempts",
            details={"cause": str(last_error) if last_error else "exhausted retries"},
        )

    def _log_retry(self, operation: str, attempt: int, reason: str) -> None:
        logger.warning(
            "Upstream call attempt failed",
            extra={
                "service": self.service_name,
                "operation": operation,
                "attempt": attempt,
                "max_attempts": self._max_retries + 1,
                "reason": reason,
            },
        )

    async def get_json(self, path: str, *, operation: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request("GET", path, operation=operation, **kwargs)
        return _decode_json(response, self.service_name, operation)

    async def post_json(self, path: str, *, operation: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request("POST", path, operation=operation, **kwargs)
        return _decode_json(response, self.service_name, operation)


def _decode_json(response: httpx.Response, service: str, operation: str) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as error:
        raise ExternalServiceError(
            service,
            f"{operation} returned a non-JSON body",
            status=response.status_code,
            details={"body": response.text[:300]},
        ) from error
    return payload if isinstance(payload, dict) else {"data": payload}
