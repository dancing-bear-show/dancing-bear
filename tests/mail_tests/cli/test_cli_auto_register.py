"""Tests for mail/cli/auto.py CLI registration."""
from __future__ import annotations

import argparse
import unittest

from mail.cli.auto import register
from tests.mail_tests.fixtures import CLIRegisterTestCase, make_noop_handlers


_AUTO_HANDLERS = ("f_propose", "f_apply", "f_summary")


def make_auto_parser():
    """Create an argparse parser with auto subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers, **make_noop_handlers(*_AUTO_HANDLERS))
    return parser


class AutoTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for auto CLI tests."""

    def setUp(self):
        self.parser = make_auto_parser()


class TestAutoRegister(AutoTestCase):
    """Tests for the auto CLI registration."""

    def test_auto_group_registered(self):
        """Test that auto group is registered."""
        args = self.parse("auto")
        self.assertEqual(args.command, "auto")

    def test_propose_subcommand_registered(self):
        """Test that propose subcommand is registered."""
        args = self.parse("auto", "propose", "--out", "proposal.json")
        self.assertEqual(args.auto_cmd, "propose")

    def test_apply_subcommand_registered(self):
        """Test that apply subcommand is registered."""
        args = self.parse("auto", "apply", "--plan", "plan.json")
        self.assertEqual(args.auto_cmd, "apply")
        self.assertEqual(args.plan, "plan.json")

    def test_summary_subcommand_registered(self):
        """Test that summary subcommand is registered."""
        args = self.parse("auto", "summary", "--log", "log.jsonl")
        self.assertEqual(args.auto_cmd, "summary")

    def test_propose_has_common_args(self):
        """Test that propose has common auto args like --days."""
        args = self.parse("auto", "propose", "--out", "proposal.json", "--days", "14")
        self.assertEqual(args.days, 14)

    def test_propose_has_only_inbox_flag(self):
        """Test that propose has --only-inbox flag."""
        args = self.parse("auto", "propose", "--out", "proposal.json", "--only-inbox")
        self.assertTrue(args.only_inbox)


if __name__ == '__main__':
    unittest.main()
