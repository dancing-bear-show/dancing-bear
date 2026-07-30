import unittest

from calendars.model import normalize_event


class TestNormalizeEvent(unittest.TestCase):
    def test_byday_variants(self):
        ev = normalize_event({
            'subject': 'Test',
            'repeat': 'weekly',
            'byday': 'Mon, wed'
        })
        self.assertEqual(ev.get('byday'), ['MO', 'WE'])

        ev2 = normalize_event({
            'subject': 'Test',
            'repeat': 'weekly',
            'byDay': 'monday,friday'
        })
        self.assertEqual(ev2.get('byday'), ['MO', 'FR'])

    def test_range_aliases(self):
        ev = normalize_event({
            'subject': 'Test',
            'range': {'startDate': '2025-01-01', 'until': '2025-02-01'}
        })
        self.assertEqual(ev.get('range'), {'start_date': '2025-01-01', 'until': '2025-02-01'})

        ev2 = normalize_event({
            'subject': 'Test',
            'startDate': '2025-03-01',
            'endDate': '2025-03-31'
        })
        self.assertEqual(ev2.get('range'), {'start_date': '2025-03-01', 'until': '2025-03-31'})

    def test_reminder_fields(self):
        ev = normalize_event({'subject': 'A', 'isReminderOn': 'off', 'reminder-minutes': '15'})
        self.assertFalse(ev.get('is_reminder_on'))
        self.assertEqual(ev.get('reminder_minutes'), 15)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

