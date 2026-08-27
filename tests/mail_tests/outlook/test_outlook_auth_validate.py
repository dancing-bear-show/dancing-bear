"""Tests for run_outlook_auth_ensure and run_outlook_auth_validate functions."""

import io
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import TempDirMixin
from tests.mail_tests.fixtures import make_args
from tests.mail_tests.outlook.fixtures import make_fake_msal_module


def make_fake_requests_module(api_success=True):
    """Factory for creating fake requests modules with Session and exceptions support."""
    requests = types.ModuleType("requests")

    class _Exceptions:
        class HTTPError(Exception):
            def __init__(self, *args, response=None, **kwargs):
                super().__init__(*args, **kwargs)
                self.response = response

        class ConnectionError(Exception):
            pass

        class Timeout(Exception):
            pass

    class _Resp:
        def __init__(self):
            self.status_code = 200 if api_success else 401
            self.text = "OK" if api_success else "Unauthorized"
            self.content = b""
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _Exceptions.HTTPError(response=self)

    class _Session:
        def request(self, method, url, **kwargs):
            return _Resp()

        def get(self, url, **kwargs):
            return _Resp()

    requests.Session = _Session
    requests.exceptions = _Exceptions
    requests.get = lambda url, headers=None, **kw: _Resp()
    return requests


class TestRunOutlookAuthEnsure(TempDirMixin, unittest.TestCase):
    """Tests for run_outlook_auth_ensure function."""

    def test_ensure_with_valid_cache(self):
        """Test ensure when token cache is valid."""
        msal = make_fake_msal_module(has_accounts=True, silent_success=True)
        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Token cache valid", output)

    def test_ensure_with_interactive_flow(self):
        """Test ensure when interactive device flow is needed."""
        msal = make_fake_msal_module(has_accounts=False, device_success=True)
        token_path = Path(self.tmpdir) / "token.json"

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("ABC123", output)
        self.assertIn("Saved Outlook token cache", output)

    def test_ensure_missing_msal(self):
        """Test ensure with missing msal dependency."""
        args = make_args(client_id="test-client", tenant="consumers", token="token.json")  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": None}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 1)
        output = buf.getvalue()
        self.assertIn("Missing msal dependency", output)

    def test_ensure_missing_client_id(self):
        """Test ensure with missing client_id."""
        msal = make_fake_msal_module()
        args = make_args(client_id=None, tenant="consumers", token="token.json")  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            with patch("mail.outlook.auth_commands.resolve_outlook_credentials", return_value=(None, "consumers", "token.json")):
                from mail.outlook.auth_commands import run_outlook_auth_ensure

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 2)
        output = buf.getvalue()
        self.assertIn("Missing --client-id", output)

    def test_ensure_device_flow_failed(self):
        """Test ensure when device flow fails."""
        msal = make_fake_msal_module(has_accounts=False, device_success=False)
        token_path = Path(self.tmpdir) / "token.json"

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 1)
        output = buf.getvalue()
        self.assertIn("Failed to start device flow", output)

    def test_ensure_corrupt_cache_warning(self):
        """Test ensure with corrupt token cache."""
        msal = make_fake_msal_module(has_accounts=False, device_success=True)
        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("invalid json{{{")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf_out = io.StringIO()
            with redirect_stdout(buf_out):
                from contextlib import redirect_stderr
                with redirect_stderr(io.StringIO()):
                    rc = run_outlook_auth_ensure(args)

        self.assertEqual(rc, 0)
        output = buf_out.getvalue()
        self.assertIn("Saved Outlook token cache", output)

    def test_ensure_get_accounts_exception(self):
        """Test ensure when get_accounts raises exception."""
        msal = make_fake_msal_module(has_accounts=True, device_success=True)

        original_app = msal.PublicClientApplication

        class _AppWithException(original_app):
            def get_accounts(self):
                raise RuntimeError("Cache error")

        msal.PublicClientApplication = _AppWithException

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_ensure

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_ensure(args)

        # Should fall back to device flow
        self.assertEqual(rc, 0)


class TestRunOutlookAuthValidate(TempDirMixin, unittest.TestCase):
    """Tests for run_outlook_auth_validate function."""

    def _run_validate(  # nosec B107 - "{}" is empty-JSON token-cache *content*, not a credential
        self, msal, requests, token_path=None, token_text="{}"
    ):
        """Write a token cache (unless token_path is pre-set), patch msal/requests,
        and run run_outlook_auth_validate.

        ``token_text`` is the literal file body written to the fake token cache —
        the default ``"{}"`` is an empty JSON object that the code under test
        parses. Cases override it to exercise malformed-cache handling. bandit's
        B107 matches on the parameter *name* containing "token"; there is no
        secret here.

        Returns (rc, output). Shared by cases that only vary the fake
        msal/requests modules, the token path, and the expected (rc, message).
        """
        if token_path is None:
            token_path = str(Path(self.tmpdir) / "token.json")
            Path(token_path).write_text(token_text)

        args = make_args(client_id="test-client", tenant="consumers", token=token_path)  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        return rc, buf.getvalue()

    def test_validate_scenarios(self):
        """Table-driven happy/sad paths that only vary fake modules and expected (rc, message)."""
        cases = [
            {
                "name": "success",
                "msal": make_fake_msal_module(),
                "requests": make_fake_requests_module(),
                "rc": 0,
                "message": "Outlook token valid",
            },
            {
                "name": "token_not_found",
                "msal": make_fake_msal_module(),
                "requests": make_fake_requests_module(),
                "rc": 2,
                "message": "Token cache not found",
                "token_path": "/nonexistent/token.json",
            },
            {
                "name": "no_accounts",
                "msal": make_fake_msal_module(has_accounts=False),
                "requests": make_fake_requests_module(),
                "rc": 3,
                "message": "No account in token cache",
            },
            {
                "name": "silent_acquisition_failed",
                "msal": make_fake_msal_module(silent_success=False),
                "requests": make_fake_requests_module(),
                "rc": 4,
                "message": "Silent token acquisition failed",
            },
            {
                "name": "api_call_failed",
                "msal": make_fake_msal_module(),
                "requests": make_fake_requests_module(api_success=False),
                "rc": 5,
                "message": "Graph /me failed",
                "extra_message": "401",
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                rc, output = self._run_validate(
                    case["msal"], case["requests"], token_path=case.get("token_path")
                )

                self.assertEqual(rc, case["rc"])
                self.assertIn(case["message"], output)
                if "extra_message" in case:
                    self.assertIn(case["extra_message"], output)

    def test_validate_missing_dependencies(self):
        """Test validate with missing dependencies."""
        args = make_args(client_id="test-client", tenant="consumers", token="token.json")  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": None, "requests": None}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 1)
        output = buf.getvalue()
        self.assertIn("Outlook validation unavailable", output)

    def test_validate_missing_client_id(self):
        """Test validate with missing client_id."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module()

        args = make_args(client_id=None, tenant="consumers", token="token.json")  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            with patch("mail.outlook.auth_commands.resolve_outlook_credentials", return_value=(None, "consumers", "token.json")):
                from mail.outlook.auth_commands import run_outlook_auth_validate

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 2)
        output = buf.getvalue()
        self.assertIn("Missing --client-id", output)

    def test_validate_unable_to_read_cache(self):
        """Test validate when unable to read token cache."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module()

        original_cache = msal.SerializableTokenCache

        class _CacheWithError(original_cache):
            def deserialize(self, s):
                raise ValueError("Invalid JSON")

        msal.SerializableTokenCache = _CacheWithError

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("invalid")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 3)
        output = buf.getvalue()
        self.assertIn("Unable to read token cache", output)

    def test_validate_get_accounts_exception(self):
        """Test validate when get_accounts raises exception."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module()

        original_app = msal.PublicClientApplication

        class _AppWithException(original_app):
            def get_accounts(self):
                raise RuntimeError("Cache error")

        msal.PublicClientApplication = _AppWithException

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 3)
        output = buf.getvalue()
        self.assertIn("No account in token cache", output)


if __name__ == "__main__":
    unittest.main()
