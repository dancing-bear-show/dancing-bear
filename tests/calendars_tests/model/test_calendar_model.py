"""Tests for calendars/model.py event normalization utilities."""
import unittest

from calendars.model import (
    _coerce_str,
    _normalize_byday,
    _normalize_range,
    normalize_event,
)


class CoerceStrTests(unittest.TestCase):
    """Tests for _coerce_str function."""

    def test_none_returns_none(self):
        self.assertIsNone(_coerce_str(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_coerce_str(""))

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(_coerce_str("   "))

    def test_strips_whitespace(self):
        self.assertEqual(_coerce_str("  hello  "), "hello")

    def test_converts_int_to_string(self):
        self.assertEqual(_coerce_str(123), "123")

    def test_normal_string(self):
        self.assertEqual(_coerce_str("test"), "test")


class NormalizeBydayTests(unittest.TestCase):
    """Tests for _normalize_byday function."""

    def test_none_returns_none(self):
        self.assertIsNone(_normalize_byday(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_normalize_byday(""))

    def test_list_of_codes(self):
        result = _normalize_byday(["MO", "WE", "FR"])
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_comma_separated_string(self):
        result = _normalize_byday("MO, WE, FR")
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_full_day_names(self):
        result = _normalize_byday(["Monday", "Wednesday"])
        self.assertEqual(result, ["MO", "WE"])

    def test_short_day_names(self):
        result = _normalize_byday(["Mon", "Wed", "Fri"])
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_mixed_formats(self):
        result = _normalize_byday("Monday, WE, fri")
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_deduplicates(self):
        result = _normalize_byday(["MO", "Monday", "mon"])
        self.assertEqual(result, ["MO"])

    def test_semicolon_separated(self):
        result = _normalize_byday("MO;WE;FR")
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_space_separated(self):
        result = _normalize_byday("MO WE FR")
        self.assertEqual(result, ["MO", "WE", "FR"])

    def test_tuesday_variants(self):
        result = _normalize_byday(["tue", "tues", "tuesday"])
        self.assertEqual(result, ["TU"])

    def test_thursday_variants(self):
        result = _normalize_byday(["thu", "thur", "thurs", "thursday"])
        self.assertEqual(result, ["TH"])


class NormalizeRangeTests(unittest.TestCase):
    """Tests for _normalize_range function."""

    def test_no_range_returns_none(self):
        self.assertIsNone(_normalize_range({}))

    def test_range_with_start_date(self):
        ev = {"range": {"start_date": "2025-01-15"}}
        result = _normalize_range(ev)
        self.assertEqual(result, {"start_date": "2025-01-15"})

    def test_range_with_until(self):
        ev = {"range": {"until": "2025-03-15"}}
        result = _normalize_range(ev)
        self.assertEqual(result, {"until": "2025-03-15"})

    def test_range_with_both(self):
        ev = {"range": {"start_date": "2025-01-15", "until": "2025-03-15"}}
        result = _normalize_range(ev)
        self.assertEqual(result, {"start_date": "2025-01-15", "until": "2025-03-15"})

    def test_camel_case_startDate(self):
        ev = {"range": {"startDate": "2025-01-15"}}
        result = _normalize_range(ev)
        self.assertEqual(result, {"start_date": "2025-01-15"})

    def test_top_level_start_date(self):
        ev = {"start_date": "2025-01-15"}
        result = _normalize_range(ev)
        self.assertEqual(result, {"start_date": "2025-01-15"})

    def test_end_date_alias(self):
        ev = {"range": {"end_date": "2025-03-15"}}
        result = _normalize_range(ev)
        self.assertEqual(result, {"until": "2025-03-15"})


class NormalizeEventTests(unittest.TestCase):
    """Tests for normalize_event function."""

    def test_minimal_event(self):
        ev = {"subject": "Meeting"}
        result = normalize_event(ev)
        self.assertEqual(result["subject"], "Meeting")

    def test_strips_none_values(self):
        ev = {"subject": "Meeting", "location": None}
        result = normalize_event(ev)
        self.assertNotIn("location", result)
        self.assertNotIn("calendar", result)

    def test_normalizes_byday(self):
        ev = {"subject": "Class", "byday": ["Monday", "Wednesday"]}
        result = normalize_event(ev)
        self.assertEqual(result["byday"], ["MO", "WE"])

    def test_byDay_alias(self):
        ev = {"subject": "Class", "byDay": ["MO", "FR"]}
        result = normalize_event(ev)
        self.assertEqual(result["byday"], ["MO", "FR"])

    def test_normalizes_range(self):
        ev = {
            "subject": "Course",
            "range": {"start_date": "2025-01-15", "until": "2025-03-15"},
        }
        result = normalize_event(ev)
        self.assertEqual(result["range"]["start_date"], "2025-01-15")
        self.assertEqual(result["range"]["until"], "2025-03-15")

    def test_body_html_alias(self):
        ev = {"subject": "Meeting", "bodyHtml": "<p>Notes</p>"}
        result = normalize_event(ev)
        self.assertEqual(result["body_html"], "<p>Notes</p>")

    def test_start_time_aliases(self):
        for key in ["start_time", "startTime", "start-time"]:
            ev = {"subject": "Class", key: "10:00"}
            result = normalize_event(ev)
            self.assertEqual(result["start_time"], "10:00", f"Failed for key: {key}")

    def test_end_time_aliases(self):
        for key in ["end_time", "endTime", "end-time"]:
            ev = {"subject": "Class", key: "11:00"}
            result = normalize_event(ev)
            self.assertEqual(result["end_time"], "11:00", f"Failed for key: {key}")

    def test_exdates_list(self):
        ev = {"subject": "Class", "exdates": ["2025-01-20", "2025-01-27"]}
        result = normalize_event(ev)
        self.assertEqual(result["exdates"], ["2025-01-20", "2025-01-27"])

    def test_exdates_string(self):
        ev = {"subject": "Class", "exdates": "2025-01-20, 2025-01-27"}
        result = normalize_event(ev)
        self.assertEqual(result["exdates"], ["2025-01-20", "2025-01-27"])

    def test_exceptions_alias(self):
        ev = {"subject": "Class", "exceptions": ["2025-01-20"]}
        result = normalize_event(ev)
        self.assertEqual(result["exdates"], ["2025-01-20"])

    def test_interval_int(self):
        ev = {"subject": "Weekly", "interval": 2}
        result = normalize_event(ev)
        self.assertEqual(result["interval"], 2)

    def test_interval_string(self):
        ev = {"subject": "Weekly", "interval": "3"}
        result = normalize_event(ev)
        self.assertEqual(result["interval"], 3)

    def test_interval_invalid(self):
        ev = {"subject": "Weekly", "interval": "invalid"}
        result = normalize_event(ev)
        self.assertNotIn("interval", result)

    def test_count_int(self):
        ev = {"subject": "Class", "count": 10}
        result = normalize_event(ev)
        self.assertEqual(result["count"], 10)

    def test_count_string(self):
        ev = {"subject": "Class", "count": "5"}
        result = normalize_event(ev)
        self.assertEqual(result["count"], 5)

    def test_is_reminder_on_bool_false(self):
        ev = {"subject": "Meeting", "is_reminder_on": False}
        result = normalize_event(ev)
        self.assertFalse(result.get("is_reminder_on", False))

    def test_is_reminder_on_bool_true(self):
        ev = {"subject": "Meeting", "is_reminder_on": True}
        result = normalize_event(ev)
        self.assertEqual(result["is_reminder_on"], True)

    def test_isReminderOn_alias(self):
        ev = {"subject": "Meeting", "isReminderOn": True}
        result = normalize_event(ev)
        self.assertEqual(result["is_reminder_on"], True)

    def test_reminder_string_off(self):
        for val in ["off", "none", "no", "false", "0"]:
            ev = {"subject": "Meeting", "reminder": val}
            result = normalize_event(ev)
            self.assertEqual(result["is_reminder_on"], False, f"Failed for: {val}")

    def test_reminder_string_on(self):
        for val in ["on", "yes", "true", "1"]:
            ev = {"subject": "Meeting", "reminder": val}
            result = normalize_event(ev)
            self.assertEqual(result["is_reminder_on"], True, f"Failed for: {val}")

    def test_reminder_minutes(self):
        ev = {"subject": "Meeting", "reminder_minutes": 15}
        result = normalize_event(ev)
        self.assertEqual(result["reminder_minutes"], 15)

    def test_reminderMinutes_alias(self):
        ev = {"subject": "Meeting", "reminderMinutes": "30"}
        result = normalize_event(ev)
        self.assertEqual(result["reminder_minutes"], 30)

    def test_single_event_start_end(self):
        ev = {"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = normalize_event(ev)
        self.assertEqual(result["start"], "2025-01-15T10:00")
        self.assertEqual(result["end"], "2025-01-15T11:00")

    def test_full_recurring_event(self):
        ev = {
            "subject": "Weekly Standup",
            "repeat": "weekly",
            "byday": ["MO", "WE", "FR"],
            "start_time": "09:00",
            "end_time": "09:30",
            "range": {"start_date": "2025-01-06", "until": "2025-03-31"},
            "tz": "America/Toronto",
            "location": "Conference Room",
        }
        result = normalize_event(ev)
        self.assertEqual(result["subject"], "Weekly Standup")
        self.assertEqual(result["repeat"], "weekly")
        self.assertEqual(result["byday"], ["MO", "WE", "FR"])
        self.assertEqual(result["start_time"], "09:00")
        self.assertEqual(result["end_time"], "09:30")
        self.assertEqual(result["range"]["start_date"], "2025-01-06")
        self.assertEqual(result["tz"], "America/Toronto")
        self.assertEqual(result["location"], "Conference Room")


if __name__ == "__main__":
    unittest.main()
