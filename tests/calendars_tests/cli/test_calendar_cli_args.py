"""Tests for calendars/cli/args.py helper functions."""
import argparse
import unittest

from calendars.cli.args import (
    add_common_outlook_args,
    add_common_gmail_auth_args,
    add_common_gmail_paging_args,
    HELP_START_DATE,
    HELP_END_DATE,
    HELP_CALENDAR_DEFAULT,
    HELP_CONFIG_EVENTS,
    HELP_DRY_RUN,
    HELP_DEFAULT_CALENDAR,
    HELP_INBOX_ONLY,
)


class TestAddCommonOutlookArgs(unittest.TestCase):
    """Tests for add_common_outlook_args function."""

    def test_adds_outlook_auth_args_to_parser(self):
        """add_common_outlook_args should add outlook auth arguments."""
        parser = argparse.ArgumentParser()
        result = add_common_outlook_args(parser)
        # Result should be the parser
        self.assertIs(result, parser)
        # Parse with minimal outlook args to verify they exist
        args = parser.parse_args(['--client-id', 'test-client'])
        self.assertEqual(args.client_id, 'test-client')

    def test_sets_tenant_default_to_consumers(self):
        """add_common_outlook_args should set tenant default to consumers."""
        parser = argparse.ArgumentParser()
        add_common_outlook_args(parser)
        args = parser.parse_args([])
        # Verify tenant defaults to consumers
        self.assertEqual(args.tenant, 'consumers')


class TestAddCommonGmailAuthArgs(unittest.TestCase):
    """Tests for add_common_gmail_auth_args function."""

    def test_adds_gmail_auth_args_to_parser(self):
        """add_common_gmail_auth_args should add gmail auth arguments."""
        parser = argparse.ArgumentParser()
        result = add_common_gmail_auth_args(parser)
        # Result should be the parser
        self.assertIs(result, parser)
        # Verify cache argument is included
        args = parser.parse_args(['--cache', '/tmp/cache'])
        self.assertEqual(args.cache, '/tmp/cache')


class TestAddCommonGmailPagingArgs(unittest.TestCase):
    """Tests for add_common_gmail_paging_args function."""

    def test_adds_paging_args_with_custom_defaults(self):
        """add_common_gmail_paging_args should add paging args with specified defaults."""
        parser = argparse.ArgumentParser()
        result = add_common_gmail_paging_args(
            parser,
            default_days=30,
            default_pages=5,
            default_page_size=100,
        )
        # Result should be the parser
        self.assertIs(result, parser)
        args = parser.parse_args([])
        self.assertEqual(args.days, 30)
        self.assertEqual(args.pages, 5)
        self.assertEqual(args.page_size, 100)

    def test_allows_override_of_defaults(self):
        """Paging args can be overridden via command line."""
        parser = argparse.ArgumentParser()
        add_common_gmail_paging_args(
            parser,
            default_days=30,
            default_pages=5,
            default_page_size=100,
        )
        args = parser.parse_args(['--days', '60', '--pages', '10', '--page-size', '50'])
        self.assertEqual(args.days, 60)
        self.assertEqual(args.pages, 10)
        self.assertEqual(args.page_size, 50)


class TestHelpConstants(unittest.TestCase):
    """Tests for help string constants."""

    def test_help_constants_are_strings(self):
        """All help constants should be non-empty strings."""
        self.assertIsInstance(HELP_START_DATE, str)
        self.assertIsInstance(HELP_END_DATE, str)
        self.assertIsInstance(HELP_CALENDAR_DEFAULT, str)
        self.assertIsInstance(HELP_CONFIG_EVENTS, str)
        self.assertIsInstance(HELP_DRY_RUN, str)
        self.assertIsInstance(HELP_DEFAULT_CALENDAR, str)
        self.assertIsInstance(HELP_INBOX_ONLY, str)
        self.assertTrue(HELP_START_DATE)
        self.assertTrue(HELP_END_DATE)
        self.assertTrue(HELP_CALENDAR_DEFAULT)
        self.assertTrue(HELP_CONFIG_EVENTS)
        self.assertTrue(HELP_DRY_RUN)
        self.assertTrue(HELP_DEFAULT_CALENDAR)
        self.assertTrue(HELP_INBOX_ONLY)
