import unittest

from calendars.model import normalize_event, _coerce_str, _normalize_byday, _normalize_range


class TestCoerceStr(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(_coerce_str('hello'), 'hello')

    def test_strips_whitespace(self):
        self.assertEqual(_coerce_str('  hello  '), 'hello')

    def test_none_returns_none(self):
        self.assertIsNone(_coerce_str(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_coerce_str(''))
        self.assertIsNone(_coerce_str('   '))

    def test_converts_number_to_string(self):
        self.assertEqual(_coerce_str(123), '123')
        self.assertEqual(_coerce_str(3.14), '3.14')


class TestNormalizeByday(unittest.TestCase):
    def test_list_of_codes(self):
        self.assertEqual(_normalize_byday(['MO', 'TU']), ['MO', 'TU'])

    def test_comma_separated_string(self):
        self.assertEqual(_normalize_byday('MO,TU,WE'), ['MO', 'TU', 'WE'])

    def test_space_separated_string(self):
        self.assertEqual(_normalize_byday('MO TU WE'), ['MO', 'TU', 'WE'])

    def test_semicolon_separated_string(self):
        self.assertEqual(_normalize_byday('MO;TU;WE'), ['MO', 'TU', 'WE'])

    def test_full_day_names(self):
        self.assertEqual(_normalize_byday('Monday,Tuesday'), ['MO', 'TU'])

    def test_abbreviated_day_names(self):
        self.assertEqual(_normalize_byday('mon,tue,wed'), ['MO', 'TU', 'WE'])

    def test_alternate_abbreviations(self):
        # 'thur' and 'thurs' both map to 'TH', duplicates removed
        self.assertEqual(_normalize_byday('tues,thur,thurs'), ['TU', 'TH'])

    def test_removes_duplicates(self):
        self.assertEqual(_normalize_byday('MO,MO,TU,TU'), ['MO', 'TU'])

    def test_empty_returns_none(self):
        self.assertIsNone(_normalize_byday(''))
        self.assertIsNone(_normalize_byday(None))
        self.assertIsNone(_normalize_byday([]))

    def test_mixed_case(self):
        self.assertEqual(_normalize_byday('Monday,TUESDAY,wednesday'), ['MO', 'TU', 'WE'])


class TestNormalizeRange(unittest.TestCase):
    def test_range_dict_with_snake_case(self):
        ev = {'range': {'start_date': '2025-01-01', 'until': '2025-02-01'}}
        result = _normalize_range(ev)
        self.assertEqual(result, {'start_date': '2025-01-01', 'until': '2025-02-01'})

    def test_range_dict_with_camel_case(self):
        ev = {'range': {'startDate': '2025-01-01', 'endDate': '2025-02-01'}}
        result = _normalize_range(ev)
        self.assertEqual(result, {'start_date': '2025-01-01', 'until': '2025-02-01'})

    def test_top_level_date_fields(self):
        ev = {'start_date': '2025-03-01', 'until': '2025-03-31'}
        result = _normalize_range(ev)
        self.assertEqual(result, {'start_date': '2025-03-01', 'until': '2025-03-31'})

    def test_only_start_date(self):
        ev = {'start_date': '2025-01-01'}
        result = _normalize_range(ev)
        self.assertEqual(result, {'start_date': '2025-01-01'})

    def test_only_until(self):
        ev = {'until': '2025-12-31'}
        result = _normalize_range(ev)
        self.assertEqual(result, {'until': '2025-12-31'})

    def test_empty_returns_none(self):
        self.assertIsNone(_normalize_range({}))
        self.assertIsNone(_normalize_range({'range': {}}))


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

