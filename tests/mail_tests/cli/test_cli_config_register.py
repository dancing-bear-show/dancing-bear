"""Tests for mail/cli/config.py CLI registration."""

from __future__ import annotations

import argparse
import unittest

from mail.cli.config import register
from tests.mail_tests.fixtures import (
    CLIRegisterTestCase,
    make_noop_handlers,
    noop_handler,
)


# Handler names required by config.register()
_CONFIG_HANDLERS = (
    "f_inspect",
    "f_derive_labels",
    "f_derive_filters",
    "f_optimize_filters",
    "f_audit_filters",
)


def make_config_parser():
    """Create an argparse parser with config subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers, **make_noop_handlers(*_CONFIG_HANDLERS))
    return parser


class ConfigTestCase(CLIRegisterTestCase, unittest.TestCase):
    """Base class for config CLI tests."""

    def setUp(self):
        self.parser = make_config_parser()


class TestConfigRegister(ConfigTestCase):
    """Tests for the config CLI registration."""

    def test_config_group_registered(self):
        """Test that config group is registered."""
        args = self.parse("config")
        self.assertEqual(args.command, "config")

    def test_config_has_subparsers(self):
        """Test that config has subcommand destination."""
        args = self.parse("config")
        self.assertIsNone(args.config_cmd)


class TestConfigInspectSubcommand(ConfigTestCase):
    """Tests for config inspect subcommand."""

    def test_inspect_subcommand(self):
        """Test inspect subcommand is registered."""
        args = self.parse("config", "inspect")
        self.assertEqual(args.config_cmd, "inspect")
        self.assertEqual(args.func, noop_handler)

    def test_inspect_default_path(self):
        """Test inspect has default path."""
        args = self.parse("config", "inspect")
        self.assertEqual(args.path, "~/.config/credentials.ini")

    def test_inspect_custom_path(self):
        """Test inspect accepts custom path."""
        args = self.parse("config", "inspect", "--path", "/custom/creds.ini")
        self.assertEqual(args.path, "/custom/creds.ini")

    def test_inspect_section_arg(self):
        """Test inspect accepts --section arg."""
        args = self.parse("config", "inspect", "--section", "mail.gmail")
        self.assertEqual(args.section, "mail.gmail")

    def test_inspect_only_mail_flag(self):
        """Test inspect accepts --only-mail flag."""
        args = self.parse("config", "inspect", "--only-mail")
        self.assertTrue(args.only_mail)

    def test_inspect_only_mail_default_false(self):
        """Test inspect --only-mail is false by default."""
        args = self.parse("config", "inspect")
        self.assertFalse(args.only_mail)


class TestConfigDeriveLabelsSubcommand(ConfigTestCase):
    """Tests for config derive labels subcommand."""

    def test_derive_labels_subcommand(self):
        """Test derive labels subcommand is registered."""
        args = self.parse(
            "config", "derive", "labels",
            "--in", "/in.yaml",
            "--out-gmail", "/gmail.yaml",
            "--out-outlook", "/outlook.yaml"
        )
        self.assertEqual(args.config_cmd, "derive")
        self.assertEqual(args.derive_cmd, "labels")
        self.assertEqual(args.func, noop_handler)

    def test_derive_labels_requires_in(self):
        """Test derive labels requires --in argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "labels",
                "--out-gmail", "/gmail.yaml",
                "--out-outlook", "/outlook.yaml"
            )

    def test_derive_labels_requires_out_gmail(self):
        """Test derive labels requires --out-gmail argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "labels",
                "--in", "/in.yaml",
                "--out-outlook", "/outlook.yaml"
            )

    def test_derive_labels_requires_out_outlook(self):
        """Test derive labels requires --out-outlook argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "labels",
                "--in", "/in.yaml",
                "--out-gmail", "/gmail.yaml"
            )

    def test_derive_labels_args(self):
        """Test derive labels parses all args correctly."""
        args = self.parse(
            "config", "derive", "labels",
            "--in", "/unified.yaml",
            "--out-gmail", "/gmail_labels.yaml",
            "--out-outlook", "/outlook_cats.yaml"
        )
        self.assertEqual(args.in_path, "/unified.yaml")
        self.assertEqual(args.out_gmail, "/gmail_labels.yaml")
        self.assertEqual(args.out_outlook, "/outlook_cats.yaml")


class TestConfigDeriveFiltersSubcommand(ConfigTestCase):
    """Tests for config derive filters subcommand."""

    def test_derive_filters_subcommand(self):
        """Test derive filters subcommand is registered."""
        args = self.parse(
            "config", "derive", "filters",
            "--in", "/in.yaml",
            "--out-gmail", "/gmail.yaml",
            "--out-outlook", "/outlook.yaml"
        )
        self.assertEqual(args.config_cmd, "derive")
        self.assertEqual(args.derive_cmd, "filters")
        self.assertEqual(args.func, noop_handler)

    def test_derive_filters_requires_in(self):
        """Test derive filters requires --in argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "filters",
                "--out-gmail", "/gmail.yaml",
                "--out-outlook", "/outlook.yaml"
            )

    def test_derive_filters_requires_out_gmail(self):
        """Test derive filters requires --out-gmail argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "filters",
                "--in", "/in.yaml",
                "--out-outlook", "/outlook.yaml"
            )

    def test_derive_filters_requires_out_outlook(self):
        """Test derive filters requires --out-outlook argument."""
        with self.assertRaises(SystemExit):
            self.parse(
                "config", "derive", "filters",
                "--in", "/in.yaml",
                "--out-gmail", "/gmail.yaml"
            )

    def test_derive_filters_outlook_move_default_true(self):
        """Test derive filters has --outlook-move-to-folders true by default."""
        args = self.parse(
            "config", "derive", "filters",
            "--in", "/in.yaml",
            "--out-gmail", "/gmail.yaml",
            "--out-outlook", "/outlook.yaml"
        )
        self.assertTrue(args.outlook_move_to_folders)

    def test_derive_filters_no_outlook_move(self):
        """Test derive filters --no-outlook-move-to-folders flag."""
        args = self.parse(
            "config", "derive", "filters",
            "--in", "/in.yaml",
            "--out-gmail", "/gmail.yaml",
            "--out-outlook", "/outlook.yaml",
            "--no-outlook-move-to-folders"
        )
        self.assertFalse(args.outlook_move_to_folders)

    def test_derive_filters_outlook_archive_on_remove_inbox(self):
        """Test derive filters --outlook-archive-on-remove-inbox flag."""
        args = self.parse(
            "config", "derive", "filters",
            "--in", "/in.yaml",
            "--out-gmail", "/gmail.yaml",
            "--out-outlook", "/outlook.yaml",
            "--outlook-archive-on-remove-inbox"
        )
        self.assertTrue(args.outlook_archive_on_remove_inbox)


class TestConfigOptimizeFiltersSubcommand(ConfigTestCase):
    """Tests for config optimize filters subcommand."""

    def test_optimize_filters_subcommand(self):
        """Test optimize filters subcommand is registered."""
        args = self.parse(
            "config", "optimize", "filters",
            "--in", "/in.yaml",
            "--out", "/out.yaml"
        )
        self.assertEqual(args.config_cmd, "optimize")
        self.assertEqual(args.optimize_cmd, "filters")
        self.assertEqual(args.func, noop_handler)

    def test_optimize_filters_requires_in(self):
        """Test optimize filters requires --in argument."""
        with self.assertRaises(SystemExit):
            self.parse("config", "optimize", "filters", "--out", "/out.yaml")

    def test_optimize_filters_requires_out(self):
        """Test optimize filters requires --out argument."""
        with self.assertRaises(SystemExit):
            self.parse("config", "optimize", "filters", "--in", "/in.yaml")

    def test_optimize_filters_default_merge_threshold(self):
        """Test optimize filters has default merge-threshold of 2."""
        args = self.parse(
            "config", "optimize", "filters",
            "--in", "/in.yaml",
            "--out", "/out.yaml"
        )
        self.assertEqual(args.merge_threshold, 2)

    def test_optimize_filters_custom_merge_threshold(self):
        """Test optimize filters accepts custom merge-threshold."""
        args = self.parse(
            "config", "optimize", "filters",
            "--in", "/in.yaml",
            "--out", "/out.yaml",
            "--merge-threshold", "5"
        )
        self.assertEqual(args.merge_threshold, 5)

    def test_optimize_filters_preview_flag(self):
        """Test optimize filters accepts --preview flag."""
        args = self.parse(
            "config", "optimize", "filters",
            "--in", "/in.yaml",
            "--out", "/out.yaml",
            "--preview"
        )
        self.assertTrue(args.preview)


class TestConfigAuditFiltersSubcommand(ConfigTestCase):
    """Tests for config audit filters subcommand."""

    def test_audit_filters_subcommand(self):
        """Test audit filters subcommand is registered."""
        args = self.parse(
            "config", "audit", "filters",
            "--in", "/unified.yaml",
            "--export", "/gmail_export.yaml"
        )
        self.assertEqual(args.config_cmd, "audit")
        self.assertEqual(args.audit_cmd, "filters")
        self.assertEqual(args.func, noop_handler)

    def test_audit_filters_requires_in(self):
        """Test audit filters requires --in argument."""
        with self.assertRaises(SystemExit):
            self.parse("config", "audit", "filters", "--export", "/export.yaml")

    def test_audit_filters_requires_export(self):
        """Test audit filters requires --export argument."""
        with self.assertRaises(SystemExit):
            self.parse("config", "audit", "filters", "--in", "/in.yaml")

    def test_audit_filters_args(self):
        """Test audit filters parses all args correctly."""
        args = self.parse(
            "config", "audit", "filters",
            "--in", "/unified.yaml",
            "--export", "/gmail_export.yaml"
        )
        self.assertEqual(args.in_path, "/unified.yaml")
        self.assertEqual(args.export_path, "/gmail_export.yaml")

    def test_audit_filters_preview_missing_flag(self):
        """Test audit filters accepts --preview-missing flag."""
        args = self.parse(
            "config", "audit", "filters",
            "--in", "/unified.yaml",
            "--export", "/gmail_export.yaml",
            "--preview-missing"
        )
        self.assertTrue(args.preview_missing)


if __name__ == "__main__":
    unittest.main()
