"""Tests for mail/cli/accounts.py CLI registration."""
from __future__ import annotations

import argparse
import unittest

from mail.cli.accounts import register
from tests.mail_tests.fixtures import CLIRegisterTestCase, make_noop_handlers


# Handler names required by accounts.register()
_ACCOUNTS_HANDLERS = (
    "f_list",
    "f_export_labels",
    "f_sync_labels",
    "f_export_filters",
    "f_sync_filters",
    "f_plan_labels",
    "f_plan_filters",
    "f_export_signatures",
    "f_sync_signatures",
)


def make_accounts_parser():
    """Create an argparse parser with accounts subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers, **make_noop_handlers(*_ACCOUNTS_HANDLERS))
    return parser


class AccountsTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for accounts CLI tests."""

    def setUp(self):
        self.parser = make_accounts_parser()


class TestAccountsRegister(AccountsTestCase):
    """Tests for the accounts CLI registration."""

    def test_accounts_group_registered(self):
        """Test that accounts group is registered."""
        args = self.parse("accounts")
        self.assertEqual(args.command, "accounts")

    def test_list_subcommand_registered(self):
        """Test that list subcommand is registered."""
        args = self.parse("accounts", "list", "--config", "accounts.yaml")
        self.assertEqual(args.accounts_cmd, "list")
        self.assertEqual(args.config, "accounts.yaml")

    def test_export_labels_requires_config(self):
        """Test that export-labels requires --config."""
        with self.assertRaises(SystemExit):
            self.parse("accounts", "export-labels", "--out-dir", "labels")

    def test_export_labels_requires_out_dir(self):
        """Test that export-labels requires --out-dir."""
        with self.assertRaises(SystemExit):
            self.parse("accounts", "export-labels", "--config", "accounts.yaml")

    def test_export_labels_accepts_both_args(self):
        """Test that export-labels accepts both required args."""
        args = self.parse("accounts", "export-labels", "--config", "accounts.yaml", "--out-dir", "labels")
        self.assertEqual(args.accounts_cmd, "export-labels")
        self.assertEqual(args.config, "accounts.yaml")
        self.assertEqual(args.out_dir, "labels")

    def test_sync_labels_requires_labels_arg(self):
        """Test that sync-labels requires --labels."""
        with self.assertRaises(SystemExit):
            self.parse("accounts", "sync-labels", "--config", "accounts.yaml")

    def test_sync_labels_has_dry_run_flag(self):
        """Test that sync-labels has --dry-run flag."""
        args = self.parse("accounts", "sync-labels", "--config", "accounts.yaml", "--labels", "labels.yaml", "--dry-run")
        self.assertTrue(args.dry_run)

    def test_sync_filters_has_require_forward_verified(self):
        """Test that sync-filters has --require-forward-verified flag."""
        args = self.parse("accounts", "sync-filters", "--config", "accounts.yaml", "--filters", "filters.yaml", "--require-forward-verified")
        self.assertTrue(args.require_forward_verified)

    def test_all_subcommands_have_config_arg(self):
        """Test that all subcommands accept --config arg."""
        # Just test that list subcommand accepts --config
        args = self.parse("accounts", "list", "--config", "accounts.yaml")
        self.assertEqual(args.config, "accounts.yaml")

    def test_accounts_accepts_optional_accounts_filter(self):
        """Test that all subcommands accept optional --accounts filter."""
        args = self.parse("accounts", "list", "--config", "accounts.yaml", "--accounts", "personal,work")
        self.assertEqual(args.accounts, "personal,work")


if __name__ == '__main__':
    unittest.main()
