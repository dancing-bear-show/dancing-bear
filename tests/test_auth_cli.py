import io
import os
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


class AuthCLITests(unittest.TestCase):
    def test_gmail_auth_validate_success(self):
        # Create a dummy token path to satisfy existence check
        td = tempfile.mkdtemp()
        tok_path = os.path.join(td, "token.json")
        with open(tok_path, "w", encoding="utf-8") as fh:
            fh.write("{}")

        # Build fake google.* modules to satisfy imports inside _cmd_auth
        google = types.ModuleType("google")

        # google.auth.transport.requests.Request
        google_auth = types.ModuleType("google.auth")
        google_auth_transport = types.ModuleType("google.auth.transport")
        google_auth_transport_requests = types.ModuleType("google.auth.transport.requests")

        class FakeRequest:
            def __init__(self, *args, **kwargs):
                pass

        google_auth_transport_requests.Request = FakeRequest

        # google.oauth2.credentials.Credentials
        google_oauth2 = types.ModuleType("google.oauth2")
        google_oauth2_credentials = types.ModuleType("google.oauth2.credentials")

        class FakeCreds:
            def __init__(self):
                self.expired = False
                self.refresh_token = None

            @classmethod
            def from_authorized_user_file(cls, path, scopes=None):
                return cls()

            def refresh(self, _request):
                # not called when expired is False
                pass

        google_oauth2_credentials.Credentials = FakeCreds

        # googleapiclient.discovery.build
        googleapiclient = types.ModuleType("googleapiclient")
        googleapiclient_discovery = types.ModuleType("googleapiclient.discovery")

        class _Users:
            def getProfile(self, userId="me"):
                class _Exec:
                    def execute(self):
                        return {"emailAddress": "me@example.com"}

                return _Exec()

        class _Svc:
            def users(self):
                return _Users()

        def build(_name, _version, credentials=None):
            return _Svc()

        googleapiclient_discovery.build = build

        fake_modules = {
            "google": google,
            "google.auth": google_auth,
            "google.auth.transport": google_auth_transport,
            "google.auth.transport.requests": google_auth_transport_requests,
            "google.oauth2": google_oauth2,
            "google.oauth2.credentials": google_oauth2_credentials,
            "googleapiclient": googleapiclient,
            "googleapiclient.discovery": googleapiclient_discovery,
        }

        with patch.dict("sys.modules", fake_modules, clear=False):
            import mail_assistant.__main__ as m

            args = SimpleNamespace(validate=True, token=tok_path, credentials=None, profile=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_auth(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("Gmail token valid.", out)

    def test_outlook_auth_validate_success(self):
        # Prepare a dummy token cache file and fake msal/requests
        td = tempfile.mkdtemp()
        tok_path = os.path.join(td, "outlook_token.json")
        with open(tok_path, "w", encoding="utf-8") as fh:
            fh.write("{}")

        # Fake msal module
        msal = types.ModuleType("msal")

        class _Cache:
            def __init__(self):
                self._s = "{}"

            def serialize(self):
                return self._s

            def deserialize(self, _s):
                self._s = _s or "{}"

        class _App:
            def __init__(self, client_id, authority=None, token_cache=None):
                self.client_id = client_id
                self.authority = authority
                self.token_cache = token_cache

            def get_accounts(self):
                return [object()]

            def acquire_token_silent(self, scopes, account=None):
                return {"access_token": "x", "expires_in": 3600}

        msal.SerializableTokenCache = _Cache
        msal.PublicClientApplication = _App

        # Fake requests module
        requests = types.ModuleType("requests")

        class _Resp:
            status_code = 200
            text = "OK"

        def _get(url, headers=None):
            return _Resp()

        requests.get = _get

        with patch.dict("sys.modules", {"msal": msal, "requests": requests}, clear=False):
            import mail_assistant.__main__ as m

            args = SimpleNamespace(client_id="fake", tenant="consumers", token=tok_path, profile=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_outlook_auth_validate(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("Outlook token valid.", out)


if __name__ == "__main__":
    unittest.main()

