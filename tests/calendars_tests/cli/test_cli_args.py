"""Tests for calendars/cli/args.py — constants and helper functions."""
import argparse
import unittest

from calendars.cli.args import (
    HELP_START_DATE,
    HELP_END_DATE,
    HELP_CALENDAR_DEFAULT,
    HELP_CONFIG_EVENTS,
    HELP_DRY_RUN,
    HELP_DEFAULT_CALENDAR,
    HELP_INBOX_ONLY,
    add_common_outlook_args,
    add_common_gmail_auth_args,
    add_common_gmail_paging_args,
)


class TestHelpConstants(unittest.TestCase):
    def test_help_start_date(self):
        self.assertIsInstance(HELP_START_DATE, str)
        self.assertGreater(len(HELP_START_DATE), 0)

    def test_help_end_date(self):
        self.assertIsInstance(HELP_END_DATE, str)
        self.assertGreater(len(HELP_END_DATE), 0)

    def test_help_calendar_default(self):
        self.assertIsInstance(HELP_CALENDAR_DEFAULT, str)

    def test_help_config_events(self):
        self.assertIsInstance(HELP_CONFIG_EVENTS, str)

    def test_help_dry_run(self):
        self.assertIsInstance(HELP_DRY_RUN, str)

    def test_help_default_calendar(self):
        self.assertIsInstance(HELP_DEFAULT_CALENDAR, str)

    def test_help_inbox_only(self):
        self.assertIsInstance(HELP_INBOX_ONLY, str)


class TestAddCommonOutlookArgs(unittest.TestCase):
    def test_adds_args_to_parser(self):
        sp = argparse.ArgumentParser()
        add_common_outlook_args(sp)
        # Should return the parser (or None) without raising
        # The important thing is the parser has been configured
        action_dests = {a.dest for a in sp._actions}
        # Should add at least some auth-related args (profile/token/client_id/tenant)
        self.assertTrue(
            bool(action_dests - {"help"}),
            "expected auth args to be added to parser",
        )


class TestAddCommonGmailAuthArgs(unittest.TestCase):
    def test_adds_args_to_parser(self):
        sp = argparse.ArgumentParser()
        add_common_gmail_auth_args(sp)
        action_dests = {a.dest for a in sp._actions}
        self.assertTrue(bool(action_dests - {"help"}))


class TestAddCommonGmailPagingArgs(unittest.TestCase):
    def test_adds_days_pages_page_size(self):
        sp = argparse.ArgumentParser()
        add_common_gmail_paging_args(sp, default_days=30, default_pages=3, default_page_size=50)
        ns = sp.parse_args([])
        self.assertEqual(ns.days, 30)
        self.assertEqual(ns.pages, 3)
        self.assertEqual(ns.page_size, 50)

    def test_overrides_via_args(self):
        sp = argparse.ArgumentParser()
        add_common_gmail_paging_args(sp, default_days=30, default_pages=3, default_page_size=50)
        ns = sp.parse_args(["--days", "60", "--pages", "5", "--page-size", "100"])
        self.assertEqual(ns.days, 60)
        self.assertEqual(ns.pages, 5)
        self.assertEqual(ns.page_size, 100)

    def test_days_help_contains_default(self):
        sp = argparse.ArgumentParser()
        add_common_gmail_paging_args(sp, default_days=14, default_pages=2, default_page_size=25)
        days_action = next(a for a in sp._actions if a.dest == "days")
        self.assertIn("14", days_action.help)

    def test_returns_parser(self):
        sp = argparse.ArgumentParser()
        result = add_common_gmail_paging_args(sp, default_days=7, default_pages=1, default_page_size=10)
        self.assertIs(result, sp)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
