"""Tests for run_outlook_auth_ensure and run_outlook_auth_validate functions."""

import io
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import TempDirMixin
from tests.mail_tests.fixtures import make_args


def make_fake_msal_module(flow_success=True, has_accounts=True, silent_success=True,
                          device_success=True, acquire_success=True, user_code="ABC123"):
    """Factory for creating fake msal modules with configurable behavior."""
    msal = types.ModuleType("msal")

    class _Cache:
        def __init__(self):
            self._s = "{}"

        def serialize(self):
            return self._s

        def deserialize(self, s):
            self._s = s or "{}"

    class _App:
        def __init__(self, client_id, authority=None, token_cache=None):
            self.client_id = client_id
            self.authority = authority
            self.token_cache = token_cache

        def initiate_device_flow(self, scopes):
            if not flow_success or not device_success:
                return {}
            return {
                "user_code": user_code,
                "verification_uri": "https://microsoft.com/devicelogin",
                "message": f"Visit https://microsoft.com/devicelogin and enter {user_code}",
                "expires_in": 900,
            }

        def acquire_token_by_device_flow(self, flow):
            if not acquire_success or not device_success:
                return {"error": "authorization_pending"}
            return {"access_token": "fake-token", "expires_in": 3600}

        def get_accounts(self):
            if not has_accounts:
                return []
            return [{"username": "user@example.com"}]

        def acquire_token_silent(self, scopes, account=None):
            if not silent_success:
                return None
            return {"access_token": "fake-token", "expires_in": 3600}

    msal.SerializableTokenCache = _Cache
    msal.PublicClientApplication = _App
    return msal


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

    def test_validate_success(self):
        """Test successful validation."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module()

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Outlook token valid", output)

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

    def test_validate_token_not_found(self):
        """Test validate when token file doesn't exist."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module()

        args = make_args(client_id="test-client", tenant="consumers", token="/nonexistent/token.json")  # nosec B106 - test fixture path

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 2)
        output = buf.getvalue()
        self.assertIn("Token cache not found", output)

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

    def test_validate_no_accounts(self):
        """Test validate when no accounts in cache."""
        msal = make_fake_msal_module(has_accounts=False)
        requests = make_fake_requests_module()

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

    def test_validate_silent_acquisition_failed(self):
        """Test validate when silent token acquisition fails."""
        msal = make_fake_msal_module(silent_success=False)
        requests = make_fake_requests_module()

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 4)
        output = buf.getvalue()
        self.assertIn("Silent token acquisition failed", output)

    def test_validate_api_call_failed(self):
        """Test validate when Graph API /me call fails."""
        msal = make_fake_msal_module()
        requests = make_fake_requests_module(api_success=False)

        token_path = Path(self.tmpdir) / "token.json"
        token_path.write_text("{}")

        args = make_args(client_id="test-client", tenant="consumers", token=str(token_path))

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_validate

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_validate(args)

        self.assertEqual(rc, 5)
        output = buf.getvalue()
        self.assertIn("Graph /me failed", output)
        self.assertIn("401", output)


if __name__ == "__main__":
    unittest.main()
