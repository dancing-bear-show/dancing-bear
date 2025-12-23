import unittest

from calendar_assistant.selection import compute_window, filter_events_by_day_time


class TestSelectionHelpers(unittest.TestCase):
    def test_compute_window_from_range(self):
        ev = {
            'range': {'start_date': '2025-01-01', 'until': '2025-02-01'}
        }
        start, end = compute_window(ev)
        self.assertEqual(start, '2025-01-01T00:00:00')
        self.assertEqual(end, '2025-02-01T23:59:59')

    def test_compute_window_single_day(self):
        ev = {'range': {'start_date': '2025-01-15'}}
        start, end = compute_window(ev)
        self.assertEqual(start, '2025-01-15T00:00:00')
        self.assertEqual(end, '2025-01-15T23:59:59')

    def test_compute_window_from_start_end(self):
        ev = {'start': '2025-01-06T17:00:00+00:00', 'end': '2025-01-06T17:30:00+00:00'}
        start, end = compute_window(ev)
        self.assertEqual(start, '2025-01-06T17:00:00+00:00')
        self.assertEqual(end, '2025-01-06T17:30:00+00:00')

    def test_filter_events_by_day_time(self):
        # Monday Jan 6, 2025
        evs = [{
            'start': {'dateTime': '2025-01-06T17:00:00+00:00'},
            'end': {'dateTime': '2025-01-06T17:30:00+00:00'},
        }, {
            'start': {'dateTime': '2025-01-07T17:00:00+00:00'},
            'end': {'dateTime': '2025-01-07T17:30:00+00:00'},
        }]
        matches = filter_events_by_day_time(evs, byday=['MO'], start_time='17:00', end_time='17:30')
        self.assertEqual(len(matches), 1)

    def test_filter_byday_only(self):
        evs = [
            {'start': {'dateTime': '2025-01-06T10:00:00+00:00'}, 'end': {'dateTime': '2025-01-06T11:00:00+00:00'}},
            {'start': {'dateTime': '2025-01-07T10:00:00+00:00'}, 'end': {'dateTime': '2025-01-07T11:00:00+00:00'}},
        ]
        matches = filter_events_by_day_time(evs, byday=['MO'])
        self.assertEqual(len(matches), 1)

    def test_filter_time_only(self):
        evs = [
            {'start': {'dateTime': '2025-01-06T10:00:00+00:00'}, 'end': {'dateTime': '2025-01-06T11:00:00+00:00'}},
            {'start': {'dateTime': '2025-01-07T10:00:00+00:00'}, 'end': {'dateTime': '2025-01-07T11:00:00+00:00'}},
        ]
        matches = filter_events_by_day_time(evs, start_time='10:00', end_time='11:00')
        self.assertEqual(len(matches), 2)

    def test_timezone_offset_times(self):
        evs = [
            {'start': {'dateTime': '2025-01-06T17:00:00-05:00'}, 'end': {'dateTime': '2025-01-06T17:30:00-05:00'}},
        ]
        matches = filter_events_by_day_time(evs, start_time='17:00', end_time='17:30')
        self.assertEqual(len(matches), 1)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
