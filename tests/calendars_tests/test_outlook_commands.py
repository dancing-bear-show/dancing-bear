"""Tests for calendars/outlook/commands.py command orchestration."""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch
from io import StringIO


class TestRunOutlookAddRecurring(unittest.TestCase):
    """Tests for run_outlook_add_recurring validation logic."""

    def _make_args(self, **kwargs):
        """Create an argparse Namespace with defaults."""
        defaults = {
            "subject": "Test Event",
            "start_time": "09:00",
            "end_time": "10:00",
            "repeat": "weekly",
            "range_start": "2024-01-01",
            "until": None,
            "count": None,
            "byday": None,
            "calendar": None,
            "tz": None,
            "interval": 1,
            "body_html": None,
            "location": None,
            "exdates": None,
            "no_reminder": False,
            "reminder_minutes": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_requires_until_or_count(self):
        from calendars.outlook.commands import run_outlook_add_recurring
        args = self._make_args(until=None, count=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_add_recurring(args)
        self.assertEqual(result, 2)
        self.assertIn("--until", mock_stdout.getvalue())

    def test_weekly_requires_byday(self):
        from calendars.outlook.commands import run_outlook_add_recurring
        args = self._make_args(repeat="weekly", until="2024-12-31", byday=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_add_recurring(args)
        self.assertEqual(result, 2)
        self.assertIn("--byday", mock_stdout.getvalue())

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_parses_byday_string(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add_recurring
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            repeat="weekly",
            until="2024-12-31",
            byday="MO,WE,FR",
        )
        result = run_outlook_add_recurring(args)
        self.assertEqual(result, 0)
        # Verify byday was parsed correctly
        call_args = mock_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.byday, ["MO", "WE", "FR"])

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add_recurring
        mock_build_svc.return_value = None
        args = self._make_args(repeat="daily", until="2024-12-31")
        result = run_outlook_add_recurring(args)
        self.assertEqual(result, 1)


class TestRunOutlookRemindersSet(unittest.TestCase):
    """Tests for run_outlook_reminders_set validation logic."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": None,
            "from_date": None,
            "to_date": None,
            "dry_run": False,
            "off": False,
            "minutes": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_requires_minutes_unless_off(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_reminders_set
        mock_build_svc.return_value = MagicMock()
        args = self._make_args(off=False, minutes=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_reminders_set(args)
        self.assertEqual(result, 2)
        self.assertIn("--minutes", mock_stdout.getvalue())

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_off_flag_does_not_require_minutes(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_reminders_set
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(off=True, minutes=None)
        result = run_outlook_reminders_set(args)
        self.assertEqual(result, 0)


class TestBuildOutlookService(unittest.TestCase):
    """Tests for _build_outlook_service helper."""

    @patch("calendars.outlook.commands.build_outlook_service_from_args")
    def test_returns_none_on_exception(self, mock_build):
        from calendars.outlook.commands import _build_outlook_service
        mock_build.side_effect = Exception("Auth failed")
        args = argparse.Namespace(profile=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = _build_outlook_service(args)
        self.assertIsNone(result)
        self.assertIn("Auth failed", mock_stdout.getvalue())

    @patch("calendars.outlook.commands.build_outlook_service_from_args")
    def test_returns_service_on_success(self, mock_build):
        from calendars.outlook.commands import _build_outlook_service
        mock_svc = MagicMock()
        mock_build.return_value = mock_svc
        args = argparse.Namespace(profile=None)
        result = _build_outlook_service(args)
        self.assertEqual(result, mock_svc)


class TestRunOutlookMailList(unittest.TestCase):
    """Tests for run_outlook_mail_list command."""

    def _make_args(self, **kwargs):
        defaults = {
            "folder": "inbox",
            "top": 5,
            "pages": 1,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_mail_list
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_mail_list(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_request_with_args(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_mail_list
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(folder="sent", top=10, pages=2)
        result = run_outlook_mail_list(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.folder, "sent")
        self.assertEqual(request.top, 10)
        self.assertEqual(request.pages, 2)


class TestRunOutlookAdd(unittest.TestCase):
    """Tests for run_outlook_add command."""

    def _make_args(self, **kwargs):
        defaults = {
            "subject": "Test Event",
            "start": "2024-01-15T09:00:00",
            "end": "2024-01-15T10:00:00",
            "calendar": None,
            "tz": None,
            "body_html": None,
            "all_day": False,
            "location": None,
            "no_reminder": False,
            "reminder_minutes": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_event_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            subject="Meeting",
            location="Room A",
            no_reminder=True,
        )
        result = run_outlook_add(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.subject, "Meeting")
        self.assertEqual(request.location, "Room A")
        self.assertTrue(request.no_reminder)


class TestRunOutlookDedup(unittest.TestCase):
    """Tests for run_outlook_dedup command."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": None,
            "from_date": None,
            "to_date": None,
            "apply": False,
            "keep_newest": False,
            "prefer_delete_nonstandard": False,
            "delete_standardized": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_passes_dedup_flags(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_dedup
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            apply=True,
            keep_newest=True,
            prefer_delete_nonstandard=True,
        )
        result = run_outlook_dedup(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertTrue(request.apply)
        self.assertTrue(request.keep_newest)
        self.assertTrue(request.prefer_delete_nonstandard)


class TestRunOutlookLocationsEnrich(unittest.TestCase):
    """Tests for run_outlook_locations_enrich command."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": "Work",
            "from_date": None,
            "to_date": None,
            "dry_run": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_enrich_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_locations_enrich
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            calendar="Personal",
            from_date="2024-01-01",
            to_date="2024-12-31",
            dry_run=True,
        )
        result = run_outlook_locations_enrich(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.calendar, "Personal")
        self.assertEqual(request.from_date, "2024-01-01")
        self.assertTrue(request.dry_run)


class TestRunOutlookCalendarShare(unittest.TestCase):
    """Tests for run_outlook_calendar_share command."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": "Work",
            "recipient": None,
            "role": "write",
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_calendar_share
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_calendar_share(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_share_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_calendar_share
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            calendar="Personal",
            recipient="user@example.com",
            role="read",
        )
        result = run_outlook_calendar_share(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.calendar, "Personal")
        self.assertEqual(request.recipient, "user@example.com")
        self.assertEqual(request.role, "read")


class TestRunOutlookScheduleImport(unittest.TestCase):
    """Tests for run_outlook_schedule_import command."""

    def _make_args(self, **kwargs):
        defaults = {
            "source": "schedule.yaml",
            "kind": None,
            "calendar": None,
            "tz": None,
            "until": None,
            "dry_run": False,
            "no_reminder": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_schedule_import
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_schedule_import(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_import_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_schedule_import
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            source="classes.yaml",
            kind="recurring",
            calendar="Kids",
            dry_run=True,
            no_reminder=True,
        )
        result = run_outlook_schedule_import(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.source, "classes.yaml")
        self.assertEqual(request.kind, "recurring")
        self.assertEqual(request.calendar, "Kids")
        self.assertTrue(request.dry_run)
        self.assertTrue(request.no_reminder)


class TestRunOutlookAddFromConfig(unittest.TestCase):
    """Tests for run_outlook_add_from_config command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "events.yaml",
            "dry_run": False,
            "no_reminder": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add_from_config
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_add_from_config(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_add_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add_from_config
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            config="my_events.yaml",
            dry_run=True,
            no_reminder=True,
        )
        result = run_outlook_add_from_config(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.config_path, Path("my_events.yaml"))
        self.assertTrue(request.dry_run)
        self.assertTrue(request.force_no_reminder)


class TestRunOutlookVerifyFromConfig(unittest.TestCase):
    """Tests for run_outlook_verify_from_config command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "events.yaml",
            "calendar": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_verify_from_config
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_verify_from_config(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_verify_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_verify_from_config
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            config="schedule.yaml",
            calendar="Work",
        )
        result = run_outlook_verify_from_config(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.config_path, Path("schedule.yaml"))
        self.assertEqual(request.calendar, "Work")


class TestRunOutlookUpdateLocations(unittest.TestCase):
    """Tests for run_outlook_update_locations command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "locations.yaml",
            "calendar": None,
            "dry_run": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_update_locations
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_update_locations(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_locations_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_update_locations
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            config="locs.yaml",
            calendar="Personal",
            dry_run=True,
        )
        result = run_outlook_update_locations(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.config_path, Path("locs.yaml"))
        self.assertEqual(request.calendar, "Personal")
        self.assertTrue(request.dry_run)


class TestRunOutlookApplyLocations(unittest.TestCase):
    """Tests for run_outlook_apply_locations command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "locations.yaml",
            "calendar": None,
            "dry_run": False,
            "all_occurrences": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_apply_locations
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_apply_locations(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_apply_request_with_all_occurrences(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_apply_locations
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            all_occurrences=True,
            dry_run=True,
        )
        result = run_outlook_apply_locations(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertTrue(request.all_occurrences)
        self.assertTrue(request.dry_run)


class TestRunOutlookRemindersOff(unittest.TestCase):
    """Tests for run_outlook_reminders_off command."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": None,
            "from_date": None,
            "to_date": None,
            "dry_run": False,
            "all_occurrences": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_reminders_off
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_reminders_off(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_reminders_off_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_reminders_off
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            calendar="Work",
            from_date="2024-01-01",
            to_date="2024-12-31",
            all_occurrences=True,
        )
        result = run_outlook_reminders_off(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.calendar, "Work")
        self.assertTrue(request.set_off)
        self.assertIsNone(request.minutes)
        self.assertTrue(request.all_occurrences)


class TestRunOutlookListOneOffs(unittest.TestCase):
    """Tests for run_outlook_list_one_offs command."""

    def _make_args(self, **kwargs):
        defaults = {
            "calendar": None,
            "from_date": None,
            "to_date": None,
            "limit": 200,
            "out": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_list_one_offs
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_list_one_offs(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_list_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_list_one_offs
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            calendar="Personal",
            limit=50,
        )
        result = run_outlook_list_one_offs(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.calendar, "Personal")
        self.assertEqual(request.limit, 50)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_request_with_out_path(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_list_one_offs
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(out="events.yaml")
        result = run_outlook_list_one_offs(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.out_path, Path("events.yaml"))


class TestRunOutlookSettingsApply(unittest.TestCase):
    """Tests for run_outlook_settings_apply command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "settings.yaml",
            "calendar": None,
            "from_date": None,
            "to_date": None,
            "dry_run": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_settings_apply
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_settings_apply(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_settings_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_settings_apply
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            config="cal_settings.yaml",
            calendar="Work",
            from_date="2024-01-01",
            dry_run=True,
        )
        result = run_outlook_settings_apply(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.config_path, Path("cal_settings.yaml"))
        self.assertEqual(request.calendar, "Work")
        self.assertEqual(request.from_date, "2024-01-01")
        self.assertTrue(request.dry_run)


class TestRunOutlookRemoveFromConfig(unittest.TestCase):
    """Tests for run_outlook_remove_from_config command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "remove.yaml",
            "calendar": None,
            "subject_only": False,
            "apply": False,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_remove_from_config
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_remove_from_config(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    @patch("calendars.outlook.commands.run_pipeline")
    def test_creates_remove_request(self, mock_pipeline, mock_build_svc):
        from calendars.outlook.commands import run_outlook_remove_from_config
        from pathlib import Path
        mock_build_svc.return_value = MagicMock()
        mock_pipeline.return_value = 0
        args = self._make_args(
            config="to_remove.yaml",
            calendar="Work",
            subject_only=True,
            apply=True,
        )
        result = run_outlook_remove_from_config(args)
        self.assertEqual(result, 0)
        request = mock_pipeline.call_args[0][0]
        self.assertEqual(request.config_path, Path("to_remove.yaml"))
        self.assertEqual(request.calendar, "Work")
        self.assertTrue(request.subject_only)
        self.assertTrue(request.apply)


class TestRunOutlookScanClasses(unittest.TestCase):
    """Tests for run_outlook_scan_classes command."""

    def _make_args(self, **kwargs):
        defaults = {
            "from_text": "swim@example.com",
            "calendar": None,
            "days": 60,
            "top": 25,
            "pages": 2,
            "out": None,
            "profile": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_scan_classes
        mock_build_svc.return_value = None
        args = self._make_args()
        result = run_outlook_scan_classes(args)
        self.assertEqual(result, 1)

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_0_when_no_messages_found(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_scan_classes
        mock_svc = MagicMock()
        mock_svc.search_inbox_messages.return_value = []
        mock_build_svc.return_value = mock_svc
        args = self._make_args()
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_scan_classes(args)
        self.assertEqual(result, 0)
        self.assertIn("No matching messages", mock_stdout.getvalue())

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_0_when_no_schedule_lines_found(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_scan_classes
        mock_svc = MagicMock()
        mock_svc.search_inbox_messages.return_value = ["msg1"]
        mock_svc.get_message.return_value = {
            "subject": "Hello",
            "receivedDateTime": "2024-01-15T10:00:00Z",
            "from": {"emailAddress": {"address": "test@example.com"}},
            "body": {"content": "No schedule info here"},
        }
        mock_build_svc.return_value = mock_svc
        args = self._make_args()
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_scan_classes(args)
        self.assertEqual(result, 0)
        self.assertIn("No schedule-like lines", mock_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
