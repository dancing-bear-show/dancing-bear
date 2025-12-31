"""Comprehensive tests for mail/outlook/auth_commands.py Outlook auth functions."""
import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestRunOutlookAuthDeviceCode(unittest.TestCase):
    """Tests for run_outlook_auth_device_code function."""

    def _make_fake_msal(self, flow_success=True, user_code="ABC123"):
        """Create fake msal module for testing."""
        msal = types.ModuleType("msal")

        class _App:
            def __init__(self, client_id, authority=None):
                self.client_id = client_id
                self.authority = authority

            def initiate_device_flow(self, scopes):
                if not flow_success:
                    return {}
                return {
                    "user_code": user_code,
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "Visit https://microsoft.com/devicelogin and enter ABC123",
                    "expires_in": 900,
                }

        msal.PublicClientApplication = _App
        return msal

    def test_device_code_success(self):
        """Test successful device code flow initiation."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                out=str(out_path),
                profile=None,
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_device_code

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())

            # Verify flow file contents
            flow_data = json.loads(out_path.read_text())
            self.assertEqual(flow_data["user_code"], "ABC123")
            self.assertEqual(flow_data["_client_id"], "test-client")
            self.assertEqual(flow_data["_tenant"], "consumers")

            output = buf.getvalue()
            self.assertIn("ABC123", output)
            self.assertIn("Saved device flow to", output)

    def test_device_code_with_verbose(self):
        """Test device code with verbose flag."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                out=str(out_path),
                profile=None,
                verbose=True,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_device_code

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 0)
            output = buf.getvalue()
            self.assertIn("[device-code]", output)
            self.assertIn("client_id=test-client", output)

    def test_device_code_with_profile(self):
        """Test device code with profile flag in output."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                out=str(out_path),
                profile="work",
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_device_code

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 0)
            output = buf.getvalue()
            self.assertIn("--profile work", output)

    def test_device_code_missing_client_id(self):
        """Test device code with missing client_id."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id=None,
                tenant="consumers",
                out=str(out_path),
                profile=None,
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                with patch("mail.outlook.auth_commands.resolve_outlook_credentials", return_value=(None, "consumers", None)):
                    from mail.outlook.auth_commands import run_outlook_auth_device_code

                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 2)
            output = buf.getvalue()
            self.assertIn("Missing --client-id", output)

    def test_device_code_missing_msal(self):
        """Test device code with missing msal dependency."""
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                out=str(out_path),
                profile=None,
                verbose=False,
            )

            # Simulate missing msal by raising ImportError
            with patch.dict("sys.modules", {"msal": None}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_device_code

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 1)
            output = buf.getvalue()
            self.assertIn("Missing msal dependency", output)

    def test_device_code_flow_failed(self):
        """Test device code when flow initiation fails."""
        msal = self._make_fake_msal(flow_success=False)

        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "flow.json"
            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                out=str(out_path),
                profile=None,
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_device_code

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_device_code(args)

            self.assertEqual(rc, 1)
            output = buf.getvalue()
            self.assertIn("Failed to start device flow", output)


class TestRunOutlookAuthPoll(unittest.TestCase):
    """Tests for run_outlook_auth_poll function."""

    def _make_fake_msal(self, acquire_success=True):
        """Create fake msal module for testing."""
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

            def acquire_token_by_device_flow(self, flow):
                if not acquire_success:
                    return {"error": "authorization_pending"}
                return {"access_token": "fake-token", "expires_in": 3600}

        msal.SerializableTokenCache = _Cache
        msal.PublicClientApplication = _App
        return msal

    def test_poll_success(self):
        """Test successful device code poll."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            flow_path = Path(td) / "flow.json"
            token_path = Path(td) / "token.json"

            # Create flow file
            flow_data = {
                "user_code": "ABC123",
                "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900,
                "_client_id": "test-client",
                "_tenant": "consumers",
            }
            flow_path.write_text(json.dumps(flow_data))

            args = SimpleNamespace(
                flow=str(flow_path),
                token=str(token_path),
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_poll

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_poll(args)

            self.assertEqual(rc, 0)
            self.assertTrue(token_path.exists())
            output = buf.getvalue()
            self.assertIn("Saved Outlook token cache", output)

    def test_poll_with_verbose(self):
        """Test poll with verbose flag."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            flow_path = Path(td) / "flow.json"
            token_path = Path(td) / "token.json"

            flow_data = {
                "user_code": "ABC123",
                "expires_in": 900,
                "_client_id": "test-client",
                "_tenant": "consumers",
            }
            flow_path.write_text(json.dumps(flow_data))

            args = SimpleNamespace(
                flow=str(flow_path),
                token=str(token_path),
                verbose=True,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_poll

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_poll(args)

            self.assertEqual(rc, 0)
            output = buf.getvalue()
            self.assertIn("[device-code] Polling", output)

    def test_poll_missing_msal(self):
        """Test poll with missing msal dependency."""
        args = SimpleNamespace(flow="flow.json", token="token.json", verbose=False)

        with patch.dict("sys.modules", {"msal": None}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_poll

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_poll(args)

        self.assertEqual(rc, 1)
        output = buf.getvalue()
        self.assertIn("Missing msal dependency", output)

    def test_poll_flow_not_found(self):
        """Test poll when flow file doesn't exist."""
        msal = self._make_fake_msal()

        args = SimpleNamespace(
            flow="/nonexistent/flow.json",
            token="token.json",
            verbose=False,
        )

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_poll

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_poll(args)

        self.assertEqual(rc, 2)
        output = buf.getvalue()
        self.assertIn("Device flow file not found", output)

    def test_poll_missing_client_id(self):
        """Test poll when flow file missing _client_id."""
        msal = self._make_fake_msal()

        with tempfile.TemporaryDirectory() as td:
            flow_path = Path(td) / "flow.json"

            # Flow without _client_id
            flow_data = {
                "user_code": "ABC123",
                "verification_uri": "https://microsoft.com/devicelogin",
            }
            flow_path.write_text(json.dumps(flow_data))

            args = SimpleNamespace(
                flow=str(flow_path),
                token="token.json",
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_poll

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_poll(args)

        self.assertEqual(rc, 2)
        output = buf.getvalue()
        self.assertIn("Device flow missing _client_id", output)

    def test_poll_acquire_failed(self):
        """Test poll when token acquisition fails."""
        msal = self._make_fake_msal(acquire_success=False)

        with tempfile.TemporaryDirectory() as td:
            flow_path = Path(td) / "flow.json"
            token_path = Path(td) / "token.json"

            flow_data = {
                "user_code": "ABC123",
                "_client_id": "test-client",
                "_tenant": "consumers",
            }
            flow_path.write_text(json.dumps(flow_data))

            args = SimpleNamespace(
                flow=str(flow_path),
                token=str(token_path),
                verbose=False,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_poll

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_poll(args)

        self.assertEqual(rc, 3)
        output = buf.getvalue()
        self.assertIn("Device flow failed", output)


class TestRunOutlookAuthEnsure(unittest.TestCase):
    """Tests for run_outlook_auth_ensure function."""

    def _make_fake_msal(self, has_accounts=True, silent_success=True, device_success=True):
        """Create fake msal module for testing."""
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

            def get_accounts(self):
                if not has_accounts:
                    return []
                return [{"username": "user@example.com"}]

            def acquire_token_silent(self, scopes, account=None):
                if not silent_success:
                    return None
                return {"access_token": "fake-token", "expires_in": 3600}

            def initiate_device_flow(self, scopes):
                if not device_success:
                    return {}
                return {
                    "user_code": "ABC123",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "Visit and enter ABC123",
                }

            def acquire_token_by_device_flow(self, flow):
                if not device_success:
                    return {"error": "timeout"}
                return {"access_token": "fake-token", "expires_in": 3600}

        msal.SerializableTokenCache = _Cache
        msal.PublicClientApplication = _App
        return msal

    def test_ensure_with_valid_cache(self):
        """Test ensure when token cache is valid."""
        msal = self._make_fake_msal(has_accounts=True, silent_success=True)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal = self._make_fake_msal(has_accounts=False, device_success=True)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        args = SimpleNamespace(
            client_id="test-client",
            tenant="consumers",
            token="token.json",
            profile=None,
        )

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
        msal = self._make_fake_msal()

        args = SimpleNamespace(
            client_id=None,
            tenant="consumers",
            token="token.json",
            profile=None,
        )

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
        msal = self._make_fake_msal(has_accounts=False, device_success=False)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal = self._make_fake_msal(has_accounts=False, device_success=True)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("invalid json{{{")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_ensure

                buf_out = io.StringIO()
                buf_err = io.StringIO()
                with redirect_stdout(buf_out):
                    import sys
                    from contextlib import redirect_stderr
                    with redirect_stderr(buf_err):
                        rc = run_outlook_auth_ensure(args)

            self.assertEqual(rc, 0)
            # Should proceed with device flow after warning
            output = buf_out.getvalue()
            self.assertIn("Saved Outlook token cache", output)

    def test_ensure_get_accounts_exception(self):
        """Test ensure when get_accounts raises exception."""
        msal = self._make_fake_msal(has_accounts=True, device_success=True)

        # Override get_accounts to raise
        original_app = msal.PublicClientApplication

        class _AppWithException(original_app):
            def get_accounts(self):
                raise RuntimeError("Cache error")

        msal.PublicClientApplication = _AppWithException

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

            with patch.dict("sys.modules", {"msal": msal}, clear=False):
                from mail.outlook.auth_commands import run_outlook_auth_ensure

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_outlook_auth_ensure(args)

            # Should fall back to device flow
            self.assertEqual(rc, 0)


class TestRunOutlookAuthValidate(unittest.TestCase):
    """Tests for run_outlook_auth_validate function."""

    def _make_fake_msal_and_requests(self, has_accounts=True, silent_success=True, api_success=True):
        """Create fake msal and requests modules."""
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

            def get_accounts(self):
                if not has_accounts:
                    return []
                return [{"username": "user@example.com"}]

            def acquire_token_silent(self, scopes, account=None):
                if not silent_success:
                    return None
                return {"access_token": "fake-token"}

        msal.SerializableTokenCache = _Cache
        msal.PublicClientApplication = _App

        requests = types.ModuleType("requests")

        class _Resp:
            def __init__(self):
                self.status_code = 200 if api_success else 401
                self.text = "OK" if api_success else "Unauthorized"

        def _get(url, headers=None, **kwargs):
            return _Resp()

        requests.get = _get

        return msal, requests

    def test_validate_success(self):
        """Test successful validation."""
        msal, requests = self._make_fake_msal_and_requests()

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        args = SimpleNamespace(
            client_id="test-client",
            tenant="consumers",
            token="token.json",
            profile=None,
        )

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
        msal, requests = self._make_fake_msal_and_requests()

        args = SimpleNamespace(
            client_id=None,
            tenant="consumers",
            token="token.json",
            profile=None,
        )

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
        msal, requests = self._make_fake_msal_and_requests()

        args = SimpleNamespace(
            client_id="test-client",
            tenant="consumers",
            token="/nonexistent/token.json",
            profile=None,
        )

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
        msal, requests = self._make_fake_msal_and_requests()

        # Override deserialize to raise
        original_cache = msal.SerializableTokenCache

        class _CacheWithError(original_cache):
            def deserialize(self, s):
                raise ValueError("Invalid JSON")

        msal.SerializableTokenCache = _CacheWithError

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("invalid")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal, requests = self._make_fake_msal_and_requests(has_accounts=False)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal, requests = self._make_fake_msal_and_requests()

        # Override get_accounts to raise
        original_app = msal.PublicClientApplication

        class _AppWithException(original_app):
            def get_accounts(self):
                raise RuntimeError("Cache error")

        msal.PublicClientApplication = _AppWithException

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal, requests = self._make_fake_msal_and_requests(silent_success=False)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
        msal, requests = self._make_fake_msal_and_requests(api_success=False)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "token.json"
            token_path.write_text("{}")

            args = SimpleNamespace(
                client_id="test-client",
                tenant="consumers",
                token=str(token_path),
                profile=None,
            )

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
