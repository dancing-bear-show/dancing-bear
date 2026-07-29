"""Tests for run_outlook_auth_device_code and run_outlook_auth_poll functions."""

import io
import json
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


class TestRunOutlookAuthDeviceCode(TempDirMixin, unittest.TestCase):
    """Tests for run_outlook_auth_device_code function."""

    def test_device_code_success(self):
        """Test successful device code flow initiation."""
        msal = make_fake_msal_module()
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id="test-client", tenant="consumers", out=str(out_path), verbose=False)

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_device_code

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_device_code(args)

        self.assertEqual(rc, 0)
        self.assertTrue(out_path.exists())

        flow_data = json.loads(out_path.read_text())
        self.assertEqual(flow_data["user_code"], "ABC123")
        self.assertEqual(flow_data["_client_id"], "test-client")
        self.assertEqual(flow_data["_tenant"], "consumers")

        output = buf.getvalue()
        self.assertIn("ABC123", output)
        self.assertIn("Saved device flow to", output)

    def test_device_code_with_verbose(self):
        """Test device code with verbose flag."""
        msal = make_fake_msal_module()
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id="test-client", tenant="consumers", out=str(out_path), verbose=True)

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
        msal = make_fake_msal_module()
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id="test-client", tenant="consumers", out=str(out_path), profile="work", verbose=False)

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
        msal = make_fake_msal_module()
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id=None, tenant="consumers", out=str(out_path), verbose=False)

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
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id="test-client", tenant="consumers", out=str(out_path), verbose=False)

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
        msal = make_fake_msal_module(flow_success=False)
        out_path = Path(self.tmpdir) / "flow.json"
        args = make_args(client_id="test-client", tenant="consumers", out=str(out_path), verbose=False)

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_device_code

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_device_code(args)

        self.assertEqual(rc, 1)
        output = buf.getvalue()
        self.assertIn("Failed to start device flow", output)


class TestRunOutlookAuthPoll(TempDirMixin, unittest.TestCase):
    """Tests for run_outlook_auth_poll function."""

    def test_poll_success(self):
        """Test successful device code poll."""
        msal = make_fake_msal_module()
        flow_path = Path(self.tmpdir) / "flow.json"
        token_path = Path(self.tmpdir) / "token.json"

        flow_data = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "_client_id": "test-client",
            "_tenant": "consumers",
        }
        flow_path.write_text(json.dumps(flow_data))

        args = make_args(flow=str(flow_path), token=str(token_path), verbose=False)

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
        msal = make_fake_msal_module()
        flow_path = Path(self.tmpdir) / "flow.json"
        token_path = Path(self.tmpdir) / "token.json"

        flow_data = {
            "user_code": "ABC123",
            "expires_in": 900,
            "_client_id": "test-client",
            "_tenant": "consumers",
        }
        flow_path.write_text(json.dumps(flow_data))

        args = make_args(flow=str(flow_path), token=str(token_path), verbose=True)

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
        args = make_args(flow="flow.json", token="token.json", verbose=False)  # nosec B106 - test fixture path

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
        msal = make_fake_msal_module()
        args = make_args(flow="/nonexistent/flow.json", token="token.json", verbose=False)  # nosec B106 - test fixture path

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
        msal = make_fake_msal_module()
        flow_path = Path(self.tmpdir) / "flow.json"

        flow_data = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin",
        }
        flow_path.write_text(json.dumps(flow_data))

        args = make_args(flow=str(flow_path), token="token.json", verbose=False)  # nosec B106 - test fixture path

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
        msal = make_fake_msal_module(acquire_success=False)
        flow_path = Path(self.tmpdir) / "flow.json"
        token_path = Path(self.tmpdir) / "token.json"

        flow_data = {
            "user_code": "ABC123",
            "_client_id": "test-client",
            "_tenant": "consumers",
        }
        flow_path.write_text(json.dumps(flow_data))

        args = make_args(flow=str(flow_path), token=str(token_path), verbose=False)

        with patch.dict("sys.modules", {"msal": msal}, clear=False):
            from mail.outlook.auth_commands import run_outlook_auth_poll

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_auth_poll(args)

        self.assertEqual(rc, 3)
        output = buf.getvalue()
        self.assertIn("Device flow failed", output)


if __name__ == "__main__":
    unittest.main()
