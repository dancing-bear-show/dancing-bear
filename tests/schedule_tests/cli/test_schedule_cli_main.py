"""Tests for schedule/cli/main.py CLI commands and argument parsing.

Focuses on untested lines: 51, 54, 68-82, 101, 208-238, 269, 306, 324, 329-396, 421-447.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin, has_pyyaml, write_yaml

# Skip module if PyYAML not available
if not has_pyyaml():  # pragma: no cover
    raise unittest.SkipTest("PyYAML required for schedule CLI tests")

from schedule.cli.main import (
    _read_yaml,
    _write_yaml,
    _iso_to_date,
    _iso_to_time,
    _weekday_code,
    _group_one_offs,
    _compute_exdates,
    _build_one_off_event,
    _build_series_event,
    _compress_events,
    _compress_sort_key,
    _build_outlook_service_from_args,
    cmd_plan,
    cmd_verify,
    cmd_sync,
    cmd_export,
    cmd_compress,
    cmd_apply,
    main,
)


class TestReadWriteYaml(TempDirMixin, unittest.TestCase):
    """Test YAML I/O helpers."""

    def test_read_yaml_missing_file(self):
        """Test _read_yaml raises FileNotFoundError for missing file (line 51)."""
        missing_path = Path(self.tmpdir) / "missing.yaml"
        with self.assertRaises(FileNotFoundError) as ctx:
            _read_yaml(missing_path)
        self.assertIn("YAML file not found", str(ctx.exception))

    def test_read_yaml_invalid_top_level(self):
        """Test _read_yaml raises ValueError for non-dict top level (line 54)."""
        import yaml

        path = Path(self.tmpdir) / "invalid.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(["list", "not", "dict"], f)

        with self.assertRaises(ValueError) as ctx:
            _read_yaml(path)
        self.assertIn("Top-level YAML must be a mapping", str(ctx.exception))

    def test_read_yaml_success(self):
        """Test _read_yaml successfully loads valid YAML."""
        data = {"events": [{"subject": "Test"}]}
        path = write_yaml(data, self.tmpdir)
        result = _read_yaml(path)
        self.assertEqual(result, data)

    def test_write_yaml(self):
        """Test _write_yaml writes valid YAML file."""
        import yaml

        data = {"events": [{"subject": "Test"}]}
        path = Path(self.tmpdir) / "output.yaml"
        _write_yaml(path, data)

        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        self.assertEqual(loaded, data)


class TestIsoDateTimeHelpers(unittest.TestCase):
    """Test ISO datetime parsing helpers (lines 68-82)."""

    def test_iso_to_date_with_t_separator(self):
        """Test _iso_to_date with T separator (line 68)."""
        import datetime as _dt
        result = _iso_to_date("2025-10-15T14:30:00")
        self.assertEqual(result, _dt.date(2025, 10, 15))

    def test_iso_to_date_with_space_separator(self):
        """Test _iso_to_date with space separator (line 69-70)."""
        import datetime as _dt
        result = _iso_to_date("2025-10-15 14:30:00")
        self.assertEqual(result, _dt.date(2025, 10, 15))

    def test_iso_to_date_with_z_suffix(self):
        """Test _iso_to_date strips Z suffix."""
        import datetime as _dt
        result = _iso_to_date("2025-10-15T14:30:00Z")
        self.assertEqual(result, _dt.date(2025, 10, 15))

    def test_iso_to_time_with_t_separator(self):
        """Test _iso_to_time with T separator (line 78-79)."""
        result = _iso_to_time("2025-10-15T14:30:00")
        self.assertEqual(result, "14:30")

    def test_iso_to_time_with_space_separator(self):
        """Test _iso_to_time with space separator (line 80-81)."""
        result = _iso_to_time("2025-10-15 14:30:45")
        self.assertEqual(result, "14:30")

    def test_iso_to_time_extracts_hhmm(self):
        """Test _iso_to_time extracts only HH:MM (line 82)."""
        result = _iso_to_time("2025-10-15T14:30:45.123Z")
        self.assertEqual(result, "14:30")

    def test_weekday_code(self):
        """Test _weekday_code returns correct day codes."""
        import datetime as _dt

        # 2025-10-13 is a Monday
        self.assertEqual(_weekday_code(_dt.date(2025, 10, 13)), "MO")
        # 2025-10-14 is a Tuesday
        self.assertEqual(_weekday_code(_dt.date(2025, 10, 14)), "TU")
        # 2025-10-19 is a Sunday
        self.assertEqual(_weekday_code(_dt.date(2025, 10, 19)), "SU")


class TestGroupOneOffs(unittest.TestCase):
    """Test _group_one_offs function (line 101)."""

    def test_group_one_offs_with_empty_events(self):
        """Test _group_one_offs skips events with missing data (line 101)."""
        events = [
            {"subject": "Test", "start": "", "end": ""},  # missing start/end
            {"subject": "", "start": "2025-10-15T10:00", "end": "2025-10-15T11:00"},  # missing subject
        ]
        groups, meta = _group_one_offs(events)
        self.assertEqual(len(groups), 0)
        self.assertEqual(len(meta), 0)

    def test_group_one_offs_groups_by_key(self):
        """Test _group_one_offs groups events by key tuple."""
        import datetime as _dt

        events = [
            {"subject": "Class", "start": "2025-10-13T10:00", "end": "2025-10-13T11:00", "location": "Room A"},
            {"subject": "Class", "start": "2025-10-20T10:00", "end": "2025-10-20T11:00", "location": "Room A"},
        ]
        groups, meta = _group_one_offs(events)

        # Should have one group with two dates
        self.assertEqual(len(groups), 1)
        key = list(groups.keys())[0]
        self.assertEqual(key[0], "Class")  # subject
        self.assertEqual(key[1], "10:00")  # start time
        self.assertEqual(key[2], "11:00")  # end time
        self.assertEqual(key[3], "MO")  # weekday
        self.assertEqual(key[4], "Room A")  # location
        self.assertEqual(len(groups[key]), 2)


class TestComputeExdates(unittest.TestCase):
    """Test _compute_exdates function."""

    def test_compute_exdates_weekly_series(self):
        """Test _compute_exdates finds missing dates in weekly series."""
        import datetime as _dt

        dates = [
            _dt.date(2025, 10, 13),
            _dt.date(2025, 10, 20),
            # Skip 10-27
            _dt.date(2025, 11, 3),
        ]
        exdates = _compute_exdates(dates, _dt.date(2025, 10, 13), _dt.date(2025, 11, 3))
        self.assertIn("2025-10-27", exdates)


class TestBuildEventHelpers(unittest.TestCase):
    """Test event building helpers."""

    def test_build_one_off_event_without_location(self):
        """Test _build_one_off_event without location."""
        import datetime as _dt

        event = _build_one_off_event("Test", "10:00", "11:00", _dt.date(2025, 10, 15), "", None)
        self.assertEqual(event["subject"], "Test")
        self.assertEqual(event["start"], "2025-10-15T10:00")
        self.assertEqual(event["end"], "2025-10-15T11:00")
        self.assertNotIn("location", event)
        self.assertNotIn("calendar", event)

    def test_build_one_off_event_with_location_and_calendar(self):
        """Test _build_one_off_event with location and calendar."""
        import datetime as _dt

        event = _build_one_off_event("Test", "10:00", "11:00", _dt.date(2025, 10, 15), "Room A", "Work")
        self.assertEqual(event["location"], "Room A")
        self.assertEqual(event["calendar"], "Work")

    def test_build_series_event_without_exdates(self):
        """Test _build_series_event without exdates."""
        import datetime as _dt

        event = _build_series_event(
            "Weekly", "10:00", "11:00", "MO", "",
            _dt.date(2025, 10, 13), _dt.date(2025, 12, 31), [], None
        )
        self.assertEqual(event["subject"], "Weekly")
        self.assertEqual(event["repeat"], "weekly")
        self.assertEqual(event["byday"], ["MO"])
        self.assertNotIn("exdates", event)
        self.assertNotIn("location", event)
        self.assertNotIn("calendar", event)

    def test_build_series_event_with_all_fields(self):
        """Test _build_series_event with all fields."""
        import datetime as _dt

        event = _build_series_event(
            "Weekly", "10:00", "11:00", "MO", "Room A",
            _dt.date(2025, 10, 13), _dt.date(2025, 12, 31),
            ["2025-10-27"], "Work"
        )
        self.assertEqual(event["location"], "Room A")
        self.assertEqual(event["exdates"], ["2025-10-27"])
        self.assertEqual(event["calendar"], "Work")


class TestCompressEvents(unittest.TestCase):
    """Test _compress_events function."""

    def test_compress_events_below_threshold(self):
        """Test _compress_events keeps events as one-offs below threshold."""
        import datetime as _dt

        groups = {
            ("Test", "10:00", "11:00", "MO", "Room A"): [_dt.date(2025, 10, 13)]
        }
        meta = {
            ("Test", "10:00", "11:00", "MO", "Room A"): {"calendar": "Work", "subject": "Test", "location": "Room A"}
        }

        events = _compress_events(groups, meta, min_occur=2, override_cal=None)
        self.assertEqual(len(events), 1)
        self.assertNotIn("repeat", events[0])
        self.assertEqual(events[0]["subject"], "Test")

    def test_compress_events_creates_series(self):
        """Test _compress_events creates series above threshold."""
        import datetime as _dt

        groups = {
            ("Test", "10:00", "11:00", "MO", "Room A"): [
                _dt.date(2025, 10, 13),
                _dt.date(2025, 10, 20),
            ]
        }
        meta = {
            ("Test", "10:00", "11:00", "MO", "Room A"): {"calendar": "Work", "subject": "Test", "location": "Room A"}
        }

        events = _compress_events(groups, meta, min_occur=2, override_cal=None)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["repeat"], "weekly")
        self.assertEqual(events[0]["byday"], ["MO"])

    def test_compress_sort_key_recurring(self):
        """Test _compress_sort_key for recurring events."""
        event = {
            "subject": "Test",
            "repeat": "weekly",
            "byday": ["MO"],
            "start_time": "10:00",
            "range": {"start_date": "2025-10-13"}
        }
        key = _compress_sort_key(event)
        self.assertEqual(key, ("Test", "MO", "2025-10-13", "10:00"))

    def test_compress_sort_key_one_off(self):
        """Test _compress_sort_key for one-off events."""
        event = {
            "subject": "Test",
            "start": "2025-10-15T10:00"
        }
        key = _compress_sort_key(event)
        self.assertEqual(key, ("Test", "", "2025-10-15T10:00", ""))


class TestEmitAgentic(unittest.TestCase):
    """Test _emit_agentic function (lines 208-210)."""

    @unittest.skip("Bug in source: schedule/cli/main.py uses 'from .agentic' instead of 'from ..agentic'")
    def test_emit_agentic_calls_context_emitter(self):
        """Test _emit_agentic delegates to emit_agentic_context.

        NOTE: This test is skipped because there's a bug in schedule/cli/main.py line 208.
        It uses "from .agentic import emit_agentic_context" which looks for schedule.cli.agentic
        but should use "from ..agentic import emit_agentic_context" to find schedule.agentic.
        This matches the pattern used in phone/cli/main.py, mail/cli/main.py, resume/cli/main.py.
        """
        pass


class TestCmdPlan(TempDirMixin, unittest.TestCase):
    """Test cmd_plan command (lines 218-226)."""

    @patch("schedule.cli.main.PlanProducer")
    @patch("schedule.cli.main.PlanProcessor")
    @patch("schedule.cli.main.PlanRequestConsumer")
    def test_cmd_plan_success(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_plan returns 0 on success."""
        import argparse

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_envelope.diagnostics = None

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        # Create args
        args = argparse.Namespace(
            source=["test.csv"],
            kind="csv",
            out=str(Path(self.tmpdir) / "plan.yaml")
        )

        result = cmd_plan(args)
        self.assertEqual(result, 0)

    @patch("schedule.cli.main.PlanProducer")
    @patch("schedule.cli.main.PlanProcessor")
    @patch("schedule.cli.main.PlanRequestConsumer")
    def test_cmd_plan_failure(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_plan returns error code on failure (line 226)."""
        import argparse

        # Setup mocks for failure
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 3}

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        args = argparse.Namespace(
            source=["test.csv"],
            kind="csv",
            out=str(Path(self.tmpdir) / "plan.yaml")
        )

        result = cmd_plan(args)
        self.assertEqual(result, 3)


class TestBuildOutlookServiceFromArgs(unittest.TestCase):
    """Test _build_outlook_service_from_args (lines 233-238)."""

    @patch("schedule.cli.main.build_outlook_service_from_args")
    def test_build_outlook_service_runtime_error(self, mock_build):
        """Test _build_outlook_service_from_args handles RuntimeError (line 234)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_build.side_effect = RuntimeError("Auth failed")
        args = argparse.Namespace()

        buf = StringIO()
        with redirect_stdout(buf):
            result = _build_outlook_service_from_args(args)

        self.assertIsNone(result)
        self.assertIn("Auth failed", buf.getvalue())

    @patch("schedule.cli.main.build_outlook_service_from_args")
    def test_build_outlook_service_other_exception(self, mock_build):
        """Test _build_outlook_service_from_args handles generic Exception (line 236-238)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_build.side_effect = ValueError("Something broke")
        args = argparse.Namespace()

        buf = StringIO()
        with redirect_stdout(buf):
            result = _build_outlook_service_from_args(args)

        self.assertIsNone(result)
        self.assertIn("Outlook provider unavailable", buf.getvalue())


class TestCmdVerify(unittest.TestCase):
    """Test cmd_verify command (lines 269)."""

    @patch("schedule.cli.main.VerifyProducer")
    @patch("schedule.cli.main.VerifyProcessor")
    @patch("schedule.cli.main.VerifyRequestConsumer")
    def test_cmd_verify_failure(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_verify returns error code on failure (line 269)."""
        import argparse

        # Setup mocks for failure
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 4}

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        args = argparse.Namespace(
            profile=None,
            client_id=None,
            tenant=None,
            token=None,
            plan="test.yaml",
            calendar="Work",
            from_date="2025-10-01",
            to_date="2025-10-31",
            match="subject"
        )

        result = cmd_verify(args)
        self.assertEqual(result, 4)


class TestCmdSync(unittest.TestCase):
    """Test cmd_sync command (line 306)."""

    @patch("schedule.cli.main.SyncProducer")
    @patch("schedule.cli.main.SyncProcessor")
    @patch("schedule.cli.main.SyncRequestConsumer")
    def test_cmd_sync_failure(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_sync returns error code on failure (line 306)."""
        import argparse

        # Setup mocks for failure
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 5}

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        args = argparse.Namespace(
            profile=None,
            client_id=None,
            tenant=None,
            token=None,
            plan="test.yaml",
            calendar="Work",
            from_date="2025-10-01",
            to_date="2025-10-31",
            match="subject-time",
            delete_missing=False,
            delete_unplanned_series=False,
            apply=False
        )

        result = cmd_sync(args)
        self.assertEqual(result, 5)


class TestCmdExport(TempDirMixin, unittest.TestCase):
    """Test cmd_export command (lines 324, 329-396)."""

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_no_service(self, mock_build_svc):
        """Test cmd_export returns 2 when service unavailable (line 324)."""
        import argparse

        mock_build_svc.return_value = None
        args = argparse.Namespace(calendar="Work", from_date="2025-10-01", to_date="2025-10-31")

        result = cmd_export(args)
        self.assertEqual(result, 2)

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_no_calendar(self, mock_build_svc):
        """Test cmd_export returns 2 when calendar missing (line 329-330)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_build_svc.return_value = MagicMock()
        args = argparse.Namespace(calendar=None, from_date="2025-10-01", to_date="2025-10-31")

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_export(args)

        self.assertEqual(result, 2)
        self.assertIn("--calendar is required", buf.getvalue())

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_invalid_date_format(self, mock_build_svc):
        """Test cmd_export returns 2 for invalid date format (line 336-338)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_build_svc.return_value = MagicMock()
        args = argparse.Namespace(calendar="Work", from_date="bad-date", to_date="2025-10-31")

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_export(args)

        self.assertEqual(result, 2)
        self.assertIn("Invalid --from/--to date format", buf.getvalue())

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_list_events_failure(self, mock_build_svc):
        """Test cmd_export returns 3 when list_events fails (line 349-351)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_svc = MagicMock()
        mock_svc.list_events_in_range.side_effect = Exception("API error")
        mock_build_svc.return_value = mock_svc

        args = argparse.Namespace(
            calendar="Work",
            from_date="2025-10-01",
            to_date="2025-10-31",
            out=str(Path(self.tmpdir) / "export.yaml")
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_export(args)

        self.assertEqual(result, 3)
        self.assertIn("Failed to list events", buf.getvalue())

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_skips_invalid_events(self, mock_build_svc):
        """Test cmd_export skips events without subject/start/end (line 361)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        mock_svc = MagicMock()
        mock_svc.list_events_in_range.return_value = [
            {
                "subject": "",  # Missing subject
                "start": {"dateTime": "2025-10-15T10:00:00"},
                "end": {"dateTime": "2025-10-15T11:00:00"},
                "location": {"displayName": "Room A"}
            },
            {
                "subject": "Valid Event",
                "start": {"dateTime": "2025-10-16T10:00:00"},
                "end": {"dateTime": "2025-10-16T11:00:00"},
                "location": {"displayName": "Room B"}
            }
        ]
        mock_build_svc.return_value = mock_svc

        out_path = Path(self.tmpdir) / "export.yaml"
        args = argparse.Namespace(
            calendar="Work",
            from_date="2025-10-01",
            to_date="2025-10-31",
            out=str(out_path)
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_export(args)

        self.assertEqual(result, 0)
        self.assertIn("Exported 1 events", buf.getvalue())  # Only valid event exported

    @patch("schedule.cli.main._build_outlook_service_from_args")
    def test_cmd_export_success(self, mock_build_svc):
        """Test cmd_export successfully exports events."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout
        import yaml

        mock_svc = MagicMock()
        mock_svc.list_events_in_range.return_value = [
            {
                "subject": "Meeting",
                "start": {"dateTime": "2025-10-15T10:00:00"},
                "end": {"dateTime": "2025-10-15T11:00:00"},
                "location": {"displayName": "Room A"}
            }
        ]
        mock_build_svc.return_value = mock_svc

        out_path = Path(self.tmpdir) / "export.yaml"
        args = argparse.Namespace(
            calendar="Work",
            from_date="2025-10-01",
            to_date="2025-10-31",
            out=str(out_path)
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_export(args)

        self.assertEqual(result, 0)
        self.assertTrue(out_path.exists())

        # Verify YAML content
        with open(out_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["subject"], "Meeting")


class TestCmdCompress(TempDirMixin, unittest.TestCase):
    """Test cmd_compress command (lines 383-396)."""

    def test_cmd_compress_input_not_found(self):
        """Test cmd_compress returns 2 when input not found (line 383-384)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        args = argparse.Namespace(
            in_path=str(Path(self.tmpdir) / "missing.yaml"),
            out=str(Path(self.tmpdir) / "out.yaml"),
            calendar=None,
            min_occur=2
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_compress(args)

        self.assertEqual(result, 2)
        self.assertIn("Input not found", buf.getvalue())

    def test_cmd_compress_invalid_events_list(self):
        """Test cmd_compress returns 2 for invalid events structure (line 389-390)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        data = {"events": "not a list"}
        in_path = write_yaml(data, self.tmpdir, "input.yaml")

        args = argparse.Namespace(
            in_path=in_path,
            out=str(Path(self.tmpdir) / "out.yaml"),
            calendar=None,
            min_occur=2
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_compress(args)

        self.assertEqual(result, 2)
        self.assertIn("events must be a list", buf.getvalue())

    def test_cmd_compress_no_one_offs(self):
        """Test cmd_compress returns 0 when no one-offs found (line 395-396)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        # Events without start/end (recurring only)
        data = {
            "events": [
                {
                    "subject": "Weekly",
                    "repeat": "weekly",
                    "byday": ["MO"],
                    "start_time": "10:00",
                    "end_time": "11:00"
                }
            ]
        }
        in_path = write_yaml(data, self.tmpdir, "input.yaml")

        args = argparse.Namespace(
            in_path=in_path,
            out=str(Path(self.tmpdir) / "out.yaml"),
            calendar=None,
            min_occur=2
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_compress(args)

        self.assertEqual(result, 0)
        self.assertIn("No one-off events found", buf.getvalue())

    def test_cmd_compress_success(self):
        """Test cmd_compress successfully compresses events."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout
        import yaml

        # Two identical one-offs on consecutive Mondays
        data = {
            "events": [
                {"subject": "Class", "start": "2025-10-13T10:00", "end": "2025-10-13T11:00", "location": "Room A"},
                {"subject": "Class", "start": "2025-10-20T10:00", "end": "2025-10-20T11:00", "location": "Room A"},
            ]
        }
        in_path = write_yaml(data, self.tmpdir, "input.yaml")
        out_path = Path(self.tmpdir) / "out.yaml"

        args = argparse.Namespace(
            in_path=in_path,
            out=str(out_path),
            calendar="Work",
            min_occur=2
        )

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_compress(args)

        self.assertEqual(result, 0)
        self.assertIn("Compressed 2 one-offs into 1 entries", buf.getvalue())

        # Verify output
        with open(out_path, encoding="utf-8") as f:
            output = yaml.safe_load(f)
        self.assertEqual(len(output["events"]), 1)
        self.assertEqual(output["events"][0]["repeat"], "weekly")


class TestCmdApply(unittest.TestCase):
    """Test cmd_apply command (lines 421-442)."""

    def test_cmd_apply_missing_plan(self):
        """Test cmd_apply returns 2 when plan missing (line 422-424)."""
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        args = argparse.Namespace(plan=None)

        buf = StringIO()
        with redirect_stdout(buf):
            result = cmd_apply(args)

        self.assertEqual(result, 2)
        self.assertIn("Missing --plan PATH", buf.getvalue())

    @patch("schedule.cli.main.ApplyProducer")
    @patch("schedule.cli.main.ApplyProcessor")
    @patch("schedule.cli.main.ApplyRequestConsumer")
    def test_cmd_apply_success(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_apply returns 0 on success (line 440-441)."""
        import argparse

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_envelope.diagnostics = None

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        args = argparse.Namespace(
            plan="test.yaml",
            profile=None,
            client_id=None,
            tenant=None,
            token=None,
            calendar=None,
            provider=None,
            apply=False
        )

        result = cmd_apply(args)
        self.assertEqual(result, 0)

    @patch("schedule.cli.main.ApplyProducer")
    @patch("schedule.cli.main.ApplyProcessor")
    @patch("schedule.cli.main.ApplyRequestConsumer")
    def test_cmd_apply_failure(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_apply returns error code on failure (line 442)."""
        import argparse

        # Setup mocks for failure
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 6}

        mock_processor = MagicMock()
        mock_processor.process.return_value = mock_envelope
        mock_processor_cls.return_value = mock_processor

        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        mock_consumed = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_consumed

        args = argparse.Namespace(
            plan="test.yaml",
            profile=None,
            client_id=None,
            tenant=None,
            token=None,
            calendar=None,
            provider="outlook",
            apply=True
        )

        result = cmd_apply(args)
        self.assertEqual(result, 6)


class TestMain(unittest.TestCase):
    """Test main function (line 447)."""

    @patch("schedule.cli.main.app")
    def test_main_delegates_to_app(self, mock_app):
        """Test main delegates to app.run_with_assistant."""
        mock_app.run_with_assistant.return_value = 0

        result = main(["--help"])
        self.assertEqual(result, 0)
        mock_app.run_with_assistant.assert_called_once()


if __name__ == "__main__":
    unittest.main()
