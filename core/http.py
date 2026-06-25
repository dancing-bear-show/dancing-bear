"""Thin requests-based HTTP client with retry and secret masking."""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from core.secrets import mask_headers, mask_url

# ---------------------------------------------------------------------------
# Env var names and defaults
# ---------------------------------------------------------------------------

ENV_HTTP_TIMEOUT = "HTTP_TIMEOUT"
ENV_HTTP_RETRIES = "HTTP_RETRIES"
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_HTTP_RETRIES = 3

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers: dict[str, str] = default_headers or {}
        self.timeout = timeout if timeout is not None else _parse_env_float(ENV_HTTP_TIMEOUT, DEFAULT_HTTP_TIMEOUT)
        raw_retries = retries if retries is not None else _parse_env_int(ENV_HTTP_RETRIES, DEFAULT_HTTP_RETRIES)
        self.retries = max(1, raw_retries)  # always allow at least one attempt
        self.logger = logging.getLogger(f"http.{self.__class__.__name__}")
        self._session = _make_session()

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
        """Return Retry-After seconds from response headers, or None."""
        try:
            ra = response.headers.get("Retry-After")
            if ra:
                return int(str(ra).strip())
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

    def _log_response(self, method: str, url: str, status: int, length: int) -> None:
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug("%s %s -> %d (%d bytes)", method, mask_url(url), status, length)

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
        backoff = min(2 ** attempt, 10)
        delay = max(backoff, retry_after) if retry_after is not None else backoff
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
        *,
        data: Any = None,
        json: Any = None,
        files: Any = None,
        stream: bool = False,
    ) -> Any:
        """Execute a single HTTP attempt; returns response or None to retry, raises on terminal error."""
        import requests as _requests  # noqa: PLC0415 - intentional lazy import

        self._log_request(method, url, hdrs, attempt)
        try:
            resp = self._session.request(
                method.upper(), url, headers=hdrs, data=data, json=json,
                files=files, timeout=self.timeout, stream=stream,
            )
            if self.logger.isEnabledFor(logging.DEBUG):
                self._log_response(method, url, resp.status_code, len(resp.content))
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
        data: Any = None,
        json: Any = None,
        files: Any = None,
        stream: bool = False,
    ) -> Any:
        """Make an HTTP request with retry logic, returning a requests.Response."""
        url = self._build_url(path, params)
        hdrs: dict[str, str] = dict(self.default_headers)
        if headers:
            hdrs.update(headers)

        for attempt in range(self.retries):
            resp = self._attempt_request(method, url, hdrs, attempt, data=data, json=json, files=files, stream=stream)
            if resp is not None:
                return resp

        raise RuntimeError(f"request failed after {self.retries} attempts: {method} {url}")

    def get(self, path: str, **kw: Any) -> Any:
        """GET request."""
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        """POST request."""
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        """PATCH request."""
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        """PUT request."""
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        """DELETE request."""
        return self.request("DELETE", path, **kw)
