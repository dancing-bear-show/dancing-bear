"""Tests for calendars/cli/outlook.py — register() and OutlookCommandCallbacks."""
import argparse
import unittest
from unittest.mock import MagicMock


def _make_callbacks():
    """Build an OutlookCommandCallbacks with all no-op mock callables."""
    from calendars.cli.outlook import OutlookCommandCallbacks

    def noop_add_common(sp):
        pass  # no-op; real version adds --profile etc.

    return OutlookCommandCallbacks(
        f_add=MagicMock(return_value=0),
        f_add_recurring=MagicMock(return_value=0),
        f_add_from_config=MagicMock(return_value=0),
        f_verify_from_config=MagicMock(return_value=0),
        f_update_locations=MagicMock(return_value=0),
        f_apply_locations=MagicMock(return_value=0),
        f_locations_enrich=MagicMock(return_value=0),
        f_list_one_offs=MagicMock(return_value=0),
        f_remove_from_config=MagicMock(return_value=0),
        f_dedup=MagicMock(return_value=0),
        f_scan_classes=MagicMock(return_value=0),
        f_schedule_import=MagicMock(return_value=0),
        f_reminders_off=MagicMock(return_value=0),
        f_reminders_set=MagicMock(return_value=0),
        f_calendar_share=MagicMock(return_value=0),
        f_settings_apply=MagicMock(return_value=0),
        f_mail_list=MagicMock(return_value=0),
        add_common_outlook_args=noop_add_common,
    )


def _build_parser():
    """Build a top-level parser with the 'outlook' group registered."""
    from calendars.cli.outlook import register
    root = argparse.ArgumentParser(prog="calendar")
    sub = root.add_subparsers(dest="cmd")
    register(sub, _make_callbacks())
    return root


class TestOutlookCommandCallbacksDataclass(unittest.TestCase):
    def test_instantiate_callbacks(self):
        cb = _make_callbacks()
        self.assertIsNotNone(cb)
        self.assertTrue(callable(cb.f_add))
        self.assertTrue(callable(cb.add_common_outlook_args))


class TestRegisterSubcommands(unittest.TestCase):
    def setUp(self):
        self.parser = _build_parser()

    def _parse(self, args):
        return self.parser.parse_args(args)

    # ── add ──────────────────────────────────────────────────────────────────

    def test_add_required_args(self):
        ns = self._parse(["outlook", "add", "--subject", "Meeting", "--start", "2025-01-01T10:00", "--end", "2025-01-01T11:00"])
        self.assertEqual(ns.subject, "Meeting")
        self.assertEqual(ns.start, "2025-01-01T10:00")
        self.assertEqual(ns.end, "2025-01-01T11:00")

    def test_add_optional_flags(self):
        ns = self._parse([
            "outlook", "add",
            "--subject", "S", "--start", "2025-01-01T10:00", "--end", "2025-01-01T11:00",
            "--calendar", "Work",
            "--tz", "America/Toronto",
            "--all-day",
            "--no-reminder",
        ])
        self.assertEqual(ns.calendar, "Work")
        self.assertEqual(ns.tz, "America/Toronto")
        self.assertTrue(ns.all_day)
        self.assertTrue(ns.no_reminder)

    def test_add_reminder_minutes(self):
        ns = self._parse([
            "outlook", "add",
            "--subject", "S", "--start", "2025-01-01T10:00", "--end", "2025-01-01T11:00",
            "--reminder-minutes", "15",
        ])
        self.assertEqual(ns.reminder_minutes, 15)

    def test_add_func_set(self):
        ns = self._parse(["outlook", "add", "--subject", "S", "--start", "2025-01-01T10:00", "--end", "2025-01-01T11:00"])
        self.assertTrue(callable(ns.func))

    # ── add-recurring ─────────────────────────────────────────────────────────

    def test_add_recurring_required_args(self):
        ns = self._parse([
            "outlook", "add-recurring",
            "--subject", "Swim",
            "--repeat", "weekly",
            "--range-start", "2025-01-01",
            "--start-time", "17:00",
            "--end-time", "17:30",
        ])
        self.assertEqual(ns.subject, "Swim")
        self.assertEqual(ns.repeat, "weekly")
        self.assertEqual(ns.range_start, "2025-01-01")

    def test_add_recurring_optional_fields(self):
        ns = self._parse([
            "outlook", "add-recurring",
            "--subject", "Class",
            "--repeat", "weekly",
            "--range-start", "2025-01-01",
            "--start-time", "10:00",
            "--end-time", "11:00",
            "--byday", "MO,WE",
            "--until", "2025-06-30",
            "--interval", "2",
            "--no-reminder",
        ])
        self.assertEqual(ns.byday, "MO,WE")
        self.assertEqual(ns.until, "2025-06-30")
        self.assertEqual(ns.interval, 2)
        self.assertTrue(ns.no_reminder)

    def test_add_recurring_count(self):
        ns = self._parse([
            "outlook", "add-recurring",
            "--subject", "Class",
            "--repeat", "monthly",
            "--range-start", "2025-01-01",
            "--start-time", "10:00",
            "--end-time", "11:00",
            "--count", "10",
        ])
        self.assertEqual(ns.count, 10)

    # ── add-from-config ───────────────────────────────────────────────────────

    def test_add_from_config_required_args(self):
        ns = self._parse(["outlook", "add-from-config", "--config", "plan.yaml"])
        self.assertEqual(ns.config, "plan.yaml")
        self.assertFalse(ns.dry_run)
        self.assertFalse(ns.no_reminder)

    def test_add_from_config_dry_run(self):
        ns = self._parse(["outlook", "add-from-config", "--config", "plan.yaml", "--dry-run"])
        self.assertTrue(ns.dry_run)

    # ── verify-from-config ────────────────────────────────────────────────────

    def test_verify_from_config(self):
        ns = self._parse(["outlook", "verify-from-config", "--config", "plan.yaml"])
        self.assertEqual(ns.config, "plan.yaml")

    # ── update-locations ──────────────────────────────────────────────────────

    def test_update_locations(self):
        ns = self._parse(["outlook", "update-locations", "--config", "plan.yaml", "--dry-run"])
        self.assertEqual(ns.config, "plan.yaml")
        self.assertTrue(ns.dry_run)

    # ── apply-locations ───────────────────────────────────────────────────────

    def test_apply_locations(self):
        ns = self._parse([
            "outlook", "apply-locations",
            "--config", "plan.yaml",
            "--all-occurrences",
        ])
        self.assertEqual(ns.config, "plan.yaml")
        self.assertTrue(ns.all_occurrences)

    # ── locations-enrich ──────────────────────────────────────────────────────

    def test_locations_enrich(self):
        ns = self._parse([
            "outlook", "locations-enrich",
            "--calendar", "Family",
            "--from", "2025-01-01",
            "--to", "2025-12-31",
            "--dry-run",
        ])
        self.assertEqual(ns.calendar, "Family")
        self.assertEqual(ns.from_date, "2025-01-01")
        self.assertEqual(ns.to_date, "2025-12-31")
        self.assertTrue(ns.dry_run)

    # ── list-one-offs ─────────────────────────────────────────────────────────

    def test_list_one_offs_defaults(self):
        ns = self._parse(["outlook", "list-one-offs"])
        self.assertEqual(ns.limit, 200)

    def test_list_one_offs_with_options(self):
        ns = self._parse([
            "outlook", "list-one-offs",
            "--calendar", "Family",
            "--from", "2025-01-01",
            "--to", "2025-06-30",
            "--limit", "50",
            "--out", "out.yaml",
        ])
        self.assertEqual(ns.calendar, "Family")
        self.assertEqual(ns.from_date, "2025-01-01")
        self.assertEqual(ns.to_date, "2025-06-30")
        self.assertEqual(ns.limit, 50)
        self.assertEqual(ns.out, "out.yaml")

    # ── remove-from-config ────────────────────────────────────────────────────

    def test_remove_from_config(self):
        ns = self._parse([
            "outlook", "remove-from-config",
            "--config", "plan.yaml",
            "--apply",
            "--subject-only",
        ])
        self.assertEqual(ns.config, "plan.yaml")
        self.assertTrue(ns.apply)
        self.assertTrue(ns.subject_only)

    # ── dedup ─────────────────────────────────────────────────────────────────

    def test_dedup_defaults(self):
        ns = self._parse(["outlook", "dedup"])
        self.assertFalse(ns.apply)
        self.assertFalse(ns.keep_newest)
        self.assertFalse(ns.delete_standardized)

    def test_dedup_flags(self):
        ns = self._parse([
            "outlook", "dedup",
            "--calendar", "Family",
            "--apply",
            "--keep-newest",
            "--delete-standardized",
            "--prefer-delete-nonstandard",
        ])
        self.assertTrue(ns.apply)
        self.assertTrue(ns.keep_newest)
        self.assertTrue(ns.delete_standardized)
        self.assertTrue(ns.prefer_delete_nonstandard)

    # ── scan-classes ──────────────────────────────────────────────────────────

    def test_scan_classes_defaults(self):
        ns = self._parse(["outlook", "scan-classes"])
        self.assertEqual(ns.days, 60)
        self.assertEqual(ns.top, 25)
        self.assertEqual(ns.pages, 2)

    def test_scan_classes_options(self):
        ns = self._parse([
            "outlook", "scan-classes",
            "--days", "30",
            "--top", "10",
            "--pages", "3",
            "--out", "plan.yaml",
        ])
        self.assertEqual(ns.days, 30)
        self.assertEqual(ns.top, 10)
        self.assertEqual(ns.pages, 3)
        self.assertEqual(ns.out, "plan.yaml")

    # ── schedule-import ───────────────────────────────────────────────────────

    def test_schedule_import_required(self):
        ns = self._parse(["outlook", "schedule-import", "--source", "schedule.xlsx"])
        self.assertEqual(ns.source, "schedule.xlsx")
        self.assertEqual(ns.kind, "auto")
        self.assertFalse(ns.dry_run)

    def test_schedule_import_kind(self):
        ns = self._parse([
            "outlook", "schedule-import",
            "--source", "sched.csv",
            "--kind", "csv",
            "--dry-run",
        ])
        self.assertEqual(ns.kind, "csv")
        self.assertTrue(ns.dry_run)

    def test_schedule_import_kind_choices(self):
        """Only valid choices should be accepted."""
        with self.assertRaises(SystemExit):
            self._parse(["outlook", "schedule-import", "--source", "x", "--kind", "invalid"])

    # ── reminders-off ────────────────────────────────────────────────────────

    def test_reminders_off_dry_run(self):
        ns = self._parse([
            "outlook", "reminders-off",
            "--calendar", "Family",
            "--dry-run",
        ])
        self.assertEqual(ns.calendar, "Family")
        self.assertTrue(ns.dry_run)

    def test_reminders_off_all_occurrences(self):
        ns = self._parse([
            "outlook", "reminders-off",
            "--all-occurrences",
        ])
        self.assertTrue(ns.all_occurrences)

    # ── reminders-set ─────────────────────────────────────────────────────────

    def test_reminders_set_off_mode(self):
        ns = self._parse([
            "outlook", "reminders-set",
            "--calendar", "Work",
            "--off",
        ])
        self.assertTrue(ns.off)

    def test_reminders_set_minutes_mode(self):
        ns = self._parse([
            "outlook", "reminders-set",
            "--calendar", "Work",
            "--minutes", "10",
        ])
        self.assertEqual(ns.minutes, 10)
        self.assertFalse(ns.off)

    def test_reminders_set_mutually_exclusive(self):
        """--off and --minutes cannot both be provided."""
        with self.assertRaises(SystemExit):
            self._parse([
                "outlook", "reminders-set",
                "--calendar", "Work",
                "--off",
                "--minutes", "5",
            ])

    def test_reminders_set_requires_mode(self):
        """At least one of --off or --minutes is required."""
        with self.assertRaises(SystemExit):
            self._parse(["outlook", "reminders-set", "--calendar", "Work"])

    # ── calendar-share ────────────────────────────────────────────────────────

    def test_calendar_share(self):
        ns = self._parse([
            "outlook", "calendar-share",
            "--calendar", "Family",
            "--with", "user@example.com",
            "--role", "read",
        ])
        self.assertEqual(ns.calendar, "Family")
        self.assertEqual(ns.recipient, "user@example.com")
        self.assertEqual(ns.role, "read")

    def test_calendar_share_default_role(self):
        ns = self._parse([
            "outlook", "calendar-share",
            "--calendar", "Family",
            "--with", "user@example.com",
        ])
        self.assertEqual(ns.role, "write")

    # ── settings-apply ────────────────────────────────────────────────────────

    def test_settings_apply(self):
        ns = self._parse([
            "outlook", "settings-apply",
            "--config", "rules.yaml",
            "--dry-run",
        ])
        self.assertEqual(ns.config, "rules.yaml")
        self.assertTrue(ns.dry_run)

    # ── mail-list ─────────────────────────────────────────────────────────────

    def test_mail_list_defaults(self):
        ns = self._parse(["outlook", "mail-list"])
        self.assertEqual(ns.folder, "inbox")
        self.assertEqual(ns.top, 5)
        self.assertEqual(ns.pages, 1)

    def test_mail_list_options(self):
        ns = self._parse([
            "outlook", "mail-list",
            "--folder", "sent",
            "--top", "20",
            "--pages", "3",
        ])
        self.assertEqual(ns.folder, "sent")
        self.assertEqual(ns.top, 20)
        self.assertEqual(ns.pages, 3)

    # ── func callbacks set correctly ─────────────────────────────────────────

    def test_all_subcommands_have_func(self):
        subcommands_and_required = [
            (["outlook", "add", "--subject", "S", "--start", "2025-01-01T10:00", "--end", "2025-01-01T11:00"], "f_add"),
            (["outlook", "add-recurring", "--subject", "S", "--repeat", "weekly", "--range-start", "2025-01-01", "--start-time", "10:00", "--end-time", "11:00"], "f_add_recurring"),
            (["outlook", "add-from-config", "--config", "x.yaml"], "f_add_from_config"),
            (["outlook", "verify-from-config", "--config", "x.yaml"], "f_verify_from_config"),
            (["outlook", "update-locations", "--config", "x.yaml"], "f_update_locations"),
            (["outlook", "apply-locations", "--config", "x.yaml"], "f_apply_locations"),
            (["outlook", "locations-enrich", "--calendar", "C"], "f_locations_enrich"),
            (["outlook", "list-one-offs"], "f_list_one_offs"),
            (["outlook", "remove-from-config", "--config", "x.yaml"], "f_remove_from_config"),
            (["outlook", "dedup"], "f_dedup"),
            (["outlook", "scan-classes"], "f_scan_classes"),
            (["outlook", "schedule-import", "--source", "x.xlsx"], "f_schedule_import"),
            (["outlook", "reminders-off"], "f_reminders_off"),
            (["outlook", "reminders-set", "--calendar", "C", "--off"], "f_reminders_set"),
            (["outlook", "calendar-share", "--calendar", "C", "--with", "u@e.com"], "f_calendar_share"),
            (["outlook", "settings-apply", "--config", "x.yaml"], "f_settings_apply"),
            (["outlook", "mail-list"], "f_mail_list"),
        ]
        for args, _cb_name in subcommands_and_required:
            with self.subTest(cmd=args[1]):
                ns = self._parse(args)
                self.assertTrue(callable(ns.func), f"func not set for {args[1]}")

    # ── return value ─────────────────────────────────────────────────────────

    def test_register_returns_parser(self):
        from calendars.cli.outlook import register
        root = argparse.ArgumentParser()
        sub = root.add_subparsers(dest="cmd")
        p = register(sub, _make_callbacks())
        self.assertIsNotNone(p)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
