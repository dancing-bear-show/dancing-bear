"""Tests for importer helper functions (time/day parsing)."""
import unittest

from calendars.importer import (
    strip_html_tags,
    normalize_day,
    normalize_days,
    to_24h,
    parse_time_range,
    extract_time_ranges,
)


class TestStripHtmlTags(unittest.TestCase):
    def test_removes_simple_tags(self):
        self.assertEqual(strip_html_tags('<p>Hello</p>'), 'Hello')

    def test_removes_nested_tags(self):
        self.assertEqual(strip_html_tags('<div><span>Text</span></div>'), 'Text')

    def test_normalizes_nbsp(self):
        self.assertEqual(strip_html_tags('Hello\xa0World'), 'Hello World')
        self.assertEqual(strip_html_tags('Hello&nbsp;World'), 'Hello World')

    def test_strips_whitespace(self):
        self.assertEqual(strip_html_tags('  <p>Trim</p>  '), 'Trim')


class TestNormalizeDay(unittest.TestCase):
    def test_full_day_names(self):
        self.assertEqual(normalize_day('Monday'), 'MO')
        self.assertEqual(normalize_day('Tuesday'), 'TU')
        self.assertEqual(normalize_day('Wednesday'), 'WE')
        self.assertEqual(normalize_day('Thursday'), 'TH')
        self.assertEqual(normalize_day('Friday'), 'FR')
        self.assertEqual(normalize_day('Saturday'), 'SA')
        self.assertEqual(normalize_day('Sunday'), 'SU')

    def test_case_insensitive(self):
        self.assertEqual(normalize_day('MONDAY'), 'MO')
        self.assertEqual(normalize_day('friday'), 'FR')

    def test_strips_whitespace(self):
        self.assertEqual(normalize_day('  Monday  '), 'MO')

    def test_unknown_returns_empty(self):
        self.assertEqual(normalize_day('Funday'), '')
        self.assertEqual(normalize_day(''), '')


class TestNormalizeDays(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(normalize_days('Monday'), ['MO'])
        self.assertEqual(normalize_days('Fri'), ['FR'])

    def test_day_range_with_to(self):
        self.assertEqual(normalize_days('Mon to Fri'), ['MO', 'TU', 'WE', 'TH', 'FR'])

    def test_day_range_with_dash(self):
        self.assertEqual(normalize_days('Mon-Fri'), ['MO', 'TU', 'WE', 'TH', 'FR'])

    def test_day_range_wrap_around(self):
        # Fri to Mon wraps around the weekend
        self.assertEqual(normalize_days('Fri to Mon'), ['FR', 'SA', 'SU', 'MO'])

    def test_multiple_days_with_ampersand(self):
        result = normalize_days('Mon & Wed')
        self.assertIn('MO', result)
        self.assertIn('WE', result)

    def test_handles_full_day_names(self):
        self.assertEqual(normalize_days('Monday'), ['MO'])
        self.assertEqual(normalize_days('Saturday'), ['SA'])

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_days(''), [])
        self.assertEqual(normalize_days(None), [])


class TestTo24h(unittest.TestCase):
    def test_pm_conversion(self):
        self.assertEqual(to_24h('1:45 p.m.'), '13:45')
        self.assertEqual(to_24h('3:15 pm'), '15:15')

    def test_am_conversion(self):
        self.assertEqual(to_24h('9:00 a.m.'), '09:00')
        self.assertEqual(to_24h('11:30 am'), '11:30')

    def test_noon(self):
        self.assertEqual(to_24h('12:00 p.m.'), '12:00')

    def test_midnight(self):
        self.assertEqual(to_24h('12:00 a.m.'), '00:00')

    def test_no_minutes(self):
        self.assertEqual(to_24h('7 p.m.'), '19:00')
        self.assertEqual(to_24h('9 a.m.'), '09:00')

    def test_explicit_ampm_override(self):
        self.assertEqual(to_24h('7:00', 'pm'), '19:00')
        self.assertEqual(to_24h('7:00', 'am'), '07:00')

    def test_heuristic_without_ampm(self):
        # Hours 7-11 without am/pm assume PM
        self.assertEqual(to_24h('7:00'), '19:00')
        self.assertEqual(to_24h('11:00'), '23:00')
        # Hours outside 7-11 assume AM
        self.assertEqual(to_24h('6:00'), '06:00')

    def test_invalid_returns_none(self):
        self.assertIsNone(to_24h(''))
        self.assertIsNone(to_24h('invalid'))
        self.assertIsNone(to_24h('abc:def'))


class TestParseTimeRange(unittest.TestCase):
    def test_pm_range(self):
        self.assertEqual(parse_time_range('1:45 - 3:15 p.m.'), ('13:45', '15:15'))

    def test_am_to_pm_range(self):
        self.assertEqual(parse_time_range('11:15 a.m. - 12:15 p.m.'), ('11:15', '12:15'))

    def test_no_minutes_range(self):
        self.assertEqual(parse_time_range('7 - 8:30 p.m.'), ('19:00', '20:30'))

    def test_em_dash_separator(self):
        self.assertEqual(parse_time_range('7:15 – 8:45 p.m.'), ('19:15', '20:45'))

    def test_to_separator(self):
        self.assertEqual(parse_time_range('9:00 a.m. to 10:00 a.m.'), ('09:00', '10:00'))

    def test_empty_returns_none_tuple(self):
        self.assertEqual(parse_time_range(''), (None, None))
        self.assertEqual(parse_time_range('\xa0'), (None, None))

    def test_invalid_format_returns_none_tuple(self):
        self.assertEqual(parse_time_range('just text'), (None, None))
        self.assertEqual(parse_time_range('1:00'), (None, None))  # no range


class TestExtractTimeRanges(unittest.TestCase):
    def test_single_range(self):
        result = extract_time_ranges('10:00 a.m. - 12:00 p.m.')
        self.assertEqual(result, [('10:00', '12:00')])

    def test_multiple_ranges(self):
        result = extract_time_ranges('9:00am - 10:30am and 2:00pm - 3:30pm')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ('09:00', '10:30'))
        self.assertEqual(result[1], ('14:00', '15:30'))

    def test_with_asterisks(self):
        result = extract_time_ranges('*10:00 a.m. - 11:00 a.m.*')
        self.assertEqual(result, [('10:00', '11:00')])

    def test_empty_returns_empty_list(self):
        self.assertEqual(extract_time_ranges(''), [])
        self.assertEqual(extract_time_ranges(None), [])

    def test_no_valid_ranges_returns_empty(self):
        self.assertEqual(extract_time_ranges('no times here'), [])


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
