"""Tests for mail/cli/forwarding.py CLI registration."""
from __future__ import annotations

import argparse
import unittest

from mail.cli.forwarding import register
from tests.mail_tests.fixtures import CLIRegisterTestCase, make_noop_handlers


_FORWARDING_HANDLERS = ("f_list", "f_add", "f_status", "f_enable", "f_disable")


def make_forwarding_parser():
    """Create an argparse parser with forwarding subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers, **make_noop_handlers(*_FORWARDING_HANDLERS))
    return parser


class ForwardingTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for forwarding CLI tests."""

    def setUp(self):
        self.parser = make_forwarding_parser()


class TestForwardingRegister(ForwardingTestCase):
    """Tests for the forwarding CLI registration."""

    def test_forwarding_group_registered(self):
        """Test that forwarding group is registered."""
        args = self.parse("forwarding")
        self.assertEqual(args.command, "forwarding")

    def test_list_subcommand_registered(self):
        """Test that list subcommand is registered."""
        args = self.parse("forwarding", "list")
        self.assertEqual(args.forwarding_cmd, "list")

    def test_add_subcommand_registered(self):
        """Test that add subcommand is registered."""
        args = self.parse("forwarding", "add", "--email", "user@example.com")
        self.assertEqual(args.forwarding_cmd, "add")
        self.assertEqual(args.email, "user@example.com")

    def test_add_requires_email(self):
        """Test that add requires --email argument."""
        with self.assertRaises(SystemExit):
            self.parse("forwarding", "add")

    def test_status_subcommand_registered(self):
        """Test that status subcommand is registered."""
        args = self.parse("forwarding", "status")
        self.assertEqual(args.forwarding_cmd, "status")

    def test_enable_subcommand_registered(self):
        """Test that enable subcommand is registered."""
        args = self.parse("forwarding", "enable", "--email", "fwd@example.com")
        self.assertEqual(args.forwarding_cmd, "enable")
        self.assertEqual(args.email, "fwd@example.com")

    def test_enable_requires_email(self):
        """Test that enable requires --email argument."""
        with self.assertRaises(SystemExit):
            self.parse("forwarding", "enable")

    def test_enable_has_disposition_choices(self):
        """Test that enable has --disposition with valid choices."""
        args = self.parse("forwarding", "enable", "--email", "fwd@example.com", "--disposition", "archive")
        self.assertEqual(args.disposition, "archive")

    def test_enable_disposition_defaults_to_leaveInInbox(self):
        """Test that enable --disposition defaults to leaveInInbox."""
        args = self.parse("forwarding", "enable", "--email", "fwd@example.com")
        self.assertEqual(args.disposition, "leaveInInbox")

    def test_enable_disposition_validates_choices(self):
        """Test that enable --disposition validates against allowed choices."""
        with self.assertRaises(SystemExit):
            self.parse("forwarding", "enable", "--email", "fwd@example.com", "--disposition", "invalid")

    def test_disable_subcommand_registered(self):
        """Test that disable subcommand is registered."""
        args = self.parse("forwarding", "disable")
        self.assertEqual(args.forwarding_cmd, "disable")


if __name__ == '__main__':
    unittest.main()
