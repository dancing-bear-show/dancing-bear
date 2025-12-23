import datetime as dt
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from core.pipeline import ResultEnvelope
from schedule.pipeline import (
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    PlanResult,
    _norm_dt_minute,
    _to_iso_str,
    _weekday_code_to_py,
    _to_date,
    _to_datetime,
    _parse_exdates,
    _load_plan_events,
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
