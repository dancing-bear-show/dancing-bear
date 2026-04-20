"""Additional tests for schedule/cli/main.py covering previously uncovered lines."""
from __future__ import annotations

import datetime as dt
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class TestIsoToDate(unittest.TestCase):
    def test_date_only(self):
        from schedule.cli.main import _iso_to_date

        result = _iso_to_date("2025-01-15")
        self.assertEqual(result, dt.date(2025, 1, 15))

    def test_datetime_string(self):
        from schedule.cli.main import _iso_to_date

        result = _iso_to_date("2025-01-15T10:30:00")
        self.assertEqual(result, dt.date(2025, 1, 15))

    def test_datetime_with_space(self):
        from schedule.cli.main import _iso_to_date

        result = _iso_to_date("2025-01-15 10:30:00")
        self.assertEqual(result, dt.date(2025, 1, 15))

    def test_with_z_suffix(self):
        from schedule.cli.main import _iso_to_date

        result = _iso_to_date("2025-01-15T10:30:00Z")
        self.assertEqual(result, dt.date(2025, 1, 15))


class TestIsoToTime(unittest.TestCase):
    def test_datetime_string(self):
        from schedule.cli.main import _iso_to_time

        result = _iso_to_time("2025-01-15T10:30:00")
        self.assertEqual(result, "10:30")

    def test_date_only_returns_partial_date(self):
        from schedule.cli.main import _iso_to_time

        result = _iso_to_time("2025-01-15")
        # When no T or space, returns first 5 chars of date string
        self.assertEqual(result, "2025-")

    def test_datetime_with_space(self):
        from schedule.cli.main import _iso_to_time

        result = _iso_to_time("2025-01-15 14:00:00")
        self.assertEqual(result, "14:00")


class TestWeekdayCode(unittest.TestCase):
    def test_monday(self):
        from schedule.cli.main import _weekday_code

        result = _weekday_code(dt.date(2025, 1, 13))  # Monday
        self.assertEqual(result, "MO")

    def test_friday(self):
        from schedule.cli.main import _weekday_code

        result = _weekday_code(dt.date(2025, 1, 17))  # Friday
        self.assertEqual(result, "FR")

    def test_sunday(self):
        from schedule.cli.main import _weekday_code

        result = _weekday_code(dt.date(2025, 1, 19))  # Sunday
        self.assertEqual(result, "SU")


class TestGroupOneOffs(unittest.TestCase):
    def test_groups_by_subject_time(self):
        from schedule.cli.main import _group_one_offs

        events = [
            {"subject": "Yoga", "start": "2025-01-13T18:00:00", "end": "2025-01-13T19:00:00"},
            {"subject": "Yoga", "start": "2025-01-20T18:00:00", "end": "2025-01-20T19:00:00"},
            {"subject": "Meeting", "start": "2025-01-14T10:00:00", "end": "2025-01-14T11:00:00"},
        ]
        groups, _meta = _group_one_offs(events)
        self.assertEqual(len(groups), 2)

    def test_skips_events_without_subject(self):
        from schedule.cli.main import _group_one_offs

        events = [
            {"start": "2025-01-13T10:00:00", "end": "2025-01-13T11:00:00"},
        ]
        groups, _meta = _group_one_offs(events)
        self.assertEqual(len(groups), 0)

    def test_groups_include_location(self):
        from schedule.cli.main import _group_one_offs

        events = [
            {"subject": "Yoga", "start": "2025-01-13T18:00:00", "end": "2025-01-13T19:00:00", "location": "Studio"},
            {"subject": "Yoga", "start": "2025-01-20T18:00:00", "end": "2025-01-20T19:00:00", "location": "Studio"},
        ]
        groups, _meta = _group_one_offs(events)
        key = list(groups.keys())[0]
        self.assertEqual(key[4], "Studio")  # location in tuple


class TestComputeExdates(unittest.TestCase):
    def test_no_exdates_when_all_present(self):
        from schedule.cli.main import _compute_exdates

        start = dt.date(2025, 1, 6)
        end = dt.date(2025, 1, 20)  # Monday Jan 6, 13, 20
        dates = [start, dt.date(2025, 1, 13), end]
        result = _compute_exdates(dates, start, end)
        self.assertEqual(result, [])

    def test_computes_missing_weeks(self):
        from schedule.cli.main import _compute_exdates

        start = dt.date(2025, 1, 6)
        end = dt.date(2025, 1, 20)
        dates = [start, end]  # Missing Jan 13
        result = _compute_exdates(dates, start, end)
        self.assertEqual(len(result), 1)
        self.assertIn("2025-01-13", result)


class TestBuildOneOffEvent(unittest.TestCase):
    def test_basic_event(self):
        from schedule.cli.main import _build_one_off_event

        result = _build_one_off_event("Yoga", "18:00", "19:00", dt.date(2025, 1, 13), "", None)
        self.assertEqual(result["subject"], "Yoga")
        self.assertEqual(result["start"], "2025-01-13T18:00")

    def test_with_location(self):
        from schedule.cli.main import _build_one_off_event

        result = _build_one_off_event("Yoga", "18:00", "19:00", dt.date(2025, 1, 13), "Studio", None)
        self.assertEqual(result["location"], "Studio")

    def test_with_calendar(self):
        from schedule.cli.main import _build_one_off_event

        result = _build_one_off_event("Yoga", "18:00", "19:00", dt.date(2025, 1, 13), "", "Health")
        self.assertEqual(result["calendar"], "Health")

    def test_no_location_or_cal(self):
        from schedule.cli.main import _build_one_off_event

        result = _build_one_off_event("Yoga", "18:00", "19:00", dt.date(2025, 1, 13), "", None)
        self.assertNotIn("location", result)
        self.assertNotIn("calendar", result)


class TestBuildSeriesEvent(unittest.TestCase):
    def test_basic_series(self):
        from schedule.cli.main import _build_series_event

        result = _build_series_event(
            "Yoga", "18:00", "19:00", "MO", "",
            dt.date(2025, 1, 6), dt.date(2025, 1, 27), [], None
        )
        self.assertEqual(result["subject"], "Yoga")
        self.assertEqual(result["repeat"], "weekly")
        self.assertEqual(result["byday"], ["MO"])

    def test_with_exdates(self):
        from schedule.cli.main import _build_series_event

        result = _build_series_event(
            "Yoga", "18:00", "19:00", "MO", "",
            dt.date(2025, 1, 6), dt.date(2025, 1, 27), ["2025-01-13"], None
        )
        self.assertEqual(result["exdates"], ["2025-01-13"])

    def test_no_exdates_not_in_result(self):
        from schedule.cli.main import _build_series_event

        result = _build_series_event(
            "Yoga", "18:00", "19:00", "MO", "",
            dt.date(2025, 1, 6), dt.date(2025, 1, 27), [], None
        )
        self.assertNotIn("exdates", result)


class TestCompressEvents(unittest.TestCase):
    def test_compresses_to_series(self):
        from schedule.cli.main import _compress_events

        groups = {
            ("Yoga", "18:00", "19:00", "MO", ""): [
                dt.date(2025, 1, 6), dt.date(2025, 1, 13), dt.date(2025, 1, 20)
            ]
        }
        meta = {("Yoga", "18:00", "19:00", "MO", ""): {"calendar": "Health", "subject": "Yoga", "location": ""}}
        result = _compress_events(groups, meta, min_occur=2, override_cal=None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["repeat"], "weekly")

    def test_keeps_as_oneoffs_below_threshold(self):
        from schedule.cli.main import _compress_events

        groups = {
            ("Yoga", "18:00", "19:00", "MO", ""): [dt.date(2025, 1, 6)]
        }
        meta = {("Yoga", "18:00", "19:00", "MO", ""): {"calendar": None, "subject": "Yoga", "location": ""}}
        result = _compress_events(groups, meta, min_occur=2, override_cal=None)
        self.assertEqual(len(result), 1)
        self.assertNotIn("repeat", result[0])

    def test_override_calendar(self):
        from schedule.cli.main import _compress_events

        groups = {
            ("Yoga", "18:00", "19:00", "MO", ""): [
                dt.date(2025, 1, 6), dt.date(2025, 1, 13)
            ]
        }
        meta = {("Yoga", "18:00", "19:00", "MO", ""): {"calendar": "OldCal", "subject": "Yoga", "location": ""}}
        result = _compress_events(groups, meta, min_occur=2, override_cal="NewCal")
        self.assertEqual(result[0]["calendar"], "NewCal")


class TestCompressSortKey(unittest.TestCase):
    def test_sort_key_for_series(self):
        from schedule.cli.main import _compress_sort_key

        e = {"subject": "Yoga", "repeat": "weekly", "byday": ["MO"], "range": {"start_date": "2025-01-06"}, "start_time": "18:00"}
        key = _compress_sort_key(e)
        self.assertEqual(key[0], "Yoga")
        self.assertEqual(key[1], "MO")

    def test_sort_key_for_oneoff(self):
        from schedule.cli.main import _compress_sort_key

        e = {"subject": "Meeting", "start": "2025-01-15T10:00"}
        key = _compress_sort_key(e)
        self.assertEqual(key[0], "Meeting")
        self.assertEqual(key[2], "2025-01-15T10:00")


class TestCmdCompress(unittest.TestCase):
    def test_compress_from_yaml(self):
        from schedule.cli.main import cmd_compress
        import argparse

        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            in_path = Path(tmp) / "input.yaml"
            out_path = Path(tmp) / "output.yaml"
            in_path.write_text(
                "events:\n"
                "  - subject: Yoga\n"
                "    start: '2025-01-06T18:00:00'\n"
                "    end: '2025-01-06T19:00:00'\n"
                "  - subject: Yoga\n"
                "    start: '2025-01-13T18:00:00'\n"
                "    end: '2025-01-13T19:00:00'\n"
            )
            args = argparse.Namespace(
                in_path=str(in_path),
                out=str(out_path),
                calendar=None,
                min_occur=2,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_compress(args)
            self.assertEqual(result, 0)
            self.assertTrue(out_path.exists())
            self.assertIn("Compressed", buf.getvalue())

    def test_compress_missing_input(self):
        from schedule.cli.main import cmd_compress
        import argparse

        args = argparse.Namespace(
            in_path="/nonexistent/plan.yaml",
            out="/tmp/out.yaml",  # nosec B108 - test-only temp file, not a security concern
            calendar=None,
            min_occur=2,
        )
        result = cmd_compress(args)
        self.assertEqual(result, 2)

    def test_compress_no_oneoffs(self):
        from schedule.cli.main import cmd_compress
        import argparse

        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            in_path = Path(tmp) / "input.yaml"
            out_path = Path(tmp) / "output.yaml"
            in_path.write_text(
                "events:\n"
                "  - subject: Recurring\n"
                "    repeat: weekly\n"
                "    byday: [MO]\n"
                "    start_time: '10:00'\n"
            )
            args = argparse.Namespace(
                in_path=str(in_path),
                out=str(out_path),
                calendar=None,
                min_occur=2,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_compress(args)
            self.assertEqual(result, 0)
            self.assertIn("No one-off", buf.getvalue())


class TestCmdApplyMissingPlan(unittest.TestCase):
    def test_missing_plan_returns_2(self):
        from schedule.cli.main import cmd_apply
        import argparse

        args = argparse.Namespace(
            plan=None,
            calendar=None,
            provider=None,
            apply=False,
            profile=None,
            client_id=None,
            tenant=None,
            token=None,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = cmd_apply(args)
        self.assertEqual(result, 2)
        self.assertIn("Missing", buf.getvalue())


class TestReadYamlAndWriteYaml(unittest.TestCase):
    def test_read_write_roundtrip(self):
        from schedule.cli.main import _read_yaml, _write_yaml

        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            path = Path(tmp) / "data.yaml"
            data = {"events": [{"subject": "Test"}]}
            _write_yaml(path, data)
            self.assertTrue(path.exists())
            result = _read_yaml(path)
            self.assertEqual(result["events"][0]["subject"], "Test")

    def test_read_yaml_missing_raises(self):
        from schedule.cli.main import _read_yaml

        with self.assertRaises(FileNotFoundError):
            _read_yaml("/nonexistent/file.yaml")


if __name__ == "__main__":
    unittest.main()
