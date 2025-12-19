import unittest


class TestRecurringExpandFallback(unittest.TestCase):

    def test_weekly_expand_uses_window_when_range_missing(self):
        from schedule_assistant import __main__ as sa
        ev = {
            "subject": "Test",
            "repeat": "weekly",
            "byday": ["WE"],
            "start_time": "08:30",
            "end_time": "09:30",
            # no range provided
        }
        occ = sa._expand_recurring_occurrences(ev, "2025-10-01", "2025-10-31")
        # Expect at least the Wednesdays in October 2025: 1,8,15,22,29
        self.assertGreaterEqual(len(occ), 5)
        starts = {s for s, _ in occ}
        self.assertIn("2025-10-01T08:30", starts)
        self.assertIn("2025-10-29T08:30", starts)


if __name__ == "__main__":
    unittest.main()

