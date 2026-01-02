import datetime as dt
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from core.pipeline import ResultEnvelope
from schedule.pipeline import (
    ApplyProducer,
    ApplyResult,
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    PlanResult,
    SyncProducer,
    SyncResult,
    VerifyProducer,
    VerifyResult,
    _build_have_st_keys,
    _build_plan_st_keys,
    _build_verify_lines_subject,
    _build_verify_lines_subject_time,
    _expand_daily,
    _expand_recurring_occurrences,
    _expand_weekly,
    _key_subject_time,
    _load_plan_events,
    _make_occurrence,
    _norm_dt_minute,
    _parse_exdates,
    _to_date,
    _to_datetime,
    _to_iso_str,
    _weekday_code_to_py,
)


class SchedulePipelineTests(TestCase):
    def test_plan_processor_success(self):
        request = PlanRequest(sources=["src"], kind=None, out_path=Path("plan.yaml"))

        def fake_loader(src, kind):
            return [{"subject": "Event", "start": "2025-01-01T10:00:00", "end": "2025-01-01T11:00:00"}]

        env = PlanProcessor(loader=fake_loader).process(PlanRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)  # type: ignore[union-attr]

    def test_plan_processor_handles_error(self):
        request = PlanRequest(sources=["bad"], kind=None, out_path=Path("plan.yaml"))

        def boom(src, kind):
            raise RuntimeError("load failure")

        env = PlanProcessor(loader=boom).process(PlanRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("load failure", env.diagnostics["message"])

    def test_plan_producer_writes_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.yaml"
            payload = PlanResult(document={"events": []}, out_path=out_path)
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                PlanProducer().produce(env)
            self.assertTrue(out_path.exists())
            self.assertIn("Wrote plan", buf.getvalue())

    def test_plan_producer_handles_error_envelope(self):
        env = ResultEnvelope(status="error", diagnostics={"message": "Something went wrong"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            PlanProducer().produce(env)
        self.assertIn("Something went wrong", buf.getvalue())

    def test_plan_processor_empty_sources(self):
        request = PlanRequest(sources=[], kind=None, out_path=Path("plan.yaml"))
        env = PlanProcessor(loader=lambda s, k: []).process(request)
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])


class NormDtMinuteTests(TestCase):
    """Tests for _norm_dt_minute function."""

    def test_full_iso_datetime(self):
        result = _norm_dt_minute("2025-01-15T10:30:00")
        self.assertEqual(result, "2025-01-15T10:30")

    def test_with_z_suffix(self):
        result = _norm_dt_minute("2025-01-15T10:30:00Z")
        self.assertEqual(result, "2025-01-15T10:30")

    def test_date_only(self):
        result = _norm_dt_minute("2025-01-15")
        self.assertEqual(result, "2025-01-15T00:00")

    def test_none_returns_none(self):
        result = _norm_dt_minute(None)
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = _norm_dt_minute("")
        self.assertIsNone(result)

    def test_partial_time(self):
        result = _norm_dt_minute("2025-01-15T10:30")
        self.assertEqual(result, "2025-01-15T10:30")


class ToIsoStrTests(TestCase):
    """Tests for _to_iso_str function."""

    def test_none_returns_none(self):
        self.assertIsNone(_to_iso_str(None))

    def test_string_passthrough(self):
        self.assertEqual(_to_iso_str("2025-01-15"), "2025-01-15")

    def test_datetime_object(self):
        d = dt.datetime(2025, 1, 15, 10, 30, 45)
        result = _to_iso_str(d)
        self.assertEqual(result, "2025-01-15T10:30:45")

    def test_date_object(self):
        d = dt.date(2025, 1, 15)
        result = _to_iso_str(d)
        self.assertEqual(result, "2025-01-15T00:00:00")

    def test_other_type_str_conversion(self):
        result = _to_iso_str(12345)
        self.assertEqual(result, "12345")


class WeekdayCodeToPyTests(TestCase):
    """Tests for _weekday_code_to_py function."""

    def test_monday(self):
        self.assertEqual(_weekday_code_to_py("MO"), 0)

    def test_friday(self):
        self.assertEqual(_weekday_code_to_py("FR"), 4)

    def test_sunday(self):
        self.assertEqual(_weekday_code_to_py("SU"), 6)

    def test_lowercase(self):
        self.assertEqual(_weekday_code_to_py("mo"), 0)

    def test_invalid_returns_none(self):
        self.assertIsNone(_weekday_code_to_py("XX"))


class ToDateTests(TestCase):
    """Tests for _to_date function."""

    def test_iso_date_string(self):
        result = _to_date("2025-01-15")
        self.assertEqual(result, dt.date(2025, 1, 15))

    def test_date_object(self):
        d = dt.date(2025, 1, 15)
        result = _to_date(d)
        self.assertEqual(result, d)


class ToDatetimeTests(TestCase):
    """Tests for _to_datetime function."""

    def test_combine_date_and_time(self):
        d = dt.date(2025, 1, 15)
        result = _to_datetime(d, "10:30")
        self.assertEqual(result, dt.datetime(2025, 1, 15, 10, 30))

    def test_default_time(self):
        d = dt.date(2025, 1, 15)
        result = _to_datetime(d, None)
        self.assertEqual(result, dt.datetime(2025, 1, 15, 0, 0))


class ParseExdatesTests(TestCase):
    """Tests for _parse_exdates function."""

    def test_parse_iso_dates(self):
        result = _parse_exdates(["2025-01-15", "2025-01-22"])
        self.assertEqual(result, {"2025-01-15", "2025-01-22"})

    def test_parse_datetime_strings(self):
        result = _parse_exdates(["2025-01-15T10:00:00"])
        self.assertIn("2025-01-15", result)

    def test_empty_list(self):
        result = _parse_exdates([])
        self.assertEqual(result, set())


class LoadPlanEventsTests(TestCase):
    """Tests for _load_plan_events function."""

    def test_load_valid_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events:\n  - subject: Test\n")
            events, err = _load_plan_events(plan_path)
            self.assertIsNone(err)
            self.assertEqual(len(events), 1)

    def test_load_empty_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events: []\n")
            events, err = _load_plan_events(plan_path)
            self.assertIsNone(err)
            self.assertEqual(events, [])

    def test_load_missing_file_returns_empty(self):
        # Missing files return empty events (load_config returns {})
        events, err = _load_plan_events(Path("/nonexistent/plan.yaml"))
        self.assertIsNone(err)
        self.assertEqual(events, [])

    def test_load_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events: not-a-list\n")
            events, err = _load_plan_events(plan_path)
            self.assertIsNotNone(err)
            self.assertIn("must be a list", err)


class MakeOccurrenceTests(TestCase):
    """Tests for _make_occurrence function."""

    def test_basic_occurrence(self):
        d = dt.date(2025, 1, 15)
        start, end = _make_occurrence(d, "10:00", "11:00")
        self.assertEqual(start, "2025-01-15T10:00")
        self.assertEqual(end, "2025-01-15T11:00")

    def test_end_before_start_adds_day(self):
        # When end time is before start time, add a day
        d = dt.date(2025, 1, 15)
        start, end = _make_occurrence(d, "23:00", "01:00")
        self.assertEqual(start, "2025-01-15T23:00")
        self.assertEqual(end, "2025-01-16T01:00")

    def test_caps_duration_at_four_hours(self):
        # Events >= 4 hours are capped at 3:59
        d = dt.date(2025, 1, 15)
        start, end = _make_occurrence(d, "10:00", "15:00")
        self.assertEqual(start, "2025-01-15T10:00")
        self.assertEqual(end, "2025-01-15T13:59")


class ExpandDailyTests(TestCase):
    """Tests for _expand_daily function."""

    def test_expand_three_days(self):
        cur = dt.date(2025, 1, 15)
        end = dt.date(2025, 1, 17)
        result = _expand_daily(cur, end, "10:00", "11:00", set())
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], "2025-01-15T10:00")
        self.assertEqual(result[2][0], "2025-01-17T10:00")

    def test_excludes_exdates(self):
        cur = dt.date(2025, 1, 15)
        end = dt.date(2025, 1, 17)
        ex_set = {"2025-01-16"}
        result = _expand_daily(cur, end, "10:00", "11:00", ex_set)
        self.assertEqual(len(result), 2)
        dates = [r[0][:10] for r in result]
        self.assertNotIn("2025-01-16", dates)

    def test_single_day(self):
        cur = dt.date(2025, 1, 15)
        end = dt.date(2025, 1, 15)
        result = _expand_daily(cur, end, "09:00", "10:00", set())
        self.assertEqual(len(result), 1)


class ExpandWeeklyTests(TestCase):
    """Tests for _expand_weekly function."""

    def test_expand_mondays_and_wednesdays(self):
        from schedule.pipeline import RecurrenceExpansionConfig

        # 2025-01-13 is Monday, 2025-01-15 is Wednesday
        config = RecurrenceExpansionConfig(
            start_date=dt.date(2025, 1, 13),
            end_date=dt.date(2025, 1, 19),
            start_time="10:00",
            end_time="11:00",
            excluded_dates=set(),
            weekdays=[0, 2],  # Monday, Wednesday
        )
        result = _expand_weekly(config)
        self.assertEqual(len(result), 2)

    def test_excludes_exdates(self):
        from schedule.pipeline import RecurrenceExpansionConfig

        config = RecurrenceExpansionConfig(
            start_date=dt.date(2025, 1, 13),
            end_date=dt.date(2025, 1, 19),
            start_time="10:00",
            end_time="11:00",
            excluded_dates={"2025-01-13"},  # Exclude the Monday
            weekdays=[0, 2],  # Monday, Wednesday
        )
        result = _expand_weekly(config)
        self.assertEqual(len(result), 1)

    def test_no_matching_days(self):
        from schedule.pipeline import RecurrenceExpansionConfig

        config = RecurrenceExpansionConfig(
            start_date=dt.date(2025, 1, 14),  # Tuesday
            end_date=dt.date(2025, 1, 14),
            start_time="10:00",
            end_time="11:00",
            excluded_dates=set(),
            weekdays=[0],  # Monday only
        )
        result = _expand_weekly(config)
        self.assertEqual(len(result), 0)


class ExpandRecurringOccurrencesTests(TestCase):
    """Tests for _expand_recurring_occurrences function."""

    def test_weekly_with_byday(self):
        ev = {
            "repeat": "weekly",
            "start_time": "10:00",
            "end_time": "11:00",
            "byday": ["MO", "WE"],
            "range": {"start_date": "2025-01-13", "until": "2025-01-19"},
        }
        result = _expand_recurring_occurrences(ev, "2025-01-13", "2025-01-19")
        self.assertEqual(len(result), 2)

    def test_daily(self):
        ev = {
            "repeat": "daily",
            "start_time": "09:00",
            "end_time": "10:00",
            "range": {"start_date": "2025-01-15", "until": "2025-01-17"},
        }
        result = _expand_recurring_occurrences(ev, "2025-01-15", "2025-01-17")
        self.assertEqual(len(result), 3)

    def test_invalid_repeat_returns_empty(self):
        ev = {"repeat": "monthly", "start_time": "10:00", "end_time": "11:00"}
        result = _expand_recurring_occurrences(ev, "2025-01-01", "2025-01-31")
        self.assertEqual(result, [])

    def test_missing_start_time_returns_empty(self):
        ev = {"repeat": "daily", "range": {"start_date": "2025-01-15"}}
        result = _expand_recurring_occurrences(ev, "2025-01-15", "2025-01-17")
        self.assertEqual(result, [])

    def test_with_exdates(self):
        ev = {
            "repeat": "daily",
            "start_time": "10:00",
            "end_time": "11:00",
            "range": {"start_date": "2025-01-15", "until": "2025-01-17"},
            "exdates": ["2025-01-16"],
        }
        result = _expand_recurring_occurrences(ev, "2025-01-15", "2025-01-17")
        self.assertEqual(len(result), 2)

    def test_window_constrains_range(self):
        ev = {
            "repeat": "daily",
            "start_time": "10:00",
            "end_time": "11:00",
            "range": {"start_date": "2025-01-01", "until": "2025-01-31"},
        }
        # Window is narrower than range
        result = _expand_recurring_occurrences(ev, "2025-01-15", "2025-01-17")
        self.assertEqual(len(result), 3)


class KeySubjectTimeTests(TestCase):
    """Tests for _key_subject_time function."""

    def test_basic_key(self):
        result = _key_subject_time("Meeting", "2025-01-15T10:00:00", "2025-01-15T11:00:00")
        self.assertEqual(result, "meeting|2025-01-15T10:00|2025-01-15T11:00")

    def test_normalizes_case(self):
        result = _key_subject_time("MEETING", "2025-01-15T10:00", "2025-01-15T11:00")
        self.assertIn("meeting", result)

    def test_handles_none_times(self):
        result = _key_subject_time("Meeting", None, None)
        self.assertEqual(result, "meeting||")


class BuildHaveStKeysTests(TestCase):
    """Tests for _build_have_st_keys function."""

    def test_builds_keys_from_occurrences(self):
        occ = [
            {
                "subject": "Meeting",
                "start": {"dateTime": "2025-01-15T10:00:00"},
                "end": {"dateTime": "2025-01-15T11:00:00"},
            },
            {
                "subject": "Standup",
                "start": {"dateTime": "2025-01-15T09:00:00"},
                "end": {"dateTime": "2025-01-15T09:30:00"},
            },
        ]
        result = _build_have_st_keys(occ)
        self.assertEqual(len(result), 2)

    def test_empty_list(self):
        result = _build_have_st_keys([])
        self.assertEqual(result, set())


class BuildPlanStKeysTests(TestCase):
    """Tests for _build_plan_st_keys function."""

    def test_oneoff_events(self):
        events = [
            {"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"},
        ]
        result = _build_plan_st_keys(events, "2025-01-15", "2025-01-15")
        self.assertEqual(len(result), 1)

    def test_recurring_events(self):
        events = [
            {
                "subject": "Daily Standup",
                "repeat": "daily",
                "start_time": "09:00",
                "end_time": "09:30",
                "range": {"start_date": "2025-01-15", "until": "2025-01-17"},
            },
        ]
        result = _build_plan_st_keys(events, "2025-01-15", "2025-01-17")
        self.assertEqual(len(result), 3)

    def test_skips_events_without_subject(self):
        events = [{"start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        result = _build_plan_st_keys(events, "2025-01-15", "2025-01-15")
        self.assertEqual(len(result), 0)


class BuildVerifyLinesSubjectTimeTests(TestCase):
    """Tests for _build_verify_lines_subject_time function."""

    def test_no_missing_no_extras(self):
        from schedule.pipeline import VerifyRequest, OutlookAuth

        payload = VerifyRequest(
            plan_path=Path("plan.yaml"),
            calendar="Test",
            from_date="2025-01-15",
            to_date="2025-01-17",
            match="subject-time",
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        plan_keys = {"a|2025-01-15T10:00|2025-01-15T11:00"}
        have_keys = {"a|2025-01-15T10:00|2025-01-15T11:00"}
        lines = _build_verify_lines_subject_time(payload, plan_keys, have_keys)
        self.assertTrue(any("Missing: none" in line for line in lines))
        self.assertTrue(any("Extras not in plan: none" in line for line in lines))

    def test_with_missing(self):
        from schedule.pipeline import VerifyRequest, OutlookAuth

        payload = VerifyRequest(
            plan_path=Path("plan.yaml"),
            calendar="Test",
            from_date="2025-01-15",
            to_date="2025-01-17",
            match="subject-time",
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        plan_keys = {"a|2025-01-15T10:00|2025-01-15T11:00", "b|2025-01-16T10:00|2025-01-16T11:00"}
        have_keys = {"a|2025-01-15T10:00|2025-01-15T11:00"}
        lines = _build_verify_lines_subject_time(payload, plan_keys, have_keys)
        self.assertTrue(any("Missing (subject@time)" in line for line in lines))


class BuildVerifyLinesSubjectTests(TestCase):
    """Tests for _build_verify_lines_subject function."""

    def test_no_missing_no_extras(self):
        from schedule.pipeline import VerifyRequest, OutlookAuth

        payload = VerifyRequest(
            plan_path=Path("plan.yaml"),
            calendar="Test",
            from_date="2025-01-15",
            to_date="2025-01-17",
            match="subject",
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        events = [{"subject": "Meeting"}]
        occ = [{"subject": "Meeting"}]
        lines = _build_verify_lines_subject(payload, events, occ)
        self.assertTrue(any("Missing: none" in line for line in lines))

    def test_with_missing_subject(self):
        from schedule.pipeline import VerifyRequest, OutlookAuth

        payload = VerifyRequest(
            plan_path=Path("plan.yaml"),
            calendar="Test",
            from_date="2025-01-15",
            to_date="2025-01-17",
            match="subject",
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        events = [{"subject": "Meeting"}, {"subject": "Standup"}]
        occ = [{"subject": "Meeting"}]
        lines = _build_verify_lines_subject(payload, events, occ)
        self.assertTrue(any("Missing (by subject)" in line for line in lines))


class VerifyProducerTests(TestCase):
    """Tests for VerifyProducer."""

    def test_produce_success(self):
        payload = VerifyResult(lines=["Line 1", "Line 2"])
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            VerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Line 1", output)
        self.assertIn("Line 2", output)

    def test_produce_error(self):
        env = ResultEnvelope(status="error", diagnostics={"message": "Verify failed"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            VerifyProducer().produce(env)
        self.assertIn("Verify failed", buf.getvalue())


class SyncProducerTests(TestCase):
    """Tests for SyncProducer."""

    def test_produce_success(self):
        payload = SyncResult(lines=["Created: 5", "Deleted: 2"])
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            SyncProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Created: 5", output)
        self.assertIn("Deleted: 2", output)

    def test_produce_error(self):
        env = ResultEnvelope(status="error", diagnostics={"message": "Sync failed"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            SyncProducer().produce(env)
        self.assertIn("Sync failed", buf.getvalue())


class ApplyProducerTests(TestCase):
    """Tests for ApplyProducer."""

    def test_produce_success(self):
        payload = ApplyResult(lines=["Applied 3 events", "Done"])
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ApplyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Applied 3 events", output)

    def test_produce_error(self):
        env = ResultEnvelope(status="error", diagnostics={"message": "Apply failed"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            ApplyProducer().produce(env)
        self.assertIn("Apply failed", buf.getvalue())
