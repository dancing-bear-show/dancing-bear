"""Tests for scan_common.py helper functions."""
import unittest

from calendars.constants import DAY_MAP
from calendars.scan_common import (
    html_to_text,
    norm_time,
    infer_meta_from_text,
    MONTH_MAP,
)


class TestHtmlToText(unittest.TestCase):
    def test_strips_simple_tags(self):
        self.assertEqual(html_to_text('<p>Hello</p>'), 'Hello')

    def test_converts_br_to_newline(self):
        self.assertEqual(html_to_text('Line1<br>Line2'), 'Line1 Line2')
        self.assertEqual(html_to_text('Line1<br/>Line2'), 'Line1 Line2')

    def test_converts_p_to_newline(self):
        result = html_to_text('<p>Para1</p><p>Para2</p>')
        self.assertIn('Para1', result)
        self.assertIn('Para2', result)

    def test_unescapes_html_entities(self):
        self.assertEqual(html_to_text('&amp; &lt; &gt;'), '& < >')
        self.assertEqual(html_to_text('&nbsp;test'), 'test')

    def test_collapses_whitespace(self):
        self.assertEqual(html_to_text('  multiple   spaces  '), 'multiple spaces')

    def test_empty_returns_empty(self):
        self.assertEqual(html_to_text(''), '')
        self.assertEqual(html_to_text(None), '')


class TestNormTime(unittest.TestCase):
    def test_basic_time(self):
        self.assertEqual(norm_time('9', '30', None), '09:30')
        self.assertEqual(norm_time('14', '00', None), '14:00')

    def test_pm_conversion(self):
        self.assertEqual(norm_time('3', '45', 'pm'), '15:45')
        self.assertEqual(norm_time('3', '45', 'p.m.'), '15:45')

    def test_am_conversion(self):
        self.assertEqual(norm_time('9', '00', 'am'), '09:00')
        self.assertEqual(norm_time('9', '00', 'a.m.'), '09:00')

    def test_noon(self):
        self.assertEqual(norm_time('12', '00', 'pm'), '12:00')

    def test_midnight(self):
        self.assertEqual(norm_time('12', '00', 'am'), '00:00')

    def test_no_minutes(self):
        self.assertEqual(norm_time('5', None, 'pm'), '17:00')

    def test_12_pm_stays_12(self):
        self.assertEqual(norm_time('12', '30', 'pm'), '12:30')

    def test_11_pm_becomes_23(self):
        self.assertEqual(norm_time('11', '00', 'pm'), '23:00')


class TestInferMetaFromText(unittest.TestCase):
    def test_extracts_location_from_facilities(self):
        text = "Your class is at Ed Sackfield Arena on Monday"
        meta = infer_meta_from_text(text)
        self.assertEqual(meta.get('location'), 'Ed Sackfield')

    def test_extracts_location_from_label(self):
        text = "Location: Richmond Green Community Centre"
        meta = infer_meta_from_text(text)
        self.assertEqual(meta.get('location'), 'Richmond Green Community Centre')

    def test_extracts_date_range(self):
        text = "Session runs from January 15, 2025 to March 30, 2025"
        meta = infer_meta_from_text(text, default_year=2025)
        self.assertIn('range', meta)
        self.assertEqual(meta['range']['start_date'], '2025-01-15')
        self.assertEqual(meta['range']['until'], '2025-03-30')

    def test_extracts_date_range_abbreviated_months(self):
        text = "Jan 5 to Feb 28, 2025"
        meta = infer_meta_from_text(text, default_year=2025)
        self.assertIn('range', meta)
        self.assertEqual(meta['range']['start_date'], '2025-01-05')
        self.assertEqual(meta['range']['until'], '2025-02-28')

    def test_extracts_class_name_swimmer(self):
        text = "Swimmer 5 - Monday 4:00pm"
        meta = infer_meta_from_text(text)
        self.assertIn('subject', meta)
        self.assertIn('Swimmer', meta['subject'])

    def test_extracts_class_name_swim_kids(self):
        text = "Swim Kids 3 class starts next week"
        meta = infer_meta_from_text(text)
        self.assertIn('subject', meta)
        self.assertIn('Swim Kids', meta['subject'])

    def test_extracts_class_name_bronze(self):
        text = "Bronze Medallion course available"
        meta = infer_meta_from_text(text)
        self.assertIn('subject', meta)
        self.assertIn('Bronze Medallion', meta['subject'])

    def test_extracts_class_name_preschool(self):
        text = "Preschool A swimming lessons"
        meta = infer_meta_from_text(text)
        self.assertIn('subject', meta)
        self.assertIn('Preschool', meta['subject'])

    def test_empty_text_returns_empty_dict(self):
        self.assertEqual(infer_meta_from_text(''), {})
        self.assertEqual(infer_meta_from_text(None), {})

    def test_no_matches_returns_empty_dict(self):
        text = "This is generic text with no schedule info"
        meta = infer_meta_from_text(text)
        self.assertEqual(meta, {})


class TestDayMap(unittest.TestCase):
    def test_full_day_names(self):
        self.assertEqual(DAY_MAP['monday'], 'MO')
        self.assertEqual(DAY_MAP['tuesday'], 'TU')
        self.assertEqual(DAY_MAP['wednesday'], 'WE')
        self.assertEqual(DAY_MAP['thursday'], 'TH')
        self.assertEqual(DAY_MAP['friday'], 'FR')
        self.assertEqual(DAY_MAP['saturday'], 'SA')
        self.assertEqual(DAY_MAP['sunday'], 'SU')

    def test_abbreviated_day_names(self):
        self.assertEqual(DAY_MAP['mon'], 'MO')
        self.assertEqual(DAY_MAP['tue'], 'TU')
        self.assertEqual(DAY_MAP['wed'], 'WE')
        self.assertEqual(DAY_MAP['thu'], 'TH')
        self.assertEqual(DAY_MAP['fri'], 'FR')
        self.assertEqual(DAY_MAP['sat'], 'SA')
        self.assertEqual(DAY_MAP['sun'], 'SU')

    def test_alternate_abbreviations(self):
        self.assertEqual(DAY_MAP['tues'], 'TU')
        self.assertEqual(DAY_MAP['thur'], 'TH')
        self.assertEqual(DAY_MAP['thurs'], 'TH')


class TestMonthMap(unittest.TestCase):
    def test_full_month_names(self):
        self.assertEqual(MONTH_MAP['january'], 1)
        self.assertEqual(MONTH_MAP['december'], 12)

    def test_abbreviated_month_names(self):
        self.assertEqual(MONTH_MAP['jan'], 1)
        self.assertEqual(MONTH_MAP['feb'], 2)
        self.assertEqual(MONTH_MAP['dec'], 12)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
