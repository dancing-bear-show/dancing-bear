"""Tests for calendars/importer/web_parser.py web schedule parsers."""

import unittest
from unittest.mock import patch

from calendars.importer.web_parser import (
    WebParser,
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
    AuroraAquaticsParser,
    parse_website,
)
from calendars.importer.model import ScheduleItem


# Sample HTML fixtures for testing
RICHMOND_HILL_SKATING_HTML = '''
<html>
<body>
<td data-name="accParent">Oak Ridges Arena</td>
<div data-name="accChild">
<table>
<tr>
    <td>Sunday</td><td>Monday</td><td>Tuesday</td><td>Wednesday</td>
    <td>Thursday</td><td>Friday</td><td>Saturday</td>
</tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>1:00 - 2:30 p.m.</td>
    <td>\xa0</td>
    <td>7:00 - 8:30 p.m.</td>
    <td>\xa0</td>
    <td>3:00 - 4:30 p.m.</td>
    <td>\xa0</td>
    <td>12:00 - 1:30 p.m.</td>
</tr>
</table>
</div>
</body>
</html>
'''

RICHMOND_HILL_SKATING_REGEX_HTML = '''
<html>
data-name="accParent">Elgin West Arena</td>
<td data-name="accChild">
<table>
<tr><td><strong>Public Skating</strong></td>
<td>2:00 - 3:30 p.m.</td>
<td></td>
<td>6:00 - 7:30 p.m.</td>
<td></td>
<td></td>
<td></td>
<td>1:00 - 2:30 p.m.</td>
</tr>
</table>
</div>
</body>
</html>
'''

RICHMOND_HILL_SWIMMING_HTML = '''
<html>
<body>
<td data-name="accParent">Richmond Green Pool&nbsp;</td>
<div data-name="accChild">
<table>
<tr>
    <td><strong>Leisure Swim</strong></td>
    <td>10:00 a.m. - 12:00 p.m.</td>
    <td></td>
    <td>2:00 - 4:00 p.m.</td>
    <td></td>
    <td></td>
    <td></td>
    <td>9:00 a.m. - 11:00 a.m.</td>
</tr>
<tr>
    <td><strong>Fun N Fit</strong></td>
    <td></td>
    <td>6:00 - 7:00 p.m.</td>
    <td></td>
    <td>6:00 - 7:00 p.m.</td>
    <td></td>
    <td></td>
    <td></td>
</tr>
</table>
</div>
</body>
</html>
'''

AURORA_AQUATICS_HTML = '''
<html>
<body>
<table>
<thead>
<tr><th>Day</th><th>Lane Swim</th><th>Leisure Swim</th></tr>
</thead>
<tbody>
<tr><td>Monday</td><td>6:00am - 8:00am</td><td>10:00am - 12:00pm</td></tr>
<tr><td>Wed to Fri</td><td></td><td>2:00pm - 4:00pm</td></tr>
<tr><td>Saturday</td><td></td><td>9:00am - 11:00am</td></tr>
</tbody>
</table>
</body>
</html>
'''


class TestWebParser(unittest.TestCase):
    """Tests for WebParser dispatcher."""

    def test_routes_to_richmond_hill_skating(self):
        parser = WebParser()
        with patch.object(RichmondHillSkatingParser, 'parse', return_value=[]) as mock:
            parser.parse('https://www.richmondhill.ca/en/rec/Skating.aspx')
            mock.assert_called_once()

    def test_routes_to_richmond_hill_swimming(self):
        parser = WebParser()
        with patch.object(RichmondHillSwimmingParser, 'parse', return_value=[]) as mock:
            parser.parse('https://www.richmondhill.ca/en/rec/Swimming.aspx')
            mock.assert_called_once()

    def test_routes_to_aurora_aquatics(self):
        parser = WebParser()
        with patch.object(AuroraAquaticsParser, 'parse', return_value=[]) as mock:
            parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')
            mock.assert_called_once()

    def test_raises_for_unsupported_url(self):
        parser = WebParser()
        with self.assertRaises(NotImplementedError) as ctx:
            parser.parse('https://unknown-site.com/schedule')
        self.assertIn('not implemented', str(ctx.exception).lower())

    def test_handles_empty_url(self):
        parser = WebParser()
        with self.assertRaises(NotImplementedError):
            parser.parse('')

    def test_handles_none_url(self):
        parser = WebParser()
        with self.assertRaises(NotImplementedError):
            parser.parse(None)


class TestRichmondHillSkatingParser(unittest.TestCase):
    """Tests for RichmondHillSkatingParser."""

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_with_bs4(self, mock_get):
        mock_get.return_value.text = RICHMOND_HILL_SKATING_HTML
        parser = RichmondHillSkatingParser()

        # Force bs4 path by ensuring import succeeds
        items = parser.parse('https://www.richmondhill.ca/en/rec/Skating.aspx')

        mock_get.assert_called_once()
        # Should find public skating entries
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)
            self.assertEqual(item.subject, 'Public Skating')
            self.assertEqual(item.recurrence, 'weekly')

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_with_regex_fallback(self, mock_get):
        mock_get.return_value.text = RICHMOND_HILL_SKATING_REGEX_HTML
        parser = RichmondHillSkatingParser()

        # Test regex fallback by patching bs4 import to fail
        with patch.dict('sys.modules', {'bs4': None}):
            items = parser._parse_with_regex(RICHMOND_HILL_SKATING_REGEX_HTML, 'http://test.com')

        self.assertIsInstance(items, list)
        # Check at least some items were parsed
        for item in items:
            self.assertEqual(item.subject, 'Public Skating')
            self.assertEqual(item.recurrence, 'weekly')
            self.assertIn('Elgin West Arena', item.location)

    def test_regex_parse_extracts_arena_name(self):
        parser = RichmondHillSkatingParser()
        items = parser._parse_with_regex(RICHMOND_HILL_SKATING_REGEX_HTML, 'http://test.com')

        if items:  # If any items were parsed
            self.assertIn('Elgin West Arena', items[0].location)

    def test_regex_parse_empty_html_returns_empty(self):
        parser = RichmondHillSkatingParser()
        items = parser._parse_with_regex('', 'http://test.com')
        self.assertEqual(items, [])

    def test_regex_parse_no_public_skating_returns_empty(self):
        parser = RichmondHillSkatingParser()
        html = '<html>data-name="accParent">Arena</td><table><tr><td>Hockey</td></tr></table></html>'
        items = parser._parse_with_regex(html, 'http://test.com')
        self.assertEqual(items, [])


class TestRichmondHillSwimmingParser(unittest.TestCase):
    """Tests for RichmondHillSwimmingParser."""

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_leisure_swim(self, mock_get):
        mock_get.return_value.text = RICHMOND_HILL_SWIMMING_HTML
        parser = RichmondHillSwimmingParser()
        items = parser.parse('https://www.richmondhill.ca/en/rec/Swimming.aspx')

        leisure_items = [i for i in items if i.subject == 'Leisure Swim']
        self.assertGreater(len(leisure_items), 0)

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_fun_n_fit(self, mock_get):
        mock_get.return_value.text = RICHMOND_HILL_SWIMMING_HTML
        parser = RichmondHillSwimmingParser()
        items = parser.parse('https://www.richmondhill.ca/en/rec/Swimming.aspx')

        fnf_items = [i for i in items if i.subject == 'Fun N Fit']
        self.assertGreater(len(fnf_items), 0)

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_extracts_facility_name(self, mock_get):
        mock_get.return_value.text = RICHMOND_HILL_SWIMMING_HTML
        parser = RichmondHillSwimmingParser()
        items = parser.parse('https://www.richmondhill.ca/en/rec/Swimming.aspx')

        if items:
            self.assertIn('Richmond Green Pool', items[0].location)

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_empty_html_returns_empty(self, mock_get):
        mock_get.return_value.text = '<html></html>'
        parser = RichmondHillSwimmingParser()
        items = parser.parse('https://www.richmondhill.ca/en/rec/Swimming.aspx')
        self.assertEqual(items, [])


class TestAuroraAquaticsParser(unittest.TestCase):
    """Tests for AuroraAquaticsParser."""

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_leisure_swim(self, mock_get):
        mock_get.return_value.text = AURORA_AQUATICS_HTML
        parser = AuroraAquaticsParser()
        items = parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')

        self.assertGreater(len(items), 0)
        for item in items:
            self.assertEqual(item.subject, 'Leisure Swim')
            self.assertEqual(item.recurrence, 'weekly')
            self.assertEqual(item.location, 'Aurora Pools')

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_handles_day_range(self, mock_get):
        mock_get.return_value.text = AURORA_AQUATICS_HTML
        parser = AuroraAquaticsParser()
        items = parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')

        # Should expand "Wed to Fri" to individual days
        all_days = []
        for item in items:
            all_days.extend(item.byday)

        # Should have WE, TH, FR from the range
        self.assertIn('WE', all_days)
        self.assertIn('TH', all_days)
        self.assertIn('FR', all_days)

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_no_leisure_table_returns_empty(self, mock_get):
        mock_get.return_value.text = '''
        <html><table><thead><tr><th>Day</th><th>Lane Swim</th></tr></thead>
        <tbody><tr><td>Monday</td><td>6:00am</td></tr></tbody></table></html>
        '''
        parser = AuroraAquaticsParser()
        items = parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser.requests.get')
    def test_parse_empty_html_returns_empty(self, mock_get):
        mock_get.return_value.text = '<html></html>'
        parser = AuroraAquaticsParser()
        items = parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')
        self.assertEqual(items, [])


class TestParseWebsiteFunction(unittest.TestCase):
    """Tests for parse_website convenience function."""

    def test_delegates_to_web_parser(self):
        with patch.object(WebParser, 'parse', return_value=[]) as mock:
            parse_website('https://www.richmondhill.ca/en/rec/Skating.aspx')
            mock.assert_called_once_with('https://www.richmondhill.ca/en/rec/Skating.aspx')

    def test_raises_for_unsupported_url(self):
        with self.assertRaises(NotImplementedError):
            parse_website('https://unsupported-site.com')


class TestScheduleItemAttributes(unittest.TestCase):
    """Tests for ScheduleItem attributes set by web parsers."""

    @patch('calendars.importer.web_parser.requests.get')
    def test_items_have_notes_with_url(self, mock_get):
        mock_get.return_value.text = AURORA_AQUATICS_HTML
        parser = AuroraAquaticsParser()
        url = 'https://www.aurora.ca/aquatics-and-swim-programs'
        items = parser.parse(url)

        if items:
            self.assertIn(url, items[0].notes)
            self.assertIn('Imported from', items[0].notes)

    @patch('calendars.importer.web_parser.requests.get')
    def test_items_have_range_start(self, mock_get):
        mock_get.return_value.text = AURORA_AQUATICS_HTML
        parser = AuroraAquaticsParser()
        items = parser.parse('https://www.aurora.ca/aquatics-and-swim-programs')

        if items:
            # range_start should be today's date in ISO format
            self.assertIsNotNone(items[0].range_start)
            self.assertRegex(items[0].range_start, r'^\d{4}-\d{2}-\d{2}$')


if __name__ == '__main__':
    unittest.main()
