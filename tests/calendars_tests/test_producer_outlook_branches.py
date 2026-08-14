"""Tests for uncovered Outlook producer output branches and helper functions."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope


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
            with patch("mail.outlook_api.OutlookClient", fake_client_cls, create=True):
                with self.assertRaises(RuntimeError) as cm:
                    ctx.ensure_client()
        self.assertIn("client-id", str(cm.exception))

    def test_ensure_client_authenticates_when_client_id_present(self):
        from calendars.context import OutlookContext
        ctx = OutlookContext(client_id="fake-id", tenant="consumers", token_path="/tmp/token.json")  # nosec B106 B108 - test string only
        fake_client = MagicMock()
        fake_client_cls = MagicMock(return_value=fake_client)
        with patch("calendars.context.resolve_outlook_credentials", return_value=("fake-id", "consumers", "/tmp/token.json")):  # nosec B108 - test string only
            with patch.dict("sys.modules", {"mail.outlook_api": MagicMock(OutlookClient=fake_client_cls)}):
                result = ctx.ensure_client()
        fake_client.authenticate.assert_called_once()
        self.assertEqual(result, fake_client)

    def test_resolve_returns_consumers_when_tenant_none(self):
        from calendars.context import OutlookContext
        ctx = OutlookContext(client_id="some-id", tenant=None)
        with patch("calendars.context.resolve_outlook_credentials", return_value=("some-id", None, None)):
            _, tenant, _ = ctx.resolve()
        self.assertEqual(tenant, "consumers")

    def test_resolve_falls_through_to_env_vars_when_unset(self):
        """resolve() threads through to real env-var resolution when nothing
        is set on the context and profile config resolvers are unavailable —
        distinct from the other tests here, which mock resolve_outlook_credentials
        away entirely and never exercise its real env-var fallback."""
        import os
        from calendars.context import OutlookContext

        old_id = os.environ.get("MAIL_ASSISTANT_OUTLOOK_CLIENT_ID")
        old_tenant = os.environ.get("MAIL_ASSISTANT_OUTLOOK_TENANT")
        try:
            os.environ["MAIL_ASSISTANT_OUTLOOK_CLIENT_ID"] = "ENV_CLIENT"
            os.environ["MAIL_ASSISTANT_OUTLOOK_TENANT"] = "common"
            with patch("mail.config_resolver.get_outlook_client_id", return_value=None), \
                 patch("mail.config_resolver.get_outlook_tenant", return_value=None), \
                 patch("mail.config_resolver.get_outlook_token_path", return_value=None):
                ctx = OutlookContext()
                client_id, tenant, token_path = ctx.resolve()
            self.assertEqual(client_id, "ENV_CLIENT")
            self.assertEqual(tenant, "common")
            self.assertIsNone(token_path)
        finally:
            if old_id is None:
                os.environ.pop("MAIL_ASSISTANT_OUTLOOK_CLIENT_ID", None)
            else:
                os.environ["MAIL_ASSISTANT_OUTLOOK_CLIENT_ID"] = old_id
            if old_tenant is None:
                os.environ.pop("MAIL_ASSISTANT_OUTLOOK_TENANT", None)
            else:
                os.environ["MAIL_ASSISTANT_OUTLOOK_TENANT"] = old_tenant


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
        result = sync._resolve_event_location("not a dict", calendar=None)
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


if __name__ == "__main__":
    unittest.main()
