"""Thin requests-based HTTP client with retry and secret masking."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from core.retry import jitter_backoff
from core.secrets import mask_headers, mask_url

# ---------------------------------------------------------------------------
# Env var names and defaults
# ---------------------------------------------------------------------------

ENV_HTTP_TIMEOUT = "HTTP_TIMEOUT"
ENV_HTTP_RETRIES = "HTTP_RETRIES"
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_HTTP_RETRIES = 3

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Hard ceiling on a self-computed retry delay, in seconds. A server-supplied
# Retry-After may exceed it; our own backoff may not.
_MAX_RETRY_BACKOFF = 10.0


@dataclass
class HttpRequestBody:
    """Optional request body parameters grouped for HttpClient.request."""

    data: Any = None
    json: Any = None
    files: Any = None
    stream: bool = False


def _parse_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:  # nosec B110 - fall back to default on any parse error
        return default


def _parse_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:  # nosec B110 - fall back to default on any parse error
        return default


def _make_session():  # type: ignore[return]
    """Lazy-import requests and return a new Session."""
    import requests  # noqa: PLC0415 - intentional lazy import

    return requests.Session()


class HttpClient:
    """requests.Session wrapper with retries and secret masking."""

    def __init__(
        self,
        base_url: str,
        default_headers: dict[str, str] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        session: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers: dict[str, str] = default_headers or {}
        self.timeout = timeout if timeout is not None else _parse_env_float(ENV_HTTP_TIMEOUT, DEFAULT_HTTP_TIMEOUT)
        raw_retries = retries if retries is not None else _parse_env_int(ENV_HTTP_RETRIES, DEFAULT_HTTP_RETRIES)
        self.retries = max(1, raw_retries)  # always allow at least one attempt
        self.logger = logging.getLogger(f"http.{self.__class__.__name__}")
        self._session = session if session is not None else _make_session()

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Join base_url + path, appending query params if provided.

        If path is an absolute URL (has a scheme), it is used directly as the URL.
        """
        path = path or ""
        path_parts = urlsplit(path)
        if path_parts.scheme:
            # path is already an absolute URL; use it directly
            query = urlencode(params or {}, doseq=True) if params else path_parts.query
            return urlunsplit((path_parts.scheme, path_parts.netloc, path_parts.path, query, ""))
        parts = urlsplit(self.base_url)
        base_path = parts.path.rstrip("/")
        sub = path.lstrip("/")
        combined = f"{base_path}/{sub}" if sub else base_path
        query = urlencode(params or {}, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, combined, query, ""))

    def _parse_retry_after(self, response: Any) -> int | None:
        """Return Retry-After seconds from response headers, or None.

        Handles both delta-seconds (RFC 9110 §10.2.4) and HTTP-date formats.
        """
        try:
            ra = response.headers.get("Retry-After")
            if not ra:
                return None
            value = str(ra).strip()
            try:
                return int(value)
            except ValueError:
                pass
            # Try HTTP-date format (e.g. "Wed, 25 Jun 2026 15:00:00 GMT")
            from email.utils import parsedate_to_datetime  # noqa: PLC0415 - stdlib lazy import
            dt = parsedate_to_datetime(value)
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(delta))
        except Exception:  # nosec B110 - header may be absent or malformed
            pass
        return None

    def _log_request(self, method: str, url: str, hdrs: dict[str, str], attempt: int) -> None:
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug(
            "%s %s (attempt %d/%d, timeout=%ss) headers=%s",
            method, mask_url(url), attempt + 1, self.retries, self.timeout, mask_headers(hdrs),
        )

    def _log_response(self, method: str, url: str, status: int, length: int | str) -> None:
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug("%s %s -> %d (%s bytes)", method, mask_url(url), status, length)

    def _log_transient(self, status: int, method: str, url: str, attempt: int, retry_after: int | None) -> None:
        if status == 429:
            msg = f"HTTP 429 rate limited: {method} {mask_url(url)} (attempt {attempt + 1}/{self.retries})"
            if retry_after is not None:
                msg += f"; Retry-After={retry_after}s"
            self.logger.warning(msg)
        elif self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "HTTP %d transient error for %s %s (attempt %d/%d)",
                status, method, mask_url(url), attempt + 1, self.retries,
            )

    def _sleep_for_retry(self, attempt: int, retry_after: int | None) -> None:
        # Jitter spreads concurrent retries so the up-to-16 threads in
        # core/parallel.py stop backing off in lockstep against a shared rate
        # limit. jitter_backoff applies its +/-30% band *after* its own clamp,
        # so it can return up to 13s for a 10s max_delay -- clamp again here to
        # keep the hard ceiling the previous min(2 ** attempt, 10) guaranteed.
        computed = min(
            jitter_backoff(attempt, base_delay=1.0, multiplier=2.0, max_delay=_MAX_RETRY_BACKOFF),
            _MAX_RETRY_BACKOFF,
        )
        # A server-supplied Retry-After is a hard floor: jitter must not reduce
        # the delay below what the server requested, and the ceiling above does
        # not apply to it -- the server's instruction wins over our own cap.
        delay = max(computed, retry_after) if retry_after is not None else computed
        time.sleep(delay)

    def _should_retry_response(self, resp: Any, method: str, url: str, attempt: int) -> bool:
        """Return True and schedule sleep if the response warrants a retry."""
        if resp.status_code not in _RETRYABLE_STATUS_CODES or attempt >= self.retries - 1:
            return False
        retry_after = self._parse_retry_after(resp)
        self._log_transient(resp.status_code, method, url, attempt, retry_after)
        self._sleep_for_retry(attempt, retry_after)
        return True

    def _handle_connection_error(self, exc: Exception, method: str, url: str, attempt: int) -> bool:
        """Log a ConnectionError and return True if a retry should be attempted."""
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "%s %s network error: %s (attempt %d/%d)",
                method, mask_url(url), exc, attempt + 1, self.retries,
            )
        if attempt < self.retries - 1:
            self._sleep_for_retry(attempt, None)
            return True
        return False

    def _handle_timeout_error(self, method: str, url: str, attempt: int) -> bool:
        """Log a Timeout and return True if a retry should be attempted."""
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "%s %s timed out (attempt %d/%d)",
                method, mask_url(url), attempt + 1, self.retries,
            )
        if attempt < self.retries - 1:
            self._sleep_for_retry(attempt, None)
            return True
        return False

    def _attempt_request(
        self,
        method: str,
        url: str,
        hdrs: dict[str, str],
        attempt: int,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """Execute a single HTTP attempt; returns response or None to retry, raises on terminal error."""
        import requests as _requests  # noqa: PLC0415 - intentional lazy import

        b = body or HttpRequestBody()
        self._log_request(method, url, hdrs, attempt)
        try:
            resp = self._session.request(
                method.upper(), url, headers=hdrs, data=b.data, json=b.json,
                files=b.files, timeout=self.timeout, stream=b.stream,
            )
            if self.logger.isEnabledFor(logging.DEBUG):
                content_len: int | str = "<streamed>" if b.stream else len(resp.content)
                self._log_response(method, url, resp.status_code, content_len)  # type: ignore[arg-type]
            if self._should_retry_response(resp, method, url, attempt):
                resp.close()
                return None
            resp.raise_for_status()
            return resp
        except _requests.exceptions.ConnectionError as exc:
            if self._handle_connection_error(exc, method, url, attempt):
                return None
            raise
        except _requests.exceptions.Timeout:
            if self._handle_timeout_error(method, url, attempt):
                return None
            raise

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """Make an HTTP request with retry logic, returning a requests.Response."""
        url = self._build_url(path, params)
        hdrs: dict[str, str] = dict(self.default_headers)
        if headers:
            hdrs.update(headers)

        for attempt in range(self.retries):
            resp = self._attempt_request(method, url, hdrs, attempt, body)
            if resp is not None:
                return resp

        raise RuntimeError(f"request failed after {self.retries} attempts: {method} {mask_url(url)}")

    def get(
        self, path: str, *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """GET request."""
        return self.request("GET", path, params=params, headers=headers, body=body)

    def post(
        self, path: str, *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """POST request."""
        return self.request("POST", path, params=params, headers=headers, body=body)

    def patch(
        self, path: str, *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """PATCH request."""
        return self.request("PATCH", path, params=params, headers=headers, body=body)

    def put(
        self, path: str, *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """PUT request."""
        return self.request("PUT", path, params=params, headers=headers, body=body)

    def delete(
        self, path: str, *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: HttpRequestBody | None = None,
    ) -> Any:
        """DELETE request."""
        return self.request("DELETE", path, params=params, headers=headers, body=body)
