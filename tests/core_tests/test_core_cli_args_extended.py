"""Tests for core/cli_args.py uncovered branches (extended)."""

from __future__ import annotations

import argparse
import unittest

from core.cli_args import (
    add_gmail_auth_args,
    GmailAuthConfig,
    add_output_args,
    OutputConfig,
    add_dry_run_args,
    add_date_range_args,
    DateRangeConfig,
    add_profile_args,
    add_filter_args,
    ArgumentGroup,
)


class TestAddGmailAuthArgs(unittest.TestCase):
    def test_default_config_includes_cache(self):
        parser = argparse.ArgumentParser()
        add_gmail_auth_args(parser)
        args = parser.parse_args(["--credentials", "c.json", "--token", "t.json", "--cache", "cache.json"])
        self.assertEqual(args.credentials, "c.json")
        self.assertEqual(args.token, "t.json")
        self.assertEqual(args.cache, "cache.json")

    def test_no_cache_when_include_cache_false(self):
        parser = argparse.ArgumentParser()
        config = GmailAuthConfig(include_cache=False)
        add_gmail_auth_args(parser, config)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--cache", "cache.json"])

    def test_credentials_with_help(self):
        parser = argparse.ArgumentParser()
        config = GmailAuthConfig(credentials_help="Path to credentials")
        add_gmail_auth_args(parser, config)
        help_text = parser.format_help()
        self.assertIn("Path to credentials", help_text)

    def test_token_with_help(self):
        parser = argparse.ArgumentParser()
        config = GmailAuthConfig(token_help="Path to token")  # nosec B106 - test help string
        add_gmail_auth_args(parser, config)
        help_text = parser.format_help()
        self.assertIn("Path to token", help_text)

    def test_cache_with_help(self):
        parser = argparse.ArgumentParser()
        config = GmailAuthConfig(include_cache=True, cache_help="Cache path")
        add_gmail_auth_args(parser, config)
        help_text = parser.format_help()
        self.assertIn("Cache path", help_text)

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_gmail_auth_args(parser)
        self.assertIs(result, parser)


class TestAddOutputArgs(unittest.TestCase):
    def test_default_output_format(self):
        parser = argparse.ArgumentParser()
        add_output_args(parser)
        args = parser.parse_args([])
        self.assertEqual(args.output, "text")

    def test_custom_default_format(self):
        parser = argparse.ArgumentParser()
        config = OutputConfig(default_format="json")
        add_output_args(parser, config)
        args = parser.parse_args([])
        self.assertEqual(args.output, "json")

    def test_verbose_flag(self):
        parser = argparse.ArgumentParser()
        add_output_args(parser)
        args = parser.parse_args(["--verbose"])
        self.assertTrue(args.verbose)

    def test_quiet_flag(self):
        parser = argparse.ArgumentParser()
        add_output_args(parser)
        args = parser.parse_args(["--quiet"])
        self.assertTrue(args.quiet)

    def test_no_verbose_when_excluded(self):
        parser = argparse.ArgumentParser()
        config = OutputConfig(include_verbose=False)
        add_output_args(parser, config)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--verbose"])

    def test_no_quiet_when_excluded(self):
        parser = argparse.ArgumentParser()
        config = OutputConfig(include_quiet=False)
        add_output_args(parser, config)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--quiet"])

    def test_custom_formats(self):
        parser = argparse.ArgumentParser()
        config = OutputConfig(formats=["json", "csv"])
        add_output_args(parser, config)
        args = parser.parse_args(["--output", "csv"])
        self.assertEqual(args.output, "csv")

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_output_args(parser)
        self.assertIs(result, parser)


class TestAddDryRunArgs(unittest.TestCase):
    def test_dry_run_flag(self):
        parser = argparse.ArgumentParser()
        add_dry_run_args(parser)
        args = parser.parse_args(["--dry-run"])
        self.assertTrue(args.dry_run)

    def test_force_flag_when_included(self):
        parser = argparse.ArgumentParser()
        add_dry_run_args(parser, include_force=True)
        args = parser.parse_args(["--force"])
        self.assertTrue(args.force)

    def test_no_force_by_default(self):
        parser = argparse.ArgumentParser()
        add_dry_run_args(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--force"])

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_dry_run_args(parser)
        self.assertIs(result, parser)


class TestAddDateRangeArgs(unittest.TestCase):
    def test_default_config(self):
        parser = argparse.ArgumentParser()
        add_date_range_args(parser)
        args = parser.parse_args([])
        self.assertIsNone(args.from_date)
        self.assertIsNone(args.to_date)
        self.assertEqual(args.days_back, 30)

    def test_custom_days_back_default(self):
        parser = argparse.ArgumentParser()
        config = DateRangeConfig(default_days_back=7)
        add_date_range_args(parser, config)
        args = parser.parse_args([])
        self.assertEqual(args.days_back, 7)

    def test_days_forward_included(self):
        parser = argparse.ArgumentParser()
        config = DateRangeConfig(include_days_forward=True)
        add_date_range_args(parser, config)
        args = parser.parse_args([])
        self.assertEqual(args.days_forward, 180)

    def test_days_forward_excluded_by_default(self):
        parser = argparse.ArgumentParser()
        add_date_range_args(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--days-forward", "7"])

    def test_include_days_back_false(self):
        parser = argparse.ArgumentParser()
        config = DateRangeConfig(include_days_back=False)
        add_date_range_args(parser, config)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--days-back", "5"])

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_date_range_args(parser)
        self.assertIs(result, parser)


class TestAddProfileArgs(unittest.TestCase):
    def test_default_help(self):
        parser = argparse.ArgumentParser()
        add_profile_args(parser)
        help_text = parser.format_help()
        self.assertIn("Credentials profile name", help_text)

    def test_custom_help(self):
        parser = argparse.ArgumentParser()
        add_profile_args(parser, profile_help="Custom profile help")
        help_text = parser.format_help()
        self.assertIn("Custom profile help", help_text)

    def test_short_flag(self):
        parser = argparse.ArgumentParser()
        add_profile_args(parser)
        args = parser.parse_args(["-p", "myprofile"])
        self.assertEqual(args.profile, "myprofile")

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_profile_args(parser)
        self.assertIs(result, parser)


class TestAddFilterArgs(unittest.TestCase):
    def test_default_limit(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser)
        args = parser.parse_args([])
        self.assertEqual(args.limit, 100)

    def test_custom_default_limit(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser, default_limit=50)
        args = parser.parse_args([])
        self.assertEqual(args.limit, 50)

    def test_offset_included(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser, include_offset=True)
        args = parser.parse_args(["--offset", "20"])
        self.assertEqual(args.offset, 20)

    def test_offset_not_included_by_default(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--offset", "5"])

    def test_no_limit_when_excluded(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser, include_limit=False)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--limit", "5"])

    def test_short_flag_n(self):
        parser = argparse.ArgumentParser()
        add_filter_args(parser)
        args = parser.parse_args(["-n", "25"])
        self.assertEqual(args.limit, 25)

    def test_returns_parser(self):
        parser = argparse.ArgumentParser()
        result = add_filter_args(parser)
        self.assertIs(result, parser)


class TestArgumentGroup(unittest.TestCase):
    def test_add_to_parser_with_tuple(self):
        parser = argparse.ArgumentParser()
        group = ArgumentGroup([
            (("--myarg",), {"help": "My argument", "default": "default_val"}),
        ])
        group.add_to_parser(parser)
        args = parser.parse_args([])
        self.assertEqual(args.myarg, "default_val")

    def test_add_to_parser_with_string_tuple(self):
        parser = argparse.ArgumentParser()
        group = ArgumentGroup([
            ("--flag", {"action": "store_true"}),
        ])
        group.add_to_parser(parser)
        args = parser.parse_args(["--flag"])
        self.assertTrue(args.flag)

    def test_add_to_parser_with_name_or_flags_object(self):
        # Test with an object that has name_or_flags attribute
        class FakeArg:
            name_or_flags = ("--testarg",)
            kwargs = {"default": "test_default"}

        parser = argparse.ArgumentParser()
        group = ArgumentGroup([FakeArg()])
        group.add_to_parser(parser)
        args = parser.parse_args([])
        self.assertEqual(args.testarg, "test_default")


if __name__ == "__main__":
    unittest.main()
