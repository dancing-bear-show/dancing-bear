"""Unit tests for refactored outlook_pipelines helper methods."""

from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main as unittest_main
from unittest.mock import MagicMock



# --- dedup.py helper tests ---

class TestDedupHelpers(TestCase):
    """Tests for OutlookDedupProcessor helper methods."""

    def _make_processor(self):
        from calendars.outlook_pipelines.dedup import OutlookDedupProcessor
        return OutlookDedupProcessor()

    def test_created_at_returns_earliest(self):
        proc = self._make_processor()
        masters = {"S1": [
            {"createdDateTime": "2024-06-01T00:00:00Z"},
            {"createdDateTime": "2024-01-01T00:00:00Z"},
        ]}
        self.assertEqual(proc._created_at("S1", masters), "2024-01-01T00:00:00Z")

    def test_created_at_empty_returns_empty(self):
        proc = self._make_processor()
        self.assertEqual(proc._created_at("X", {}), "")

    def test_is_standardized_with_address(self):
        proc = self._make_processor()
        masters = {"S1": [{"location": {"address": {"city": "Toronto"}}}]}
        self.assertTrue(proc._is_standardized("S1", masters))

    def test_is_standardized_with_parens_in_name(self):
        proc = self._make_processor()
        masters = {"S1": [{"location": {"displayName": "Pool (North)"}}]}
        self.assertTrue(proc._is_standardized("S1", masters))

    def test_is_standardized_false_for_plain_name(self):
        proc = self._make_processor()
        masters = {"S1": [{"location": {"displayName": "Pool"}}]}
        self.assertFalse(proc._is_standardized("S1", masters))

    def test_pick_keep_delete_prefers_oldest_by_default(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.dedup import OutlookDedupRequest
        payload = OutlookDedupRequest(service=MagicMock())
        keep, delete = proc._pick_keep_delete(["A", "B"], [], ["A", "B"], "B", "A", payload)
        self.assertEqual(keep, "A")
        self.assertEqual(delete, ["B"])

    def test_pick_keep_delete_keep_newest(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.dedup import OutlookDedupRequest
        payload = OutlookDedupRequest(service=MagicMock(), keep_newest=True)
        keep, delete = proc._pick_keep_delete(["A", "B"], [], ["A", "B"], "B", "A", payload)
        self.assertEqual(keep, "B")
        self.assertEqual(delete, ["A"])

    def test_pick_keep_delete_prefer_delete_nonstandard(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.dedup import OutlookDedupRequest
        payload = OutlookDedupRequest(service=MagicMock(), prefer_delete_nonstandard=True)
        keep, delete = proc._pick_keep_delete(["A", "B"], ["A"], ["B"], "B", "A", payload)
        self.assertEqual(keep, "A")
        self.assertEqual(delete, ["B"])


# --- schedule_import.py helper tests ---

class TestScheduleImportHelpers(TestCase):
    """Tests for OutlookScheduleImportProcessor helper methods."""

    def _make_processor(self, loader=None):
        from calendars.outlook_pipelines.schedule_import import OutlookScheduleImportProcessor
        return OutlookScheduleImportProcessor(schedule_loader=loader)

    def test_ensure_calendar_success(self):
        proc = self._make_processor()
        svc = MagicMock()
        svc.ensure_calendar_exists.return_value = "cal-1"
        cal_id = proc._ensure_calendar(svc, "Family")
        self.assertEqual(cal_id, "cal-1")

    def test_ensure_calendar_failure(self):
        proc = self._make_processor()
        svc = MagicMock()
        svc.ensure_calendar_exists.side_effect = RuntimeError("fail")
        with self.assertRaises(RuntimeError) as ctx:
            proc._ensure_calendar(svc, "Bad")
        self.assertIn("fail", str(ctx.exception))

    def test_load_items_success(self):
        items = [MagicMock(subject="Test")]
        proc = self._make_processor(loader=lambda *_, **__: items)
        from calendars.outlook_pipelines.schedule_import import OutlookScheduleImportRequest
        payload = OutlookScheduleImportRequest(source="f.csv", kind=None, calendar=None, tz=None, until=None, dry_run=False, no_reminder=False, service=MagicMock())
        result = proc._load_items(payload)
        self.assertEqual(result, items)

    def test_load_items_value_error(self):
        proc = self._make_processor(loader=lambda *_, **__: (_ for _ in ()).throw(ValueError("bad")))
        from calendars.outlook_pipelines.schedule_import import OutlookScheduleImportRequest
        payload = OutlookScheduleImportRequest(source="f.csv", kind=None, calendar=None, tz=None, until=None, dry_run=False, no_reminder=False, service=MagicMock())
        with self.assertRaises(ValueError) as ctx:
            proc._load_items(payload)
        self.assertIn("bad", str(ctx.exception))

    def test_create_one_off_dry_run(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.schedule_import import OutlookScheduleImportRequest

        @dataclass
        class FakeItem:
            subject: str = "Test"
            start_iso: str = "2025-01-01T10:00:00"
            end_iso: str = "2025-01-01T11:00:00"
            notes: str = ""
            location: str = ""

        svc = MagicMock()
        payload = OutlookScheduleImportRequest(source="", kind=None, calendar=None, tz=None, until=None, dry_run=True, no_reminder=False, service=svc)
        logs = []
        result = proc._create_one_off(FakeItem(), svc, "cal-1", "Cal", payload, logs)
        self.assertEqual(result, 1)
        self.assertIn("[dry-run]", logs[0])
        svc.create_event.assert_not_called()


# --- add.py helper tests ---

class TestAddHelpers(TestCase):
    """Tests for OutlookAddProcessor helper methods."""

    def _make_processor(self):
        from calendars.outlook_pipelines.add import OutlookAddProcessor
        return OutlookAddProcessor()

    def test_resolve_reminder_force_no_reminder(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        payload = OutlookAddRequest(config_path="", dry_run=False, force_no_reminder=True, service=MagicMock())
        no_rem, rem_min = proc._resolve_reminder({"is_reminder_on": True}, payload)
        self.assertTrue(no_rem)
        self.assertIsNone(rem_min)

    def test_resolve_reminder_yaml_off(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        payload = OutlookAddRequest(config_path="", dry_run=False, force_no_reminder=False, service=MagicMock())
        no_rem, rem_min = proc._resolve_reminder({"is_reminder_on": False}, payload)
        self.assertTrue(no_rem)

    def test_resolve_reminder_with_minutes_overrides(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        payload = OutlookAddRequest(config_path="", dry_run=False, force_no_reminder=True, service=MagicMock())
        no_rem, rem_min = proc._resolve_reminder({"reminder_minutes": 15}, payload)
        self.assertFalse(no_rem)
        self.assertEqual(rem_min, 15)

    def test_create_single_dry_run(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        svc = MagicMock()
        payload = OutlookAddRequest(config_path="", dry_run=True, force_no_reminder=False, service=svc)
        logs = []
        result = proc._create_single(1, {"start": "2025-01-01T10:00:00", "end": "2025-01-01T11:00:00"}, "Test", False, None, payload, logs)
        self.assertEqual(result, 1)
        self.assertIn("[dry-run]", logs[0])
        svc.create_event.assert_not_called()

    def test_create_single_missing_start_end(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        payload = OutlookAddRequest(config_path="", dry_run=False, force_no_reminder=False, service=MagicMock())
        logs = []
        result = proc._create_single(1, {}, "Test", False, None, payload, logs)
        self.assertEqual(result, 0)
        self.assertIn("missing start/end", logs[0])

    def test_create_recurring_dry_run(self):
        proc = self._make_processor()
        from calendars.outlook_pipelines.add import OutlookAddRequest
        svc = MagicMock()
        payload = OutlookAddRequest(config_path="", dry_run=True, force_no_reminder=False, service=svc)
        logs = []
        nev = {"repeat": "weekly", "byday": ["MO"], "start_time": "10:00", "end_time": "11:00"}
        result = proc._create_recurring(1, nev, "Series", False, None, payload, logs)
        self.assertEqual(result, 1)
        self.assertIn("[dry-run]", logs[0])
        svc.create_recurring_event.assert_not_called()


if __name__ == "__main__":
    unittest_main()
