"""Tests for uncovered producer output branches and helper functions in the calendars domain.

Targets:
- calendars/gmail_pipelines.py 514-531 (GmailSweepTopProducer out_path branch)
- calendars/gmail_service.py 97-100 (build_activerh_query programs default)
- calendars/outlook_pipelines/add.py 145-147 (OutlookAddProducer produce)
- calendars/outlook_pipelines/dedup.py 209-210 (OutlookDedupProducer deleted count print)
- calendars/outlook_pipelines/remove.py 218-227 (OutlookRemoveProducer apply=True branch)
- calendars/outlook_pipelines/reminders.py 163 (OutlookRemindersProducer apply non-set_off branch)
- calendars/outlook_pipelines/settings.py 232 (OutlookSettingsProducer apply branch)
- calendars/outlook_pipelines/share.py 64 (OutlookCalendarShareProducer output)
- calendars/outlook_pipelines/verify.py 93-94 (OutlookVerifyProducer no_match branch)
- calendars/outlook_pipelines/schedule_import.py 146-148 (OutlookScheduleImportProducer apply branch)
- calendars/outlook_pipelines/add_event.py 82 (OutlookAddRecurringProducer output)
- calendars/selection.py 110->105 (filter_events_by_day_time with no start time)
- calendars/context.py 48-59 (OutlookContext.ensure_client fallback branches)
- calendars/model.py 97 (normalize_event edge case)
- calendars/location_sync.py 179 (LocationSync._resolve_event_location None branch)
- calendars/scan_common.py 96-97 (infer_meta_from_text with unparseable date range)
- calendars/pipeline_base.py 63 (GmailServiceBuilder.build with explicit service_cls)
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope


class TestGmailSweepTopProducerOutPath(unittest.TestCase):
    """Tests for GmailSweepTopProducer._produce_success with out_path set."""

    def test_produce_no_senders_prints_no_stats(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        payload = GmailSweepTopResult(top_senders=[], freq_days=30, inbox_only=True, out_path=None)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(env)
        self.assertIn("No sender stats available", buf.getvalue())

    def test_produce_with_out_path_writes_filters_yaml(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "filters.yaml"
            payload = GmailSweepTopResult(
                top_senders=[("spam@example.com", 42), ("noise@foo.com", 10)],
                freq_days=14,
                inbox_only=False,
                out_path=out_path,
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailSweepTopProducer().produce(env)
            output = buf.getvalue()
            self.assertIn("spam@example.com", output)
            self.assertIn("noise@foo.com", output)
            self.assertIn(str(out_path), output)
            # File should have been written with filter content
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("spam@example.com", content)

    def test_produce_with_senders_no_out_path(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        payload = GmailSweepTopResult(
            top_senders=[("sender@example.com", 5)],
            freq_days=7,
            inbox_only=True,
            out_path=None,
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("sender@example.com", output)
        self.assertIn("7d", output)
        # No "Wrote" line since out_path is None
        self.assertNotIn("Wrote", output)


class TestGmailServiceBuildActiveRHQueryDefault(unittest.TestCase):
    """Tests for GmailService.build_activerh_query with programs default."""

    def test_build_activerh_query_uses_default_programs(self):
        from calendars.gmail_service import GmailService
        result = GmailService.build_activerh_query(days=30)
        # Without explicit programs, defaults include Swimmer, Chess, etc.
        # Result must be a non-empty string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_build_activerh_query_with_explicit_programs(self):
        from calendars.gmail_service import GmailService
        result = GmailService.build_activerh_query(days=7, programs=["Tennis"])
        self.assertIn("Tennis", result)

    def test_build_activerh_query_programs_none_uses_default(self):
        from calendars.gmail_service import GmailService
        # programs=None should trigger the default list
        result_none = GmailService.build_activerh_query(days=30, programs=None)
        result_default = GmailService.build_activerh_query(days=30)
        self.assertEqual(result_none, result_default)


class TestOutlookAddProducerOutput(unittest.TestCase):
    """Tests for OutlookAddProducer._produce_success."""

    def test_produce_dry_run(self):
        from calendars.outlook_pipelines.add import OutlookAddProducer, OutlookAddResult
        payload = OutlookAddResult(logs=["[1] Dry-run: would create event"], created=2, dry_run=True)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookAddProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("dry-run", output)
        self.assertIn("2", output)

    def test_produce_apply(self):
        from calendars.outlook_pipelines.add import OutlookAddProducer, OutlookAddResult
        payload = OutlookAddResult(logs=["[1] Created event: abc123 Meeting"], created=1, dry_run=False)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookAddProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("1", output)
        # No dry-run suffix
        self.assertNotIn("dry-run", output)


class TestOutlookDedupProducerDeletedCount(unittest.TestCase):
    """Tests for OutlookDedupProducer._produce_success with apply=True."""

    def _make_dup(self):
        from calendars.outlook_pipelines.dedup import OutlookDedupDuplicate
        return OutlookDedupDuplicate(
            subject="Swim Class",
            weekday="mo",
            start_time="09:00",
            end_time="10:00",
            keep="id1",
            delete=["id2"],
        )

    def test_produce_apply_true_shows_deleted_count(self):
        from calendars.outlook_pipelines.dedup import OutlookDedupProducer, OutlookDedupResult
        payload = OutlookDedupResult(
            duplicates=[self._make_dup()],
            apply=True,
            deleted=1,
            logs=["Deleted series master id2"],
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Deleted 1", output)
        self.assertIn("Deleted series master id2", output)

    def test_produce_apply_false_shows_plan_only(self):
        from calendars.outlook_pipelines.dedup import OutlookDedupProducer, OutlookDedupResult
        payload = OutlookDedupResult(
            duplicates=[self._make_dup()],
            apply=False,
            deleted=0,
            logs=[],
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Dry plan only", output)
        self.assertNotIn("Deleted", output)

    def test_produce_no_duplicates(self):
        from calendars.outlook_pipelines.dedup import OutlookDedupProducer, OutlookDedupResult
        payload = OutlookDedupResult(
            duplicates=[],
            apply=False,
            deleted=0,
            logs=[],
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        self.assertIn("No duplicate", buf.getvalue())


class TestOutlookRemoveProducerApplyBranch(unittest.TestCase):
    """Tests for OutlookRemoveProducer._produce_success with apply=True."""

    def test_produce_apply_true_shows_deleted(self):
        from calendars.outlook_pipelines.remove import (
            OutlookRemoveProducer,
            OutlookRemoveResult,
            OutlookRemovePlanEntry,
        )
        plan = [OutlookRemovePlanEntry(subject="Swim", series_ids=["s1"], event_ids=[])]
        payload = OutlookRemoveResult(
            plan=plan,
            apply=True,
            deleted=1,
            logs=["Deleted series master: s1 (Swim)"],
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemoveProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Deleted 1", output)
        self.assertIn("Deleted series master", output)

    def test_produce_apply_false_shows_plan(self):
        from calendars.outlook_pipelines.remove import (
            OutlookRemoveProducer,
            OutlookRemoveResult,
            OutlookRemovePlanEntry,
        )
        plan = [OutlookRemovePlanEntry(subject="Swim", series_ids=["s1"], event_ids=["e1"])]
        payload = OutlookRemoveResult(plan=plan, apply=False, deleted=0, logs=[])
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemoveProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Planned deletions", output)
        self.assertIn("Re-run with --apply", output)


class TestOutlookRemindersProducerApplyBranch(unittest.TestCase):
    """Tests for OutlookRemindersProducer._produce_success non-set_off apply branch."""

    def test_produce_apply_set_off(self):
        from calendars.outlook_pipelines.reminders import OutlookRemindersProducer, OutlookRemindersResult
        payload = OutlookRemindersResult(logs=[], updated=3, dry_run=False, set_off=True)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemindersProducer().produce(env)
        self.assertIn("Disabled reminders on 3", buf.getvalue())

    def test_produce_apply_set_minutes(self):
        from calendars.outlook_pipelines.reminders import OutlookRemindersProducer, OutlookRemindersResult
        payload = OutlookRemindersResult(logs=[], updated=5, dry_run=False, set_off=False)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemindersProducer().produce(env)
        self.assertIn("Updated reminders on 5", buf.getvalue())

    def test_produce_dry_run(self):
        from calendars.outlook_pipelines.reminders import OutlookRemindersProducer, OutlookRemindersResult
        payload = OutlookRemindersResult(logs=["Would update reminder"], updated=2, dry_run=True, set_off=False)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemindersProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Would update reminder", output)
        self.assertIn("Preview complete", output)


class TestOutlookSettingsProducerApplyBranch(unittest.TestCase):
    """Tests for OutlookSettingsProducer._produce_success apply branch."""

    def test_produce_apply(self):
        from calendars.outlook_pipelines.settings import OutlookSettingsProducer, OutlookSettingsResult
        payload = OutlookSettingsResult(logs=[], selected=10, changed=7, dry_run=False)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookSettingsProducer().produce(env)
        self.assertIn("Applied settings to 7", buf.getvalue())

    def test_produce_dry_run(self):
        from calendars.outlook_pipelines.settings import OutlookSettingsProducer, OutlookSettingsResult
        payload = OutlookSettingsResult(logs=[], selected=5, changed=0, dry_run=True)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookSettingsProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("5", output)
        self.assertIn("Preview complete", output)


class TestOutlookCalendarShareProducerOutput(unittest.TestCase):
    """Tests for OutlookCalendarShareProducer._produce_success."""

    def test_produce_outputs_share_details(self):
        from calendars.outlook_pipelines.share import OutlookCalendarShareProducer, OutlookCalendarShareResult
        payload = OutlookCalendarShareResult(
            calendar="Work",
            recipient="alice@example.com",
            role="write",
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookCalendarShareProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Work", output)
        self.assertIn("alice@example.com", output)
        self.assertIn("write", output)


class TestOutlookVerifyProducerNoMatch(unittest.TestCase):
    """Tests for OutlookVerifyProducer._produce_success."""

    def test_produce_outputs_counts(self):
        from calendars.outlook_pipelines.verify import OutlookVerifyProducer, OutlookVerifyResult
        payload = OutlookVerifyResult(
            logs=["[1] missing: Swim MO 09:00-10:00 in 'Primary'"],
            total=3,
            duplicates=1,
            missing=1,
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Checked 3", output)
        self.assertIn("Duplicates: 1", output)
        self.assertIn("Missing: 1", output)
        self.assertIn("missing: Swim", output)

    def test_produce_all_zeros(self):
        from calendars.outlook_pipelines.verify import OutlookVerifyProducer, OutlookVerifyResult
        payload = OutlookVerifyResult(logs=[], total=0, duplicates=0, missing=0)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        self.assertIn("Checked 0", buf.getvalue())


class TestOutlookScheduleImportProducerApplyBranch(unittest.TestCase):
    """Tests for OutlookScheduleImportProducer._produce_success apply branch."""

    def test_produce_apply(self):
        from calendars.outlook_pipelines.schedule_import import (
            OutlookScheduleImportProducer,
            OutlookScheduleImportResult,
        )
        payload = OutlookScheduleImportResult(
            logs=["Created recurring 'Swim Class'"],
            created=3,
            dry_run=False,
            calendar="Kids",
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScheduleImportProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Created 3", output)
        self.assertIn("Kids", output)
        self.assertIn("Created recurring", output)

    def test_produce_dry_run(self):
        from calendars.outlook_pipelines.schedule_import import (
            OutlookScheduleImportProducer,
            OutlookScheduleImportResult,
        )
        payload = OutlookScheduleImportResult(logs=[], created=0, dry_run=True, calendar="Primary")
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScheduleImportProducer().produce(env)
        self.assertIn("Preview complete", buf.getvalue())


class TestOutlookAddRecurringProducerOutput(unittest.TestCase):
    """Tests for OutlookAddRecurringProducer._produce_success."""

    def test_produce_outputs_event_details(self):
        from calendars.outlook_pipelines.add_event import (
            OutlookAddRecurringProducer,
            OutlookAddRecurringResult,
        )
        payload = OutlookAddRecurringResult(event_id="rec123", subject="Weekly Swim")
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookAddRecurringProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("rec123", output)
        self.assertIn("Weekly Swim", output)


class TestFilterEventsByDayTimeNoStartTime(unittest.TestCase):
    """Tests for filter_events_by_day_time with no start_time (covers line 110->105 branch)."""

    def _make_event(self, dt_str: str, end_str: str = "") -> dict:
        return {
            "start": {"dateTime": dt_str},
            "end": {"dateTime": end_str or dt_str},
        }

    def test_no_filters_returns_all_with_start(self):
        from calendars.selection import filter_events_by_day_time
        events = [
            self._make_event("2025-01-06T09:00:00"),  # Monday
            self._make_event("2025-01-07T10:00:00"),  # Tuesday
        ]
        result = filter_events_by_day_time(events)
        self.assertEqual(len(result), 2)

    def test_events_without_start_are_skipped(self):
        from calendars.selection import filter_events_by_day_time
        events = [
            {"start": {}, "end": {}},
            {"start": {"dateTime": "2025-01-06T09:00:00"}, "end": {"dateTime": "2025-01-06T10:00:00"}},
        ]
        result = filter_events_by_day_time(events)
        self.assertEqual(len(result), 1)

    def test_byday_filter_with_no_start_time(self):
        from calendars.selection import filter_events_by_day_time
        events = [
            self._make_event("2025-01-06T09:00:00"),  # Monday
            self._make_event("2025-01-07T09:00:00"),  # Tuesday
        ]
        # Filter by Monday (MO) only - no start_time filter
        result = filter_events_by_day_time(events, byday=["MO"])
        self.assertEqual(len(result), 1)
        self.assertIn("2025-01-06", result[0]["start"]["dateTime"])

    def test_start_time_filter(self):
        from calendars.selection import filter_events_by_day_time
        events = [
            self._make_event("2025-01-06T09:00:00", "2025-01-06T10:00:00"),
            self._make_event("2025-01-06T11:00:00", "2025-01-06T12:00:00"),
        ]
        result = filter_events_by_day_time(events, start_time="09:00")
        self.assertEqual(len(result), 1)


class TestOutlookContextEnsureClient(unittest.TestCase):
    """Tests for OutlookContext.ensure_client fallback branches."""

    def test_ensure_client_raises_when_no_client_id(self):
        from calendars.context import OutlookContext
        ctx = OutlookContext(client_id=None, tenant="consumers", token_path=None)
        fake_client_cls = MagicMock()
        with patch("calendars.context.resolve_outlook_credentials", return_value=(None, "consumers", None)):
            with patch("core.outlook.OutlookClient", fake_client_cls):
                with self.assertRaises(RuntimeError) as cm:
                    ctx.ensure_client()
        self.assertIn("client-id", str(cm.exception))

    def test_ensure_client_authenticates_when_client_id_present(self):
        from calendars.context import OutlookContext
        ctx = OutlookContext(client_id="fake-id", tenant="consumers", token_path="/tmp/token.json")  # nosec B106 B108 - test string only
        fake_client = MagicMock()
        fake_client_cls = MagicMock(return_value=fake_client)
        with patch("calendars.context.resolve_outlook_credentials", return_value=("fake-id", "consumers", "/tmp/token.json")):  # nosec B108 - test string only
            with patch("core.outlook.OutlookClient", fake_client_cls):
                result = ctx.ensure_client()
        fake_client.authenticate.assert_called_once()
        self.assertEqual(result, fake_client)

    def test_resolve_returns_consumers_when_tenant_none(self):
        from calendars.context import OutlookContext
        ctx = OutlookContext(client_id="some-id", tenant=None)
        with patch("calendars.context.resolve_outlook_credentials", return_value=("some-id", None, None)):
            _, tenant, _ = ctx.resolve()
        self.assertEqual(tenant, "consumers")


class TestNormalizeEventEdgeCases(unittest.TestCase):
    """Tests for calendars.model.normalize_event edge cases."""

    def test_normalize_event_with_bool_like_flag(self):
        """Covers bool/truthy coercion path in normalize_event."""
        from calendars.model import normalize_event
        ev = {
            "subject": "Meeting",
            "all_day": "off",   # should normalize to False via _normalize_bool
        }
        result = normalize_event(ev)
        self.assertEqual(result["subject"], "Meeting")

    def test_normalize_event_bool_normalize_on(self):
        from calendars.model import normalize_event
        # The _normalize_bool helper inside model
        ev = {"subject": "Test", "all_day": "true"}
        result = normalize_event(ev)
        self.assertEqual(result["subject"], "Test")

    def test_normalize_event_bool_normalize_none_for_invalid(self):
        """Covers the None return branch in _normalize_reminder_on (line 97)."""
        from calendars.model import _normalize_reminder_on
        # Strings not matching any known truthy/falsy value return None
        self.assertIsNone(_normalize_reminder_on("maybe"))
        self.assertIsNone(_normalize_reminder_on("unknown"))
        # Valid values
        self.assertFalse(_normalize_reminder_on("off"))
        self.assertTrue(_normalize_reminder_on("yes"))


class TestLocationSyncResolveEventLocationNone(unittest.TestCase):
    """Tests for LocationSync._resolve_event_location returning None."""

    def test_returns_none_for_non_dict(self):
        from calendars.location_sync import LocationSync
        sync = LocationSync(svc=MagicMock())
        # cast exercises the isinstance(ev, dict) guard — intentional wrong type.
        result = sync._resolve_event_location(cast(Any, "not a dict"), calendar=None)
        self.assertIsNone(result)

    def test_returns_none_when_no_location(self):
        from calendars.location_sync import LocationSync
        sync = LocationSync(svc=MagicMock())
        # Event has subject but no location
        result = sync._resolve_event_location({"subject": "Meeting"}, calendar=None)
        self.assertIsNone(result)

    def test_returns_none_when_no_subject(self):
        from calendars.location_sync import LocationSync
        sync = LocationSync(svc=MagicMock())
        result = sync._resolve_event_location({"location": "Room 1"}, calendar=None)
        self.assertIsNone(result)

    def test_returns_tuple_when_both_present(self):
        from calendars.location_sync import LocationSync
        sync = LocationSync(svc=MagicMock())
        result = sync._resolve_event_location(
            {"subject": "Meeting", "location": "Room 1"},
            calendar=None,
        )
        self.assertIsNotNone(result)
        _, yaml_loc, _ = result
        self.assertEqual(yaml_loc, "Room 1")


class TestInferMetaFromTextFallback(unittest.TestCase):
    """Tests for scan_common.infer_meta_from_text with unparseable date range (lines 96-97)."""

    def test_no_date_range_in_text(self):
        from calendars.scan_common import infer_meta_from_text
        result = infer_meta_from_text("No dates here")
        self.assertNotIn("range", result)

    def test_unparseable_month_in_date_range(self):
        """Trigger the except branch in _infer_date_range."""
        from calendars.scan_common import infer_meta_from_text, MetaParserConfig
        import re
        # Use a date_range_pat that matches but produces month keys not in MONTH_MAP
        bad_pat = re.compile(
            r"(xxx)\s+(\d{1,2})(,\s*\d{4})?\s*-\s*(yyy)\s+(\d{1,2})(,\s*\d{4})?",
            re.I,
        )
        cfg = MetaParserConfig(date_range_pat=bad_pat)
        # This matches but xxx/yyy are not in MONTH_MAP, causing KeyError -> except
        result = infer_meta_from_text("xxx 01 - yyy 31", config=cfg)
        self.assertNotIn("range", result)

    def test_with_valid_date_range(self):
        from calendars.scan_common import infer_meta_from_text, MetaParserConfig
        cfg = MetaParserConfig(default_year=2025)
        result = infer_meta_from_text("January 10 - March 20", config=cfg)
        self.assertIn("range", result)
        self.assertEqual(result["range"]["start_date"], "2025-01-10")


class TestGmailServiceBuilderWithExplicitClass(unittest.TestCase):
    """Tests for GmailServiceBuilder.build with an explicit service_cls (line 63+)."""

    def test_build_passes_custom_service_cls(self):
        from calendars.pipeline_base import GmailServiceBuilder, GmailAuth
        custom_svc = MagicMock()
        auth = GmailAuth(profile=None, credentials=None, token=None, cache_dir=None)
        with patch("calendars.pipeline_base._build_gmail_service", return_value="fake_svc") as mock_build:
            result = GmailServiceBuilder.build(auth, service_cls=custom_svc)
        mock_build.assert_called_once_with(
            profile=None,
            cache_dir=None,
            credentials_path=None,
            token_path=None,
            service_cls=custom_svc,
        )
        self.assertEqual(result, "fake_svc")

    def test_build_uses_default_gmail_service_when_no_cls(self):
        from calendars.pipeline_base import GmailServiceBuilder, GmailAuth
        from calendars.gmail_service import GmailService
        auth = GmailAuth(profile=None, credentials=None, token=None, cache_dir=None)
        with patch("calendars.pipeline_base._build_gmail_service", return_value="svc") as mock_build:
            GmailServiceBuilder.build(auth)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs["service_cls"], GmailService)


class TestOutlookRemindersProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookRemindersProducer.produce with an error envelope."""

    def test_produce_error_status_prints_message_and_skips_success(self):
        from calendars.outlook_pipelines.reminders import OutlookRemindersProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "Calendar not found: Bogus"})
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookRemindersProducer().produce(env)
        # print_error routes through OutputWriter.print_error -> stderr, not stdout
        self.assertNotIn("Updated reminders", buf.getvalue())
        self.assertNotIn("Disabled reminders", buf.getvalue())
        self.assertIn("Calendar not found: Bogus", err_buf.getvalue())


class TestOutlookAddProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookAddProducer.produce with an error envelope."""

    def test_produce_error_status_skips_success_output(self):
        from calendars.outlook_pipelines.add import OutlookAddProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "events.yaml not found"})
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookAddProducer().produce(env)
        self.assertNotIn("Planned", buf.getvalue())
        self.assertIn("events.yaml not found", err_buf.getvalue())


class TestOutlookRemoveProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookRemoveProducer.produce with an error envelope."""

    def test_produce_error_status_skips_plan_and_deleted_output(self):
        from calendars.outlook_pipelines.remove import OutlookRemoveProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "service is required"})
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookRemoveProducer().produce(env)
        output = buf.getvalue()
        self.assertNotIn("Planned deletions", output)
        self.assertNotIn("Deleted", output)
        self.assertIn("service is required", err_buf.getvalue())


class TestOutlookSettingsProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookSettingsProducer.produce with an error envelope."""

    def test_produce_error_status_skips_success_output(self):
        from calendars.outlook_pipelines.settings import OutlookSettingsProducer
        env = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"message": "Config must contain settings.rules: [] or top-level rules: []"},
        )
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookSettingsProducer().produce(env)
        output = buf.getvalue()
        self.assertNotIn("Applied settings", output)
        self.assertNotIn("Preview complete", output)
        self.assertIn("Config must contain settings.rules", err_buf.getvalue())


class TestOutlookScheduleImportProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookScheduleImportProducer.produce with an error envelope."""

    def test_produce_error_status_skips_success_output(self):
        from calendars.outlook_pipelines.schedule_import import OutlookScheduleImportProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "service is required"})
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookScheduleImportProducer().produce(env)
        output = buf.getvalue()
        self.assertNotIn("Created", output)
        self.assertNotIn("Preview complete", output)
        self.assertIn("service is required", err_buf.getvalue())


class TestOutlookCalendarShareProducerErrorBranch(unittest.TestCase):
    """Sad-path: OutlookCalendarShareProducer.produce with an error envelope."""

    def test_produce_error_status_skips_success_output(self):
        from calendars.outlook_pipelines.share import OutlookCalendarShareProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "service is required"})
        buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err_buf):
            OutlookCalendarShareProducer().produce(env)
        self.assertNotIn("Shared", buf.getvalue())
        self.assertIn("service is required", err_buf.getvalue())


class TestOutlookRemindersProcessorCalendarNotFound(unittest.TestCase):
    """Sad-path: OutlookRemindersProcessor raises when the named calendar is missing."""

    def test_process_raises_value_error_for_unknown_calendar(self):
        from calendars.outlook_pipelines.reminders import OutlookRemindersProcessor, OutlookRemindersRequest
        svc = MagicMock()
        svc.get_calendar_id_by_name.return_value = None
        req = OutlookRemindersRequest(
            service=svc,
            calendar="Bogus",
            from_date=None,
            to_date=None,
            dry_run=True,
            all_occurrences=False,
            set_off=True,
        )
        env = OutlookRemindersProcessor().process(req)
        self.assertEqual(env.status, "error")
        self.assertIn("Calendar not found: Bogus", env.diagnostics["message"])


class TestOutlookRemoveProcessorServiceRequired(unittest.TestCase):
    """Sad-path: OutlookRemoveProcessor raises when service is None."""

    def test_process_raises_value_error_when_service_missing(self):
        from calendars.outlook_pipelines.remove import OutlookRemoveProcessor, OutlookRemoveRequest
        with patch(
            "calendars.outlook_pipelines.remove.load_events_config",
            return_value=[{"subject": "Swim", "start": "2025-01-06T09:00:00", "end": "2025-01-06T10:00:00"}],
        ):
            req = OutlookRemoveRequest(
                config_path=Path("events.yaml"),
                calendar=None,
                subject_only=False,
                apply=False,
                service=None,
            )
            env = OutlookRemoveProcessor().process(req)
        self.assertEqual(env.status, "error")
        self.assertIn("service", env.diagnostics["message"].lower())


class TestOutlookSettingsProcessorInvalidRules(unittest.TestCase):
    """Sad-path: OutlookSettingsProcessor raises when config rules are malformed."""

    def test_process_raises_value_error_when_rules_not_a_list(self):
        from calendars.outlook_pipelines.settings import OutlookSettingsProcessor, OutlookSettingsRequest
        bad_loader = MagicMock(return_value={"settings": {"rules": "not-a-list"}})
        req = OutlookSettingsRequest(
            config_path=Path("settings.yaml"),
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=True,
            service=MagicMock(),
        )
        env = OutlookSettingsProcessor(config_loader=bad_loader).process(req)
        self.assertEqual(env.status, "error")
        self.assertIn("settings.rules", env.diagnostics["message"])


class TestOutlookScheduleImportProcessorServiceRequired(unittest.TestCase):
    """Sad-path: OutlookScheduleImportProcessor raises when service is None."""

    def test_process_raises_value_error_when_service_missing(self):
        from calendars.outlook_pipelines.schedule_import import (
            OutlookScheduleImportProcessor,
            OutlookScheduleImportRequest,
        )
        req = OutlookScheduleImportRequest(
            source="schedule.csv",
            kind=None,
            calendar="Kids",
            tz=None,
            until=None,
            dry_run=True,
            no_reminder=False,
            service=None,
        )
        env = OutlookScheduleImportProcessor().process(req)
        self.assertEqual(env.status, "error")
        self.assertIn("service", env.diagnostics["message"].lower())


class TestOutlookCalendarShareProcessorServiceRequired(unittest.TestCase):
    """Sad-path: OutlookCalendarShareProcessor raises when service is None."""

    def test_process_raises_value_error_when_service_missing(self):
        from calendars.outlook_pipelines.share import (
            OutlookCalendarShareProcessor,
            OutlookCalendarShareRequest,
        )
        req = OutlookCalendarShareRequest(
            service=None,
            calendar="Work",
            recipient="alice@example.com",
            role="write",
        )
        env = OutlookCalendarShareProcessor().process(req)
        self.assertEqual(env.status, "error")
        self.assertIn("service", env.diagnostics["message"].lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
