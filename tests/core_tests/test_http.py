"""Unit tests for core/http.py HttpClient."""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch


def _make_requests_stub(responses: list) -> types.ModuleType:
    """Build a minimal stub requests module with a Session that returns queued responses."""
    requests = types.ModuleType("requests")

    class _HTTPError(Exception):
        def __init__(self, *args, response=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.response = response

    class _ConnectionError(Exception):  # noqa: N818 - fake exception matching requests interface
        """Stub for requests.exceptions.ConnectionError."""

    class _Timeout(Exception):  # noqa: N818 - fake exception matching requests interface
        """Stub for requests.exceptions.Timeout."""

    # Build an _Exceptions namespace using a module to avoid S116 (class field casing)
    exceptions_mod = types.ModuleType("requests.exceptions")
    exceptions_mod.HTTPError = _HTTPError  # type: ignore[attr-defined]
    exceptions_mod.ConnectionError = _ConnectionError  # type: ignore[attr-defined]
    exceptions_mod.Timeout = _Timeout  # type: ignore[attr-defined]

    class _Resp:
        def __init__(self, status: int = 200, body: bytes = b"hello"):
            self.status_code = status
            self.content = body
            self.text = body.decode()
            self.headers: dict[str, str] = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _HTTPError(f"HTTP {self.status_code}", response=self)

        def close(self):
            """No-op — stub response has no underlying connection to close."""

    class _Session:
        def __init__(self):
            self._responses = list(responses)
            self.calls: list[dict] = []

        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            if not self._responses:
                raise AssertionError("No queued response")
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    requests.exceptions = exceptions_mod  # type: ignore[attr-defined]
    requests.Session = _Session  # type: ignore[attr-defined]
    requests._Resp = _Resp  # type: ignore[attr-defined]  # expose for convenience
    return requests


class TestHttpClientGet(unittest.TestCase):
    """Successful GET returns the response."""

    def test_get_success(self):
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests = _make_requests_stub([resp_obj])
        session = requests.Session()
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            from core.http import HttpClient
            client = HttpClient("https://example.com", session=session)
            resp = client.get("/path")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertIn("/path", session.calls[0]["url"])


class TestHttpClientRetry(unittest.TestCase):
    """Retries on transient errors and succeeds on eventual 200."""

    def _run_with_responses(self, statuses: list[int]) -> tuple:
        import importlib
        requests = _make_requests_stub([])
        resps = [requests._Resp(s, b"body") for s in statuses]
        requests2 = _make_requests_stub(resps)
        session = requests2.Session()
        with patch("time.sleep"):
            with patch.dict("sys.modules", {"requests": requests2}, clear=False):
                import core.http as http_mod
                importlib.reload(http_mod)
                client = http_mod.HttpClient("https://example.com", retries=len(statuses), session=session)
                resp = client.get("/retry")
        return resp, session

    def test_retries_on_429_then_200(self):
        resp, session = self._run_with_responses([429, 200])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 2)

    def test_retries_on_500_then_200(self):
        resp, session = self._run_with_responses([500, 200])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 2)

    def test_retries_on_502_503_504_then_200(self):
        resp, session = self._run_with_responses([502, 503, 504, 200])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 4)


class TestHttpClientRetryClamp(unittest.TestCase):
    """HTTP_RETRIES=0 still makes exactly one attempt (clamp behavior)."""

    def test_zero_retries_makes_one_attempt(self):
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            # retries=0 → clamped to 1
            client = http_mod.HttpClient("https://example.com", retries=0, session=session)
            self.assertEqual(client.retries, 1)
            resp = client.get("/once")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 1)


class TestParseRetryAfter(unittest.TestCase):
    """_parse_retry_after handles integer, HTTP-date, and garbage."""

    def _client(self):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://example.com")

    def _make_resp(self, header_value: str | None):
        resp = MagicMock()
        resp.headers = {"Retry-After": header_value} if header_value else {}
        return resp

    def test_integer_string(self):
        client = self._client()
        resp = self._make_resp("42")
        self.assertEqual(client._parse_retry_after(resp), 42)

    def test_http_date_string(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
        # Format as RFC 1123 HTTP-date
        http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
        client = self._client()
        resp = self._make_resp(http_date)
        result = client._parse_retry_after(resp)
        self.assertIsNotNone(result)
        if result is not None:  # type narrowing for assertGreater/assertLessEqual
            self.assertGreater(result, 0)
            self.assertLessEqual(result, 35)  # within 5s tolerance

    def test_garbage_input_returns_none(self):
        client = self._client()
        resp = self._make_resp("not-a-date-or-int")
        self.assertIsNone(client._parse_retry_after(resp))

    def test_absent_header_returns_none(self):
        client = self._client()
        resp = self._make_resp(None)
        self.assertIsNone(client._parse_retry_after(resp))


class TestUrlMaskingInLog(unittest.TestCase):
    """mask_url is called in debug log; RuntimeError format uses mask_url."""

    def test_runtime_error_message_uses_mask_url(self):
        """Verify the RuntimeError format string passes the URL through mask_url."""
        import importlib
        import core.http as http_mod
        importlib.reload(http_mod)
        # Patch mask_url and directly inspect how request() formats the error.
        # We call request() on a client whose _attempt_request always returns None,
        # achieved by patching _attempt_request directly.
        requests = _make_requests_stub([])
        session = requests.Session()
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", retries=1, session=session)
            with patch.object(client, "_attempt_request", return_value=None):
                with patch("core.http.mask_url", return_value="MASKED") as mock_mask:
                    with self.assertRaises(RuntimeError) as ctx:
                        client.get("/secret?token=abc123")
        self.assertIn("MASKED", str(ctx.exception))
        self.assertTrue(mock_mask.called)

    def test_mask_url_called_in_debug_log(self):
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", session=session)
            with patch.object(client.logger, "isEnabledFor", return_value=True):
                with patch("core.http.mask_url", wraps=http_mod.mask_url) as mock_mask:
                    client.get("/path?token=secret")
        self.assertTrue(mock_mask.called)


if __name__ == "__main__":
    unittest.main()
