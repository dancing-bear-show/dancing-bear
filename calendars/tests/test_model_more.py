import unittest

from calendars.model import normalize_event


class TestModelExtras(unittest.TestCase):
    def test_exdates_string_and_list(self):
        e1 = normalize_event({'subject':'A','exdates':'2025-01-01,2025-01-02'})
        self.assertEqual(e1.get('exdates'), ['2025-01-01','2025-01-02'])
        e2 = normalize_event({'subject':'A','exceptions':['2025-03-01','2025-03-02']})
        self.assertEqual(e2.get('exdates'), ['2025-03-01','2025-03-02'])

    def test_byday_range_words(self):
        # Accept partial words and generate codes; order not strictly enforced here
        e = normalize_event({'subject':'A','repeat':'weekly','byday':'monday,thursday'})
        self.assertEqual(e.get('byday'), ['MO','TH'])

    def test_reminder_variants(self):
        e = normalize_event({'subject':'A','reminder':'on','reminderMinutes':'10'})
        self.assertTrue(e.get('is_reminder_on'))
        self.assertEqual(e.get('reminder_minutes'), 10)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

