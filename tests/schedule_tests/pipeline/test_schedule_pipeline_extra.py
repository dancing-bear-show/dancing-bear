"""Additional tests for schedule/pipeline.py covering previously uncovered lines."""
from __future__ import annotations

import datetime as dt
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from schedule.pipeline import (
    ApplyProcessor,
    ApplyRequest,
    ApplyRequestConsumer,
    DryRunConfig,
    OutlookAuth,
    RecurrenceExpansionConfig,
    SyncMatchContext,
    SyncRequest,
    _apply_outlook_events,
    _build_dry_run_lines,
    _build_have_map,
    _build_outlook_service,
    _build_plan_keys,
    _build_series_maps,
    _calculate_expansion_window,
    _determine_creates,
    _determine_deletes,
    _execute_sync_creates,
    _execute_sync_deletes,
    _expand_weekly_occurrences,
    _extract_event_times,
    _find_missing_series,
    _find_occurrences_to_delete_by_subject,
    _find_occurrences_to_delete_by_time,
    _find_series_to_delete,
    _should_create_oneoff,
    _should_delete_series,
)


class TestExtractEventTimes(unittest.TestCase):
    def test_returns_times_for_valid_event(self):
        ev = {
            "start_time": "10:00",
            "end_time": "11:00",
            "range": {"start_date": "2025-01-01", "until": "2025-01-31"},
        }
        result = _extract_event_times(ev, "2025-01-01", "2025-01-31")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "10:00")
        self.assertEqual(result[1], "11:00")

    def test_returns_none_when_missing_start_time(self):
        ev = {"end_time": "11:00", "range": {"start_date": "2025-01-01"}}
        result = _extract_event_times(ev, "2025-01-01", "2025-01-31")
        self.assertIsNone(result)

    def test_uses_window_dates_when_no_range(self):
        ev = {"start_time": "10:00", "end_time": "11:00"}
        result = _extract_event_times(ev, "2025-01-15", "2025-01-17")
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "2025-01-15")  # range_start from win_from

    def test_start_time_used_as_end_when_end_missing(self):
        ev = {
            "start_time": "10:00",
            "range": {"start_date": "2025-01-01", "until": "2025-01-31"},
        }
        result = _extract_event_times(ev, "2025-01-01", "2025-01-31")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "10:00")  # end_time == start_time fallback


class TestCalculateExpansionWindow(unittest.TestCase):
    def test_within_window(self):
        result = _calculate_expansion_window("2025-01-01", "2025-01-31", "2025-01-15", "2025-01-20")
        self.assertIsNotNone(result)
        cur, end = result
        self.assertEqual(cur, dt.date(2025, 1, 15))
        self.assertEqual(end, dt.date(2025, 1, 20))

    def test_range_contains_window(self):
        result = _calculate_expansion_window("2025-01-01", "2025-12-31", "2025-03-01", "2025-04-30")
        self.assertIsNotNone(result)

    def test_no_overlap_returns_none(self):
        result = _calculate_expansion_window("2025-01-01", "2025-01-10", "2025-02-01", "2025-02-28")
        self.assertIsNone(result)

    def test_exact_boundary(self):
        result = _calculate_expansion_window("2025-01-15", "2025-01-15", "2025-01-01", "2025-01-31")
        self.assertIsNotNone(result)


class TestExpandWeeklyOccurrences(unittest.TestCase):
    def test_expands_weekly(self):
        ev = {"byday": ["MO", "WE"]}
        start = dt.date(2025, 1, 13)  # Monday
        end = dt.date(2025, 1, 19)  # Sunday
        config = RecurrenceExpansionConfig(start_date=start, end_date=end, start_time="10:00", end_time="11:00", excluded_dates=set())
        result = _expand_weekly_occurrences(ev, config)
        self.assertEqual(len(result), 2)

    def test_returns_empty_when_no_byday(self):
        ev = {}
        config = RecurrenceExpansionConfig(start_date=dt.date(2025, 1, 13), end_date=dt.date(2025, 1, 19), start_time="10:00", end_time="11:00", excluded_dates=set())
        result = _expand_weekly_occurrences(ev, config)
        self.assertEqual(result, [])

    def test_returns_empty_when_invalid_byday(self):
        ev = {"byday": ["XX", "YY"]}
        config = RecurrenceExpansionConfig(start_date=dt.date(2025, 1, 13), end_date=dt.date(2025, 1, 19), start_time="10:00", end_time="11:00", excluded_dates=set())
        result = _expand_weekly_occurrences(ev, config)
        self.assertEqual(result, [])


class TestBuildOutlookService(unittest.TestCase):
    def test_returns_error_on_runtime_error(self):
        auth = OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None)
        with patch("schedule.pipeline_verify.build_outlook_service", side_effect=RuntimeError("no creds")):
            svc, err = _build_outlook_service(auth)
            self.assertIsNone(svc)
            self.assertIn("no creds", err)

    def test_returns_error_on_import_or_value_error(self):
        # _build_outlook_service narrows to (ImportError, OSError, ValueError) for non-auth errors
        auth = OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None)
        with patch("schedule.pipeline_verify.build_outlook_service", side_effect=ValueError("unavailable")):
            svc, err = _build_outlook_service(auth)
            self.assertIsNone(svc)
            self.assertIn("unavailable", err)


class TestApplyOutlookEvents(unittest.TestCase):
    def _make_svc(self):
        svc = MagicMock()
        svc.ensure_calendar.return_value = "cal-id"
        svc.get_calendar_id_by_name.return_value = "cal-id"
        svc.create_event.return_value = {"id": "event-id-1"}
        svc.create_recurring_event.return_value = {"id": "recurring-event-id"}
        return svc

    def test_creates_one_off_event(self):
        svc = self._make_svc()
        events = [{"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, logs = _apply_outlook_events(events, calendar_name="Work", service=svc)
        self.assertEqual(rc, 0)
        self.assertTrue(any("Meeting" in log for log in logs))

    def test_creates_recurring_event(self):
        svc = self._make_svc()
        events = [{
            "subject": "Daily Standup",
            "repeat": "daily",
            "start_time": "09:00",
            "end_time": "09:30",
            "range": {"start_date": "2025-01-15", "until": "2025-01-31"},
        }]
        rc, _logs = _apply_outlook_events(events, calendar_name="Work", service=svc)
        self.assertEqual(rc, 0)

    def test_skips_event_without_subject(self):
        svc = self._make_svc()
        events = [{"start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertEqual(rc, 0)
        self.assertTrue(any("Skipping" in log for log in logs))

    def test_skips_event_with_insufficient_fields(self):
        svc = self._make_svc()
        events = [{"subject": "Orphan"}]  # no start/end and no repeat
        rc, logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertEqual(rc, 0)
        self.assertTrue(any("Skipping" in log for log in logs))

    def test_handles_create_failure(self):
        svc = self._make_svc()
        svc.create_event.side_effect = Exception("API error")
        events = [{"subject": "Fail Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, _logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertEqual(rc, 2)

    def test_ensure_calendar_failure_fallback(self):
        svc = self._make_svc()
        svc.ensure_calendar.side_effect = Exception("calendar not found")
        svc.get_calendar_id_by_name.return_value = "cal-id-from-name"
        svc.create_event.return_value = {"id": "eid"}
        events = [{"subject": "Test", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, _logs = _apply_outlook_events(events, calendar_name="Work", service=svc)
        self.assertEqual(rc, 0)

    def test_no_calendar_name(self):
        svc = self._make_svc()
        events = [{"subject": "Test", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, _logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertEqual(rc, 0)

    def test_event_id_in_log_when_available(self):
        svc = self._make_svc()
        svc.create_event.return_value = {"id": "my-event-id"}
        events = [{"subject": "With ID", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        _rc, logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertTrue(any("my-event-id" in log for log in logs))

    def test_event_without_id_in_response(self):
        svc = self._make_svc()
        svc.create_event.return_value = {}
        events = [{"subject": "No ID", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        rc, logs = _apply_outlook_events(events, calendar_name=None, service=svc)
        self.assertEqual(rc, 0)
        self.assertTrue(any("No ID" in log for log in logs))


class TestBuildPlanKeys(unittest.TestCase):
    def test_builds_keys_for_oneoffs(self):
        events = [
            {"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"},
        ]
        plan_st_keys, _series_by_subject, planned_subjects = _build_plan_keys(
            events, "2025-01-15", "2025-01-15"
        )
        self.assertEqual(len(plan_st_keys), 1)
        self.assertEqual(len(planned_subjects), 1)

    def test_builds_keys_for_recurring(self):
        events = [
            {
                "subject": "Standup",
                "repeat": "daily",
                "start_time": "09:00",
                "end_time": "09:30",
                "range": {"start_date": "2025-01-15", "until": "2025-01-17"},
            }
        ]
        plan_st_keys, series_by_subject, _planned_subjects = _build_plan_keys(
            events, "2025-01-15", "2025-01-17"
        )
        self.assertEqual(len(plan_st_keys), 3)
        self.assertIn("standup", series_by_subject)

    def test_skips_events_without_subject(self):
        events = [{"start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        plan_st_keys, _series, planned = _build_plan_keys(events, "2025-01-15", "2025-01-15")
        self.assertEqual(len(plan_st_keys), 0)
        self.assertEqual(len(planned), 0)


class TestBuildHaveMap(unittest.TestCase):
    def test_builds_map_from_occurrences(self):
        occ = [
            {
                "id": "event-1",
                "subject": "Meeting",
                "start": {"dateTime": "2025-01-15T10:00:00"},
                "end": {"dateTime": "2025-01-15T11:00:00"},
            }
        ]
        _have_map, have_keys = _build_have_map(occ)
        self.assertEqual(len(have_keys), 1)
        key = list(have_keys)[0]
        self.assertIn("meeting", key)

    def test_handles_non_dict_start_end(self):
        occ = [
            {
                "id": "event-1",
                "subject": "AllDay",
                "start": "2025-01-15",
                "end": "2025-01-16",
            }
        ]
        _have_map, have_keys = _build_have_map(occ)
        self.assertEqual(len(have_keys), 1)


class TestFindMissingSeries(unittest.TestCase):
    def test_finds_missing_series(self):
        series_by_subject = {
            "standup": {"subject": "Standup"},
            "meeting": {"subject": "Meeting"},
        }
        present_subjects = {"meeting"}
        result = _find_missing_series(series_by_subject, present_subjects)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["subject"], "Standup")

    def test_empty_when_all_present(self):
        series_by_subject = {"standup": {"subject": "Standup"}}
        present_subjects = {"standup"}
        result = _find_missing_series(series_by_subject, present_subjects)
        self.assertEqual(result, [])


class TestShouldCreateOneoff(unittest.TestCase):
    def test_returns_false_when_no_start_end(self):
        e = {"subject": "Event"}
        result = _should_create_oneoff(e, "subject-time", [], set())
        self.assertFalse(result)

    def test_returns_true_for_subject_time_match(self):
        e = {"subject": "Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        key = "event|2025-01-15T10:00|2025-01-15T11:00"
        result = _should_create_oneoff(e, "subject-time", [key], set())
        self.assertTrue(result)

    def test_returns_false_for_subject_time_no_match(self):
        e = {"subject": "Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = _should_create_oneoff(e, "subject-time", [], set())
        self.assertFalse(result)

    def test_returns_true_for_subject_mode_when_not_present(self):
        e = {"subject": "New Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = _should_create_oneoff(e, "subject", [], {"existing event"})
        self.assertTrue(result)

    def test_returns_false_for_subject_mode_when_present(self):
        e = {"subject": "Existing Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = _should_create_oneoff(e, "subject", [], {"existing event"})
        self.assertFalse(result)


class TestDetermineCreates(unittest.TestCase):
    def test_determines_creates(self):
        events = [
            {"subject": "New Event", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        ]
        series_by_subject = {"missing_series": {"subject": "Missing Series"}}
        ctx = SyncMatchContext(
            plan_st_keys={"new event|2025-01-15T10:00|2025-01-15T11:00"},
            planned_subjects_set={"new event"},
            have_keys=set(),
            have_map={},
            match_mode="subject-time",
        )
        to_create_series, _to_create_oneoffs = _determine_creates(
            events, series_by_subject, set(), ctx
        )
        self.assertEqual(len(to_create_series), 1)


class TestFindOccurrencesToDeleteByTime(unittest.TestCase):
    def test_finds_single_instance_events(self):
        have_map = {
            "event|2025-01-15T10:00|2025-01-15T11:00": {
                "id": "event-id-1",
                "type": "singleInstance",
            }
        }
        extra_keys = ["event|2025-01-15T10:00|2025-01-15T11:00"]
        result = _find_occurrences_to_delete_by_time(extra_keys, have_map)
        self.assertIn("event-id-1", result)

    def test_finds_occurrence_type_events(self):
        have_map = {
            "event|2025-01-15T10:00|2025-01-15T11:00": {
                "id": "occ-id",
                "type": "occurrence",
                "seriesMasterId": "master-id",
            }
        }
        extra_keys = ["event|2025-01-15T10:00|2025-01-15T11:00"]
        result = _find_occurrences_to_delete_by_time(extra_keys, have_map)
        self.assertIn("occ-id", result)

    def test_skips_events_without_id(self):
        have_map = {
            "event|2025-01-15T10:00|2025-01-15T11:00": {"type": "singleInstance"}
        }
        extra_keys = ["event|2025-01-15T10:00|2025-01-15T11:00"]
        result = _find_occurrences_to_delete_by_time(extra_keys, have_map)
        self.assertEqual(result, [])


class TestFindOccurrencesToDeleteBySubject(unittest.TestCase):
    def test_deletes_unplanned_subjects(self):
        have_map = {
            "unplanned|t1|t2": {"id": "del-id", "subject": "Unplanned Event"},
            "planned|t3|t4": {"id": "keep-id", "subject": "Planned Event"},
        }
        planned_subjects = {"planned event"}
        result = _find_occurrences_to_delete_by_subject(have_map, planned_subjects)
        self.assertIn("del-id", result)
        self.assertNotIn("keep-id", result)


class TestBuildSeriesMaps(unittest.TestCase):
    def test_builds_maps(self):
        have_map = {
            "event1|t1|t2": {
                "id": "occ1",
                "subject": "Recurring",
                "seriesMasterId": "master1",
            },
            "event2|t3|t4": {
                "id": "occ2",
                "subject": "Recurring",
                "seriesMasterId": "master1",
            },
        }
        series_keys, series_subject = _build_series_maps(have_map)
        self.assertIn("master1", series_keys)
        self.assertEqual(len(series_keys["master1"]), 2)
        self.assertEqual(series_subject["master1"], "Recurring")


class TestShouldDeleteSeries(unittest.TestCase):
    def test_does_not_delete_planned_series(self):
        ctx = SyncMatchContext(
            plan_st_keys=set(),
            planned_subjects_set={"recurring meeting"},
            have_keys=set(),
            have_map={},
            match_mode="subject-time",
        )
        series_subject = {"master1": "Recurring Meeting"}
        result = _should_delete_series("master1", [], series_subject, ctx)
        self.assertFalse(result)

    def test_deletes_unplanned_series_in_subject_time_mode(self):
        ctx = SyncMatchContext(
            plan_st_keys={"planned|t1|t2"},
            planned_subjects_set={"planned"},
            have_keys=set(),
            have_map={},
            match_mode="subject-time",
        )
        series_subject = {"master1": "Unplanned"}
        result = _should_delete_series("master1", ["unplanned|t3|t4"], series_subject, ctx)
        self.assertTrue(result)


class TestFindSeriesToDelete(unittest.TestCase):
    def test_finds_unplanned_series(self):
        have_map = {
            "unplanned|t1|t2": {
                "subject": "Unplanned",
                "seriesMasterId": "master-unplanned",
            }
        }
        ctx = SyncMatchContext(
            plan_st_keys={"planned|t3|t4"},
            planned_subjects_set={"planned"},
            have_keys={"unplanned|t1|t2"},
            have_map=have_map,
            match_mode="subject-time",
        )
        result = _find_series_to_delete(ctx)
        self.assertIn("master-unplanned", result)


class TestDetermineDeletes(unittest.TestCase):
    def _make_payload(self, delete_missing=True, delete_unplanned=False):
        return SyncRequest(
            plan_path=Path("plan.yaml"),
            calendar="Work",
            from_date="2025-01-15",
            to_date="2025-01-20",
            match="subject-time",
            delete_missing=delete_missing,
            delete_unplanned_series=delete_unplanned,
            apply=False,
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )

    def test_returns_empty_when_delete_missing_false(self):
        payload = self._make_payload(delete_missing=False)
        ctx = SyncMatchContext(
            plan_st_keys=set(),
            planned_subjects_set=set(),
            have_keys={"extra|t1|t2"},
            have_map={},
            match_mode="subject-time",
        )
        occ_ids, series_ids = _determine_deletes(payload, ctx)
        self.assertEqual(occ_ids, [])
        self.assertEqual(series_ids, [])

    def test_deletes_in_subject_mode(self):
        payload = self._make_payload(delete_missing=True)
        payload.match = "subject"
        have_map = {
            "unplanned|t1|t2": {"id": "del-id", "subject": "Unplanned"},
        }
        ctx = SyncMatchContext(
            plan_st_keys=set(),
            planned_subjects_set={"planned"},
            have_keys={"unplanned|t1|t2"},
            have_map=have_map,
            match_mode="subject",
        )
        occ_ids, _series_ids = _determine_deletes(payload, ctx)
        self.assertIn("del-id", occ_ids)


class TestBuildDryRunLines(unittest.TestCase):
    def _make_payload(self, delete_missing=False, delete_unplanned=False):
        return SyncRequest(
            plan_path=Path("plan.yaml"),
            calendar="Work",
            from_date="2025-01-15",
            to_date="2025-01-20",
            match="subject-time",
            delete_missing=delete_missing,
            delete_unplanned_series=delete_unplanned,
            apply=False,
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )

    def test_dry_run_basic(self):
        cfg = DryRunConfig(
            to_create_series=[],
            to_create_oneoffs=[],
            to_delete_occurrence_ids=[],
            to_delete_series_master_ids=[],
            match_mode="subject-time",
        )
        lines = _build_dry_run_lines(self._make_payload(), cfg)
        self.assertTrue(any("[DRY-RUN]" in line for line in lines))
        self.assertTrue(any("disabled" in line for line in lines))

    def test_dry_run_with_creates(self):
        series = [{"subject": "New Recurring", "repeat": "weekly", "byday": ["MO"], "start_time": "10:00"}]
        oneoffs = [{"subject": "One Off", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]
        cfg = DryRunConfig(
            to_create_series=series,
            to_create_oneoffs=oneoffs,
            to_delete_occurrence_ids=[],
            to_delete_series_master_ids=[],
            match_mode="subject-time",
        )
        lines = _build_dry_run_lines(self._make_payload(), cfg)
        self.assertTrue(any("New Recurring" in line for line in lines))
        self.assertTrue(any("One Off" in line for line in lines))

    def test_dry_run_with_deletes(self):
        cfg = DryRunConfig(
            to_create_series=[],
            to_create_oneoffs=[],
            to_delete_occurrence_ids=["id1", "id2"],
            to_delete_series_master_ids=["master1"],
            match_mode="subject-time",
        )
        lines = _build_dry_run_lines(self._make_payload(delete_missing=True, delete_unplanned=True), cfg)
        self.assertTrue(any("extraneous" in line for line in lines))
        self.assertTrue(any("unplanned" in line for line in lines))


class TestExecuteSyncCreates(unittest.TestCase):
    def test_creates_series_and_oneoffs(self):
        svc = MagicMock()
        svc.ensure_calendar.return_value = "cal-id"
        svc.create_recurring_event.return_value = {"id": "r1"}
        svc.create_event.return_value = {"id": "e1"}

        payload = SyncRequest(
            plan_path=Path("plan.yaml"),
            calendar="Work",
            from_date="2025-01-15",
            to_date="2025-01-20",
            match="subject-time",
            delete_missing=False,
            delete_unplanned_series=False,
            apply=True,
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        series = [{
            "subject": "Weekly",
            "repeat": "weekly",
            "start_time": "10:00",
            "end_time": "11:00",
            "range": {"start_date": "2025-01-15", "until": "2025-01-31"},
            "byday": ["MO"],
        }]
        oneoffs = [{"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}]

        _lines, created = _execute_sync_creates(svc, payload, series, oneoffs)
        self.assertGreaterEqual(created, 0)


class TestExecuteSyncDeletes(unittest.TestCase):
    def test_deletes_occurrences(self):
        raw_client = MagicMock()
        raw_client.delete_event = MagicMock()

        payload = SyncRequest(
            plan_path=Path("plan.yaml"),
            calendar="Work",
            from_date="2025-01-15",
            to_date="2025-01-20",
            match="subject-time",
            delete_missing=True,
            delete_unplanned_series=True,
            apply=True,
            auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
        )
        deleted = _execute_sync_deletes(raw_client, "cal-id", payload, ["occ1", "occ2"], ["master1"])
        self.assertEqual(deleted, 3)  # 2 occ + 1 master


class TestApplyProcessorDryRun(unittest.TestCase):
    def test_dry_run_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events:\n  - subject: Test Event\n    start: '2025-01-15T10:00'\n    end: '2025-01-15T11:00'\n")

            request = ApplyRequest(
                plan_path=plan_path,
                calendar="Work",
                provider="outlook",
                apply=False,
                auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                env = ApplyProcessor().process(ApplyRequestConsumer(request).consume())
            self.assertTrue(env.ok())
            self.assertIn("[DRY-RUN]", env.payload.lines[0])

    def test_unsupported_provider_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events: []\n")

            request = ApplyRequest(
                plan_path=plan_path,
                calendar=None,
                provider="gmail",
                apply=True,
                auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
            )
            with patch("schedule.pipeline._build_outlook_service", return_value=(MagicMock(), None)):
                env = ApplyProcessor().process(ApplyRequestConsumer(request).consume())
            self.assertFalse(env.ok())

    def test_apply_with_outlook_service_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.yaml"
            plan_path.write_text("events: []\n")

            request = ApplyRequest(
                plan_path=plan_path,
                calendar=None,
                provider="outlook",
                apply=True,
                auth=OutlookAuth(profile=None, client_id=None, tenant=None, token_path=None),
            )
            with patch("schedule.pipeline._build_outlook_service", return_value=(None, "no creds")):
                env = ApplyProcessor().process(ApplyRequestConsumer(request).consume())
            self.assertFalse(env.ok())


class TestExportScheduleProcessor(unittest.TestCase):
    """Tests for ExportScheduleProcessor._process_safe() and ExportScheduleProducer."""

    def _make_svc(self, events):
        """Build a mock service that returns the given events from list_events_in_range."""
        svc = MagicMock()
        svc.list_events_in_range.return_value = events
        return svc

    def _make_request(self, svc, out_path):
        from schedule.pipeline import ExportScheduleRequest
        return ExportScheduleRequest(
            service=svc,
            cal_name="Activities",
            start_iso="2025-10-01T00:00:00",
            end_iso="2025-10-31T23:59:59",
            out_path=out_path,
        )

    # --- Happy path ---

    def test_export_happy_path_produces_yaml_and_prints_summary(self):
        """Consumer -> processor -> producer writes YAML and prints summary."""
        from schedule.pipeline import (
            ExportScheduleProcessor,
            ExportScheduleProducer,
            ExportScheduleRequestConsumer,
        )

        evs = [
            {
                "subject": "Swim",
                "start": {"dateTime": "2025-10-06T10:00:00"},
                "end": {"dateTime": "2025-10-06T11:00:00"},
                "location": {"displayName": "Pool"},
            },
            {
                "subject": "Skate",
                "start": {"dateTime": "2025-10-07T14:00:00"},
                "end": {"dateTime": "2025-10-07T15:00:00"},
                "location": {"displayName": "Rink"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "export.yaml"
            svc = self._make_svc(evs)
            request = self._make_request(svc, out_path)

            envelope = ExportScheduleProcessor().process(
                ExportScheduleRequestConsumer(request).consume()
            )

            self.assertTrue(envelope.ok())
            self.assertEqual(len(envelope.payload.rows), 2)
            # Rows are sorted by start time
            self.assertEqual(envelope.payload.rows[0]["subject"], "Swim")
            self.assertEqual(envelope.payload.rows[1]["subject"], "Skate")
            self.assertEqual(envelope.payload.cal_name, "Activities")

            # Produce: write YAML and print summary
            buf_out = io.StringIO()
            with redirect_stdout(buf_out):
                ExportScheduleProducer().produce(envelope)

            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("events:", content)
            self.assertIn("Swim", content)
            self.assertIn("Skate", content)
            summary = buf_out.getvalue()
            self.assertIn("Exported 2 events", summary)
            self.assertIn("Activities", summary)

    def test_export_skips_events_with_missing_fields(self):
        """Events with no subject, no start, or no end are silently skipped."""
        from schedule.pipeline import (
            ExportScheduleProcessor,
            ExportScheduleRequestConsumer,
        )

        evs = [
            # No subject
            {"start": {"dateTime": "2025-10-06T10:00:00"}, "end": {"dateTime": "2025-10-06T11:00:00"}},
            # No start
            {"subject": "Ghost", "end": {"dateTime": "2025-10-06T11:00:00"}},
            # No end
            {"subject": "Phantom", "start": {"dateTime": "2025-10-06T10:00:00"}},
            # Valid
            {
                "subject": "Valid",
                "start": {"dateTime": "2025-10-06T10:00:00"},
                "end": {"dateTime": "2025-10-06T11:00:00"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "export.yaml"
            svc = self._make_svc(evs)
            request = self._make_request(svc, out_path)

            envelope = ExportScheduleProcessor().process(
                ExportScheduleRequestConsumer(request).consume()
            )

            self.assertTrue(envelope.ok())
            self.assertEqual(len(envelope.payload.rows), 1)
            self.assertEqual(envelope.payload.rows[0]["subject"], "Valid")

    def test_export_empty_calendar_produces_empty_events(self):
        """Empty calendar returns 0-row result and writes events: [] to YAML."""
        from schedule.pipeline import (
            ExportScheduleProcessor,
            ExportScheduleProducer,
            ExportScheduleRequestConsumer,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "empty.yaml"
            svc = self._make_svc([])
            request = self._make_request(svc, out_path)

            envelope = ExportScheduleProcessor().process(
                ExportScheduleRequestConsumer(request).consume()
            )

            self.assertTrue(envelope.ok())
            self.assertEqual(envelope.payload.rows, [])

            buf_out = io.StringIO()
            with redirect_stdout(buf_out):
                ExportScheduleProducer().produce(envelope)

            self.assertTrue(out_path.exists())
            self.assertIn("Exported 0 events", buf_out.getvalue())

    # --- Sad paths (per distinct raise site in _process_safe) ---

    def test_export_sad_path_service_raises_propagates_as_error_envelope(self):
        """If list_events_in_range raises, SafeProcessor returns error envelope."""
        from schedule.pipeline import (
            ExportScheduleProcessor,
            ExportScheduleRequestConsumer,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "export.yaml"
            svc = MagicMock()
            svc.list_events_in_range.side_effect = RuntimeError("API timeout")

            from schedule.pipeline import ExportScheduleRequest
            request = ExportScheduleRequest(
                service=svc,
                cal_name="Activities",
                start_iso="2025-10-01T00:00:00",
                end_iso="2025-10-31T23:59:59",
                out_path=out_path,
            )

            envelope = ExportScheduleProcessor().process(
                ExportScheduleRequestConsumer(request).consume()
            )

            self.assertFalse(envelope.ok())
            self.assertIn("API timeout", envelope.diagnostics.get("message", ""))

    def test_export_producer_prints_error_to_stderr_on_failure(self):
        """ExportScheduleProducer.produce() routes error message to stderr."""
        from schedule.pipeline import ExportScheduleProducer

        env = ResultEnvelope(
            status="error", diagnostics={"message": "Export pipeline failed"}
        )
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            ExportScheduleProducer().produce(env)
        self.assertIn("Export pipeline failed", buf_err.getvalue())

    def test_export_rows_sorted_by_start(self):
        """Output rows are sorted ascending by start datetime string."""
        from schedule.pipeline import (
            ExportScheduleProcessor,
            ExportScheduleRequestConsumer,
        )

        # Provide events out of order
        evs = [
            {
                "subject": "Later",
                "start": {"dateTime": "2025-10-10T14:00:00"},
                "end": {"dateTime": "2025-10-10T15:00:00"},
            },
            {
                "subject": "Earlier",
                "start": {"dateTime": "2025-10-05T09:00:00"},
                "end": {"dateTime": "2025-10-05T10:00:00"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "sorted.yaml"
            svc = self._make_svc(evs)
            request = self._make_request(svc, out_path)

            envelope = ExportScheduleProcessor().process(
                ExportScheduleRequestConsumer(request).consume()
            )

            self.assertTrue(envelope.ok())
            self.assertEqual(envelope.payload.rows[0]["subject"], "Earlier")
            self.assertEqual(envelope.payload.rows[1]["subject"], "Later")


if __name__ == "__main__":
    unittest.main()
