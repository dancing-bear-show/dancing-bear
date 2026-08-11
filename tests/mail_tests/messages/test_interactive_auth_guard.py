"""Tests for the interactive-auth guard installed by ``tests/__init__.py``.

The guard exists because a command that builds a provider before dispatching --
or a test that forgets to patch the provider factory -- reaches
``InstalledAppFlow.run_local_server``, which binds a real port and opens a
browser. These tests keep the guard from being removed or silently broken.
"""

from __future__ import annotations

import unittest
import webbrowser

import tests as tests_pkg


class InteractiveAuthGuardTests(unittest.TestCase):
    def test_run_local_server_is_blocked(self):
        """The OAuth listener must never bind a port under test."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            self.skipTest("google_auth_oauthlib not installed")

        with self.assertRaises(tests_pkg.InteractiveAuthAttempted):
            InstalledAppFlow.run_local_server(None, port=0)

    def test_run_console_is_blocked(self):
        """The console OAuth flow blocks on stdin; it must be guarded too."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            self.skipTest("google_auth_oauthlib not installed")

        with self.assertRaises(tests_pkg.InteractiveAuthAttempted):
            InstalledAppFlow.run_console(None)

    def test_webbrowser_open_is_blocked(self):
        """Opening a browser is never correct under test."""
        for fn in (webbrowser.open, webbrowser.open_new, webbrowser.open_new_tab):
            with self.subTest(fn=fn.__name__ if hasattr(fn, "__name__") else str(fn)):
                with self.assertRaises(tests_pkg.InteractiveAuthAttempted):
                    fn("https://example.com")

    def test_error_names_the_correct_patch_target(self):
        """The message must point at the definition site.

        The commands import these helpers function-locally, which resolves
        through the module object at call time -- so patching the definition
        site (``mail.utils.cli_helpers.*``) is what intercepts them.
        """
        with self.assertRaises(tests_pkg.InteractiveAuthAttempted) as ctx:
            webbrowser.open("https://example.com")
        self.assertIn("mail.utils.cli_helpers", str(ctx.exception))

    def test_patched_provider_is_unaffected_by_the_guard(self):
        """The guard must not interfere with correctly isolated tests."""
        from unittest.mock import patch

        sentinel = object()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=sentinel):
            from mail.utils import cli_helpers

            self.assertIs(cli_helpers.gmail_provider_from_args(None), sentinel)


if __name__ == "__main__":
    unittest.main()
