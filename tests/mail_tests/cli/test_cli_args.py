"""Tests for mail/cli/args.py wrapper functions."""
from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from mail.cli.args import add_gmail_common_args, add_outlook_common_args
from core.cli_args import GmailAuthConfig, OutlookAuthConfig


class TestAddGmailCommonArgs(unittest.TestCase):
    """Tests for add_gmail_common_args function."""

    @patch('mail.cli.args._add_gmail_auth_args')
    def test_delegates_to_core_cli_args(self, mock_add_gmail):
        """add_gmail_common_args should delegate to core.cli_args."""
        parser = argparse.ArgumentParser()
        mock_add_gmail.return_value = parser

        result = add_gmail_common_args(parser)

        # Verify delegation with config object
        mock_add_gmail.assert_called_once()
        call_args = mock_add_gmail.call_args
        self.assertEqual(call_args[0][0], parser)
        config = call_args[0][1]
        self.assertIsInstance(config, GmailAuthConfig)
        self.assertEqual(result, parser)

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
    def test_delegates_to_core_cli_args(self, mock_add_outlook):
        """add_outlook_common_args should delegate to core.cli_args."""
        parser = argparse.ArgumentParser()
        mock_add_outlook.return_value = parser

        result = add_outlook_common_args(parser)

        # Verify delegation with config object
        mock_add_outlook.assert_called_once()
        call_args = mock_add_outlook.call_args
        self.assertEqual(call_args[0][0], parser)
        config = call_args[0][1]
        self.assertIsInstance(config, OutlookAuthConfig)
        self.assertEqual(result, parser)

    @patch('mail.cli.args._add_outlook_auth_args')
    def test_sets_tenant_default_to_consumers(self, mock_add_outlook):
        """add_outlook_common_args should default tenant to 'consumers'."""
        parser = argparse.ArgumentParser()

        add_outlook_common_args(parser)

        config = mock_add_outlook.call_args[0][1]
        self.assertEqual(config.tenant_default, "consumers")


if __name__ == '__main__':
    unittest.main()
