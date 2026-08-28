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


class TestParseEnvFunctions(unittest.TestCase):
    """_parse_env_float and _parse_env_int fall back to defaults on bad values."""

    def _reload_http(self):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod

    def test_parse_env_float_invalid_falls_back_to_default(self):
        http_mod = self._reload_http()
        with patch.dict("os.environ", {"HTTP_TIMEOUT": "not-a-float"}):
            result = http_mod._parse_env_float("HTTP_TIMEOUT", 30.0)
        self.assertEqual(result, 30.0)

    def test_parse_env_float_valid_returns_value(self):
        http_mod = self._reload_http()
        with patch.dict("os.environ", {"HTTP_TIMEOUT": "15.5"}):
            result = http_mod._parse_env_float("HTTP_TIMEOUT", 30.0)
        self.assertEqual(result, 15.5)

    def test_parse_env_int_invalid_falls_back_to_default(self):
        http_mod = self._reload_http()
        with patch.dict("os.environ", {"HTTP_RETRIES": "not-an-int"}):
            result = http_mod._parse_env_int("HTTP_RETRIES", 3)
        self.assertEqual(result, 3)

    def test_parse_env_int_valid_returns_value(self):
        http_mod = self._reload_http()
        with patch.dict("os.environ", {"HTTP_RETRIES": "5"}):
            result = http_mod._parse_env_int("HTTP_RETRIES", 3)
        self.assertEqual(result, 5)


class TestBuildUrlAbsolute(unittest.TestCase):
    """_build_url handles absolute URLs and params on absolute URLs."""

    def _client(self):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://base.example.com")

    def test_absolute_url_passthrough(self):
        client = self._client()
        url = client._build_url("https://other.example.com/path")
        self.assertIn("other.example.com", url)
        self.assertIn("/path", url)

    def test_absolute_url_with_params_replaces_query(self):
        """When an absolute URL is given with params, params replace the existing query."""
        client = self._client()
        url = client._build_url("https://other.example.com/path?old=1", params={"new": "value"})
        self.assertIn("new=value", url)
        self.assertNotIn("old=1", url)

    def test_absolute_url_without_params_keeps_existing_query(self):
        """When no params are passed for an absolute URL, the existing query is preserved."""
        client = self._client()
        url = client._build_url("https://other.example.com/path?keep=me")
        self.assertIn("keep=me", url)

    def test_relative_path_with_params(self):
        client = self._client()
        url = client._build_url("/endpoint", params={"key": "val"})
        self.assertIn("key=val", url)
        self.assertIn("base.example.com", url)


class TestDebugLogging(unittest.TestCase):
    """_log_request and _log_response fire when DEBUG logging is enabled."""

    def test_log_request_fires_on_debug(self):
        import logging
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", session=session)
            client.logger.setLevel(logging.DEBUG)
            with patch.object(client.logger, "debug") as mock_debug:
                client.get("/path")
        self.assertTrue(mock_debug.called)

    def test_log_response_fires_on_debug(self):
        import logging
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"response-body")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", session=session)
            client.logger.setLevel(logging.DEBUG)
            with patch.object(client.logger, "debug") as mock_debug:
                client.get("/endpoint")
        # At least two debug calls: one for request, one for response
        self.assertGreaterEqual(mock_debug.call_count, 2)


class TestLogTransient(unittest.TestCase):
    """_log_transient handles 429 with Retry-After and non-429 with debug."""

    def _client(self):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://example.com")

    def test_429_with_retry_after_logs_warning(self):
        client = self._client()
        with patch.object(client.logger, "warning") as mock_warn:
            client._log_transient(429, "GET", "https://example.com/x", 0, 60)
        mock_warn.assert_called_once()
        logged = mock_warn.call_args[0][0]
        self.assertIn("Retry-After=60s", logged)

    def test_429_without_retry_after_logs_warning_no_retry_after(self):
        client = self._client()
        with patch.object(client.logger, "warning") as mock_warn:
            client._log_transient(429, "GET", "https://example.com/x", 0, None)
        mock_warn.assert_called_once()
        logged = mock_warn.call_args[0][0]
        self.assertNotIn("Retry-After", logged)

    def test_non_429_transient_with_debug_enabled_logs_debug(self):
        import logging
        client = self._client()
        client.logger.setLevel(logging.DEBUG)
        with patch.object(client.logger, "isEnabledFor", return_value=True):
            with patch.object(client.logger, "debug") as mock_debug:
                client._log_transient(500, "GET", "https://example.com/x", 0, None)
        mock_debug.assert_called_once()


class TestHandleConnectionError(unittest.TestCase):
    """_handle_connection_error logs on debug and retries or re-raises."""

    def _client(self, retries=3):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://example.com", retries=retries)

    def test_returns_true_and_sleeps_when_attempts_remain(self):
        client = self._client(retries=3)
        exc = Exception("connection refused")
        with patch("time.sleep") as mock_sleep:
            result = client._handle_connection_error(exc, "GET", "https://example.com/x", 0)
        self.assertTrue(result)
        mock_sleep.assert_called_once()

    def test_returns_false_on_last_attempt(self):
        client = self._client(retries=3)
        exc = Exception("connection refused")
        with patch("time.sleep") as mock_sleep:
            result = client._handle_connection_error(exc, "GET", "https://example.com/x", 2)
        self.assertFalse(result)
        mock_sleep.assert_not_called()

    def test_debug_log_fires_when_enabled(self):
        import logging
        client = self._client(retries=3)
        client.logger.setLevel(logging.DEBUG)
        exc = Exception("connection refused")
        with patch("time.sleep"):
            with patch.object(client.logger, "isEnabledFor", return_value=True):
                with patch.object(client.logger, "debug") as mock_debug:
                    client._handle_connection_error(exc, "GET", "https://example.com/x", 0)
        mock_debug.assert_called_once()


class TestHandleTimeoutError(unittest.TestCase):
    """_handle_timeout_error logs on debug and retries or re-raises."""

    def _client(self, retries=3):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://example.com", retries=retries)

    def test_returns_true_and_sleeps_when_attempts_remain(self):
        client = self._client(retries=3)
        with patch("time.sleep") as mock_sleep:
            result = client._handle_timeout_error("GET", "https://example.com/x", 0)
        self.assertTrue(result)
        mock_sleep.assert_called_once()

    def test_returns_false_on_last_attempt(self):
        client = self._client(retries=3)
        with patch("time.sleep") as mock_sleep:
            result = client._handle_timeout_error("GET", "https://example.com/x", 2)
        self.assertFalse(result)
        mock_sleep.assert_not_called()

    def test_debug_log_fires_when_enabled(self):
        import logging
        client = self._client(retries=3)
        client.logger.setLevel(logging.DEBUG)
        with patch("time.sleep"):
            with patch.object(client.logger, "isEnabledFor", return_value=True):
                with patch.object(client.logger, "debug") as mock_debug:
                    client._handle_timeout_error("GET", "https://example.com/x", 0)
        mock_debug.assert_called_once()


def _make_requests_stub_with_errors(queue_factory) -> types.ModuleType:
    """Build a stub where the queue is populated *after* exception classes are created.

    This ensures the exceptions raised by the session and those caught by
    _attempt_request (which lazily imports the same stub) are the same class.
    """
    stub = _make_requests_stub([])  # creates exception classes
    queue = queue_factory(stub)     # caller builds queue using stub's exceptions

    class _SessionWithQueue:
        def __init__(self):
            self._responses = list(queue)
            self.calls: list[dict] = []

        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            if not self._responses:
                raise AssertionError("No queued response")
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    stub.Session = _SessionWithQueue  # type: ignore[attr-defined]
    return stub


class TestConnectionErrorAndTimeoutInRequest(unittest.TestCase):
    """ConnectionError and Timeout in _attempt_request trigger retries or re-raise.

    The exception classes used in the queue must come from the *same* stub that is
    registered in sys.modules, otherwise the except-clauses in _attempt_request
    (which import 'requests' lazily) catch a different class than the one raised.
    """

    def test_connection_error_then_success_retries(self):
        import importlib

        def make_queue(stub):
            return [stub.exceptions.ConnectionError("refused"), stub._Resp(200, b"ok")]

        requests_stub = _make_requests_stub_with_errors(make_queue)
        session = requests_stub.Session()
        with patch("time.sleep"):
            with patch.dict("sys.modules", {"requests": requests_stub}, clear=False):
                import core.http as http_mod
                importlib.reload(http_mod)
                client = http_mod.HttpClient("https://example.com", retries=2, session=session)
                resp = client.get("/path")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 2)

    def test_connection_error_exhausted_raises(self):
        import importlib

        def make_queue(stub):
            return [stub.exceptions.ConnectionError("refused")]

        requests_stub = _make_requests_stub_with_errors(make_queue)
        session = requests_stub.Session()
        with patch("time.sleep"):
            with patch.dict("sys.modules", {"requests": requests_stub}, clear=False):
                import core.http as http_mod
                importlib.reload(http_mod)
                client = http_mod.HttpClient("https://example.com", retries=1, session=session)
                with self.assertRaises(requests_stub.exceptions.ConnectionError):
                    client.get("/path")

    def test_timeout_then_success_retries(self):
        import importlib

        def make_queue(stub):
            return [stub.exceptions.Timeout("timed out"), stub._Resp(200, b"ok")]

        requests_stub = _make_requests_stub_with_errors(make_queue)
        session = requests_stub.Session()
        with patch("time.sleep"):
            with patch.dict("sys.modules", {"requests": requests_stub}, clear=False):
                import core.http as http_mod
                importlib.reload(http_mod)
                client = http_mod.HttpClient("https://example.com", retries=2, session=session)
                resp = client.get("/path")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(session.calls), 2)

    def test_timeout_exhausted_raises(self):
        import importlib

        def make_queue(stub):
            return [stub.exceptions.Timeout("timed out")]

        requests_stub = _make_requests_stub_with_errors(make_queue)
        session = requests_stub.Session()
        with patch("time.sleep"):
            with patch.dict("sys.modules", {"requests": requests_stub}, clear=False):
                import core.http as http_mod
                importlib.reload(http_mod)
                client = http_mod.HttpClient("https://example.com", retries=1, session=session)
                with self.assertRaises(requests_stub.exceptions.Timeout):
                    client.get("/path")


class TestConvenienceMethods(unittest.TestCase):
    """post, patch, put, delete convenience methods delegate to request()."""

    def _run_method(self, method_name: str) -> tuple:
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", session=session)
            method = getattr(client, method_name)
            resp = method("/endpoint")
        return resp, session

    def test_post_delegates_to_request(self):
        resp, session = self._run_method("post")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.calls[0]["method"], "POST")

    def test_patch_delegates_to_request(self):
        resp, session = self._run_method("patch")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.calls[0]["method"], "PATCH")

    def test_put_delegates_to_request(self):
        resp, session = self._run_method("put")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.calls[0]["method"], "PUT")

    def test_delete_delegates_to_request(self):
        resp, session = self._run_method("delete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.calls[0]["method"], "DELETE")


class TestStreamedResponse(unittest.TestCase):
    """Stream mode logs '<streamed>' instead of content length."""

    def test_stream_logs_streamed_not_length(self):
        import logging
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"chunk")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        debug_calls = []
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com", session=session)
            client.logger.setLevel(logging.DEBUG)

            def capture_debug(msg, *args, **kwargs):
                debug_calls.append(msg % args if args else msg)

            with patch.object(client.logger, "isEnabledFor", return_value=True):
                with patch.object(client.logger, "debug", side_effect=capture_debug):
                    from core.http import HttpRequestBody
                    client.request("GET", "/stream", body=HttpRequestBody(stream=True))
        streamed_logs = [m for m in debug_calls if "<streamed>" in m]
        self.assertGreater(len(streamed_logs), 0)


class TestAdditionalBranchCoverage(unittest.TestCase):
    """Covers remaining branches: _log_response debug, _log_transient non-debug, headers merge.

    These tests avoid importlib.reload so coverage instruments the same code object
    the client executes. Reload creates a new code object that coverage does not track.
    """

    def test_log_response_debug_line_executed(self):
        """_log_response emits a debug log when the logger level is DEBUG."""
        import logging
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com")
        client.logger.setLevel(logging.DEBUG)
        with patch.object(client.logger, "debug") as mock_debug:
            client._log_response("GET", "https://example.com/x", 200, 42)
        mock_debug.assert_called_once()

    def test_log_transient_non_429_debug_disabled_no_debug_call(self):
        """_log_transient with non-429 status and debug disabled calls neither warning nor debug."""
        import logging
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient("https://example.com")
        client.logger.setLevel(logging.WARNING)  # disable DEBUG
        with patch.object(client.logger, "debug") as mock_debug:
            with patch.object(client.logger, "warning") as mock_warn:
                # Force isEnabledFor to return False for the elif branch
                with patch.object(client.logger, "isEnabledFor", return_value=False):
                    client._log_transient(500, "GET", "https://example.com/x", 0, None)
        mock_debug.assert_not_called()
        mock_warn.assert_not_called()

    def test_request_merges_extra_headers(self):
        """Extra headers passed to get() are merged into the request."""
        import importlib
        requests = _make_requests_stub([])
        resp_obj = requests._Resp(200, b"ok")
        requests2 = _make_requests_stub([resp_obj])
        session = requests2.Session()
        with patch.dict("sys.modules", {"requests": requests2}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            client = http_mod.HttpClient(
                "https://example.com",
                default_headers={"X-Default": "yes"},
                session=session,
            )
            client.get("/path", headers={"X-Extra": "extra-value"})
        merged = session.calls[0]["headers"]
        self.assertEqual(merged.get("X-Default"), "yes")
        self.assertEqual(merged.get("X-Extra"), "extra-value")


class TestRetryAfterInSleepForRetry(unittest.TestCase):
    """_sleep_for_retry uses retry_after as a floor when server supplies it."""

    def _client(self):
        import importlib
        requests = _make_requests_stub([])
        with patch.dict("sys.modules", {"requests": requests}, clear=False):
            import core.http as http_mod
            importlib.reload(http_mod)
            return http_mod.HttpClient("https://example.com")

    def test_sleep_uses_retry_after_as_floor(self):
        client = self._client()
        with patch("time.sleep") as mock_sleep:
            # retry_after=30 should be the floor; computed backoff for attempt=0 would be ~1s
            client._sleep_for_retry(0, retry_after=30)
        mock_sleep.assert_called_once()
        slept = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(slept, 30)

    def test_sleep_without_retry_after_uses_computed_backoff(self):
        client = self._client()
        with patch("time.sleep") as mock_sleep:
            client._sleep_for_retry(0, retry_after=None)
        mock_sleep.assert_called_once()
        slept = mock_sleep.call_args[0][0]
        # Computed backoff for attempt=0 is around 1s with jitter; ceiling is 10s
        self.assertLessEqual(slept, 10.0 * 1.35)  # allow for jitter ceiling


if __name__ == "__main__":
    unittest.main()
