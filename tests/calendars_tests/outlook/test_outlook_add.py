"""Tests for Outlook add / import / verify / remove_from_config / schedule_import commands."""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch


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
        self.assertEqual(request.params.subject, "Meeting")
        self.assertEqual(request.params.location, "Room A")
        self.assertTrue(request.params.no_reminder)


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


if __name__ == "__main__":
    unittest.main()
