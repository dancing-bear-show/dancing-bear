"""Tests for mail/cli/args.py wrapper functions."""
from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from mail.cli.args import add_gmail_common_args, add_outlook_common_args


class TestAddGmailCommonArgs(unittest.TestCase):
    """Tests for add_gmail_common_args function."""

    @patch('mail.cli.args._add_gmail_auth_args')
    def test_delegates_to_core_cli_args(self, mock_add_gmail):
        """add_gmail_common_args should delegate to core.cli_args."""
        parser = argparse.ArgumentParser()
        mock_add_gmail.return_value = parser

        result = add_gmail_common_args(parser)

        # Verify delegation with correct parameters
        mock_add_gmail.assert_called_once_with(
            parser,
            include_cache=True,
            cache_help="Cache directory (optional)",
        )
        self.assertEqual(result, parser)

    @patch('mail.cli.args._add_gmail_auth_args')
    def test_includes_cache_argument(self, mock_add_gmail):
        """add_gmail_common_args should include cache argument."""
        parser = argparse.ArgumentParser()

        add_gmail_common_args(parser)

        call_kwargs = mock_add_gmail.call_args[1]
        self.assertTrue(call_kwargs['include_cache'])
        self.assertEqual(call_kwargs['cache_help'], "Cache directory (optional)")


class TestAddOutlookCommonArgs(unittest.TestCase):
    """Tests for add_outlook_common_args function."""

    @patch('mail.cli.args._add_outlook_auth_args')
    def test_delegates_to_core_cli_args(self, mock_add_outlook):
        """add_outlook_common_args should delegate to core.cli_args."""
        parser = argparse.ArgumentParser()
        mock_add_outlook.return_value = parser

        result = add_outlook_common_args(parser)

        # Verify delegation with correct parameters
        mock_add_outlook.assert_called_once_with(
            parser,
            tenant_default="consumers",
        )
        self.assertEqual(result, parser)

    @patch('mail.cli.args._add_outlook_auth_args')
    def test_sets_tenant_default_to_consumers(self, mock_add_outlook):
        """add_outlook_common_args should default tenant to 'consumers'."""
        parser = argparse.ArgumentParser()

        add_outlook_common_args(parser)

        call_kwargs = mock_add_outlook.call_args[1]
        self.assertEqual(call_kwargs['tenant_default'], "consumers")


if __name__ == '__main__':
    unittest.main()
