"""Tests for run_outlook_add_recurring command."""

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
        self.assertEqual(request.params.byday, ["MO", "WE", "FR"])

    @patch("calendars.outlook.commands._build_outlook_service")
    def test_returns_1_when_service_fails(self, mock_build_svc):
        from calendars.outlook.commands import run_outlook_add_recurring
        mock_build_svc.return_value = None
        args = self._make_args(repeat="daily", until="2024-12-31")
        result = run_outlook_add_recurring(args)
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
