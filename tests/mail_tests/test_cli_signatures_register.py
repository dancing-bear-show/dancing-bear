"""Tests for mail/cli/signatures.py CLI registration."""
from __future__ import annotations

import argparse
import unittest

from mail.cli.signatures import register
from tests.mail_tests.fixtures import CLIRegisterTestCase, make_noop_handlers


_SIGNATURES_HANDLERS = ("f_export", "f_sync", "f_normalize")


def make_signatures_parser():
    """Create an argparse parser with signatures subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers, **make_noop_handlers(*_SIGNATURES_HANDLERS))
    return parser


class SignaturesTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for signatures CLI tests."""

    def setUp(self):
        self.parser = make_signatures_parser()


class TestSignaturesRegister(SignaturesTestCase):
    """Tests for the signatures CLI registration."""

    def test_signatures_group_registered(self):
        """Test that signatures group is registered."""
        args = self.parse("signatures")
        self.assertEqual(args.command, "signatures")

    def test_export_subcommand_registered(self):
        """Test that export subcommand is registered."""
        args = self.parse("signatures", "export", "--out", "sigs.yaml")
        self.assertEqual(args.signatures_cmd, "export")
        self.assertEqual(args.out, "sigs.yaml")

    def test_export_requires_out_arg(self):
        """Test that export requires --out argument."""
        with self.assertRaises(SystemExit):
            self.parse("signatures", "export")

    def test_export_has_assets_dir_arg(self):
        """Test that export has --assets-dir with default."""
        args = self.parse("signatures", "export", "--out", "sigs.yaml")
        self.assertEqual(args.assets_dir, "signatures_assets")  # Default

    def test_sync_subcommand_registered(self):
        """Test that sync subcommand is registered."""
        args = self.parse("signatures", "sync", "--config", "sigs.yaml")
        self.assertEqual(args.signatures_cmd, "sync")
        self.assertEqual(args.config, "sigs.yaml")

    def test_sync_requires_config_arg(self):
        """Test that sync requires --config argument."""
        with self.assertRaises(SystemExit):
            self.parse("signatures", "sync")

    def test_sync_has_send_as_arg(self):
        """Test that sync has --send-as argument."""
        args = self.parse("signatures", "sync", "--config", "sigs.yaml", "--send-as", "user@example.com")
        self.assertEqual(args.send_as, "user@example.com")

    def test_sync_has_dry_run_flag(self):
        """Test that sync has --dry-run flag."""
        args = self.parse("signatures", "sync", "--config", "sigs.yaml", "--dry-run")
        self.assertTrue(args.dry_run)

    def test_normalize_subcommand_registered(self):
        """Test that normalize subcommand is registered."""
        args = self.parse("signatures", "normalize")
        self.assertEqual(args.signatures_cmd, "normalize")


if __name__ == '__main__':
    unittest.main()
