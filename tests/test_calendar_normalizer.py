import unittest

from calendars.model import normalize_event


class NormalizeEventTests(unittest.TestCase):
    def test_normalize_recurring_with_aliases(self):
        raw = {
            "subject": "Swim Kids 4",
            "calendar": "Your Family",
            "tz": "America/Toronto",
            "repeat": "weekly",
            "interval": "1",
            "byDay": ["Mon", "wednesday"],
            "startTime": "17:30",
            "endTime": "18:15",
            "range": {"startDate": "2025-01-10", "until": "2025-03-10"},
            "exceptions": ["2025-02-17"],
        }
        ev = normalize_event(raw)
        self.assertEqual(ev["subject"], "Swim Kids 4")
        self.assertEqual(ev["calendar"], "Your Family")
        self.assertEqual(ev["tz"], "America/Toronto")
        self.assertEqual(ev["repeat"], "weekly")
        self.assertEqual(ev["interval"], 1)
        self.assertEqual(ev["byday"], ["MO", "WE"])
        self.assertEqual(ev["start_time"], "17:30")
        self.assertEqual(ev["end_time"], "18:15")
        self.assertEqual(ev["range"], {"start_date": "2025-01-10", "until": "2025-03-10"})
        self.assertEqual(ev["exdates"], ["2025-02-17"])

    def test_normalize_single_event(self):
        raw = {
            "subject": "Tournament",
            "start": "2025-02-03T09:00:00",
            "end": "2025-02-03T11:00:00",
            "bodyHtml": "<b>Go team</b>",
        }
        ev = normalize_event(raw)
        self.assertEqual(ev["subject"], "Tournament")
        self.assertEqual(ev["start"], "2025-02-03T09:00:00")
        self.assertEqual(ev["end"], "2025-02-03T11:00:00")
        # body_html preserves HTML; parsing/stripping is handled by callers if needed
        self.assertEqual(ev["body_html"], "<b>Go team</b>")
