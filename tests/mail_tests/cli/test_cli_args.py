"""Tests for mail/cli/args.py wrapper functions."""
from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from mail.cli.args import add_gmail_common_args, add_outlook_common_args
from core.cli_args import GmailAuthConfig, OutlookAuthConfig


class TestAddCommonArgsDelegation(unittest.TestCase):
    """Tests that add_gmail_common_args / add_outlook_common_args delegate to core.cli_args.

    Both wrappers have the same shape: build a parser, patch the underlying
    `_add_*_auth_args` helper, call the wrapper, and assert it forwarded the
    parser plus a config object of the matching type. Table-driven over
    (provider, wrapper fn, patch target, config type) to avoid duplicating
    that scaffolding per provider.
    """

    def test_delegates_to_core_cli_args(self):
        cases = [
            ("gmail", add_gmail_common_args, "mail.cli.args._add_gmail_auth_args", GmailAuthConfig),
            ("outlook", add_outlook_common_args, "mail.cli.args._add_outlook_auth_args", OutlookAuthConfig),
        ]
        for provider, wrapper_fn, patch_target, config_cls in cases:
            with self.subTest(provider=provider):
                with patch(patch_target) as mock_add_auth_args:
                    parser = argparse.ArgumentParser()
                    mock_add_auth_args.return_value = parser

                    result = wrapper_fn(parser)

                    # Verify delegation with config object
                    mock_add_auth_args.assert_called_once()
                    call_args = mock_add_auth_args.call_args
                    self.assertEqual(call_args[0][0], parser)
                    config = call_args[0][1]
                    self.assertIsInstance(config, config_cls)
                    self.assertEqual(result, parser)


class TestAddGmailCommonArgs(unittest.TestCase):
    """Tests for add_gmail_common_args function."""

    @patch('mail.cli.args._add_gmail_auth_args')
    def test_includes_cache_argument(self, mock_add_gmail):
        """add_gmail_common_args should include cache argument."""
        parser = argparse.ArgumentParser()

        add_gmail_common_args(parser)

        config = mock_add_gmail.call_args[0][1]
        self.assertTrue(config.include_cache)
        self.assertEqual(config.cache_help, "Cache directory (optional)")


class TestAddOutlookCommonArgs(unittest.TestCase):
    """Tests for add_outlook_common_args function."""

    @patch('mail.cli.args._add_outlook_auth_args')
    def test_sets_tenant_default_to_consumers(self, mock_add_outlook):
        """add_outlook_common_args should default tenant to 'consumers'."""
        parser = argparse.ArgumentParser()

        add_outlook_common_args(parser)

        config = mock_add_outlook.call_args[0][1]
        self.assertEqual(config.tenant_default, "consumers")


if __name__ == '__main__':
    unittest.main()
