"""Tests for mail/cli/messages.py CLI registration."""
from __future__ import annotations

import argparse
import unittest

from mail.cli.messages import register
from tests.mail_tests.fixtures import CLIRegisterTestCase, make_noop_handlers


_MESSAGES_HANDLERS = ("f_search", "f_summarize", "f_reply", "f_apply_scheduled")


def make_messages_parser():
    """Create an argparse parser with messages subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    def add_gmail_args(p):
        """Dummy add_gmail_args function."""
        pass

    register(subparsers, add_gmail_args, **make_noop_handlers(*_MESSAGES_HANDLERS))
    return parser


class MessagesTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for messages CLI tests."""

    def setUp(self):
        self.parser = make_messages_parser()


class TestMessagesRegister(MessagesTestCase):
    """Tests for the messages CLI registration."""

    def test_messages_group_registered(self):
        """Test that messages group is registered."""
        args = self.parse("messages")
        self.assertEqual(args.command, "messages")

    def test_search_subcommand_registered(self):
        """Test that search subcommand is registered."""
        args = self.parse("messages", "search")
        self.assertEqual(args.messages_cmd, "search")

    def test_search_has_query_arg(self):
        """Test that search has --query argument."""
        args = self.parse("messages", "search", "--query", "from:user@example.com")
        self.assertEqual(args.query, "from:user@example.com")

    def test_search_has_days_arg(self):
        """Test that search has --days argument."""
        args = self.parse("messages", "search", "--days", "7")
        self.assertEqual(args.days, 7)

    def test_search_has_only_inbox_flag(self):
        """Test that search has --only-inbox flag."""
        args = self.parse("messages", "search", "--only-inbox")
        self.assertTrue(args.only_inbox)

    def test_search_has_max_results_arg(self):
        """Test that search has --max-results with default."""
        args = self.parse("messages", "search")
        self.assertEqual(args.max_results, 5)  # Default value

    def test_search_has_json_flag(self):
        """Test that search has --json flag."""
        args = self.parse("messages", "search", "--json")
        self.assertTrue(args.json)

    def test_summarize_subcommand_registered(self):
        """Test that summarize subcommand is registered."""
        args = self.parse("messages", "summarize")
        self.assertEqual(args.messages_cmd, "summarize")

    def test_reply_subcommand_registered(self):
        """Test that reply subcommand is registered."""
        args = self.parse("messages", "reply")
        self.assertEqual(args.messages_cmd, "reply")

    def test_apply_scheduled_subcommand_registered(self):
        """Test that apply-scheduled subcommand is registered."""
        args = self.parse("messages", "apply-scheduled")
        self.assertEqual(args.messages_cmd, "apply-scheduled")


if __name__ == '__main__':
    unittest.main()
