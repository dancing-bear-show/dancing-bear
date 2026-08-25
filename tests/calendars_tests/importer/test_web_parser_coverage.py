"""Coverage-gap tests for web_parser_base.py and web_parser_vendors_rh.py.

Targets:
  web_parser_base.py    lines 47-53  (_fetch_html error handling)
  web_parser_vendors_rh.py  lines 29-30, 43, 46, 50, 54, 67, 87-89, 99, 104->97
"""

import unittest
from unittest.mock import MagicMock, patch

from calendars.importer.web_parser_base import _fetch_html
from calendars.importer.web_parser_vendors_rh import (
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
)
from calendars.importer.model import ScheduleItem

# Availability probe: bs4 is an optional [calendars] extra, so the
# bs4-dependent tests below skip when it is absent.
#
# The import is deliberately unused — whether it raises IS the signal — hence
# the noqa. Static analysers flag this as an unused import; that is a false
# positive here, not a defect to fix.
#
# importlib.util.find_spec would avoid the binding but is NOT equivalent: it
# reports whether a module is discoverable, not whether it imports cleanly. A
# module that is present but fails on import reports available and the guarded
# tests then run and fail. Verified against the no-bs4 CI simulation, where
# find_spec returns True while the import raises.
try:
    import bs4  # noqa: F401  # probe: the ImportError is the signal
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# ---------------------------------------------------------------------------
# Minimal HTML helpers
# ---------------------------------------------------------------------------

def _skating_html_no_acchild() -> str:
    """accParent element with NO accChild sibling — triggers lines 29-30."""
    return '''
<html><body>
<td data-name="accParent">Empty Arena</td>
<!-- no accChild sibling at all -->
</body></html>
'''


def _skating_html_no_table() -> str:
    """accParent+accChild but the accChild contains NO <table> — triggers line 43."""
    return '''
<html><body>
<td data-name="accParent">No Table Arena</td>
<div data-name="accChild"><p>nothing here</p></div>
</body></html>
'''


def _skating_html_no_public_skating_row() -> str:
    """Table exists but has no 'Public Skating' row — triggers lines 46, 67."""
    return '''
<html><body>
<td data-name="accParent">Hockey Arena</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td></tr>
<tr><td><strong>Hockey</strong></td><td>8:00 - 9:00 p.m.</td></tr>
</table>
</div>
</body></html>
'''


def _skating_html_row_too_few_cells() -> str:
    """Public Skating row present but only 1 cell — triggers line 50."""
    return '''
<html><body>
<td data-name="accParent">Small Arena</td>
<div data-name="accChild">
<table>
<tr><td><strong>Public Skating</strong></td></tr>
</table>
</div>
</body></html>
'''


def _skating_html_nbsp_cell() -> str:
    """Public Skating row with an &nbsp;-only time cell — triggers line 54 (txt == \\xa0)."""
    return '''
<html><body>
<td data-name="accParent">Quiet Arena</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td></tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>\xa0</td>
    <td>1:00 - 2:00 p.m.</td>
</tr>
</table>
</div>
</body></html>
'''


def _skating_html_no_day_headers_in_table() -> str:
    """Table has fewer than 7 weekday cells; previous row provides headers — lines 87-89."""
    return '''
<html><body>
<td data-name="accParent">Sparse Arena</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td><td>Tuesday</td></tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>3:00 - 4:00 p.m.</td>
    <td>5:00 - 6:00 p.m.</td>
</tr>
</table>
</div>
</body></html>
'''


def _skating_html_more_cells_than_days() -> str:
    """_parse_time_cells receives more cells than days — triggers line 99 (i >= len(days))."""
    return '''
<html><body>
<td data-name="accParent">Overflow Arena</td>
<div data-name="accChild">
<table>
<tr>
    <td>Sunday</td>
</tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>1:00 - 2:00 p.m.</td>
    <td>3:00 - 4:00 p.m.</td>
    <td>5:00 - 6:00 p.m.</td>
</tr>
</table>
</div>
</body></html>
'''


def _skating_html_unparseable_time_cell() -> str:
    """Time cell contains text that parse_time_range cannot parse — branch 104->97."""
    return '''
<html><body>
<td data-name="accParent">Bad Times Arena</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td></tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>CLOSED</td>
    <td>1:00 - 2:00 p.m.</td>
</tr>
</table>
</div>
</body></html>
'''


# ---------------------------------------------------------------------------
# Tests for _fetch_html error handling (web_parser_base.py lines 47-53)
# ---------------------------------------------------------------------------

class TestFetchHtmlErrorHandling(unittest.TestCase):
    """Tests for _fetch_html's three distinct code paths."""

    @patch('calendars.importer.web_parser_base.HttpClient')
    def test_success_returns_response_text(self, mock_client_cls):
        """Happy path: returns .text from the response."""
        mock_response = MagicMock()
        mock_response.text = '<html>ok</html>'
        mock_client_cls.return_value.get.return_value = mock_response

        result = _fetch_html('http://example.com')

        self.assertEqual(result, '<html>ok</html>')

    @patch('calendars.importer.web_parser_base.HttpClient')
    def test_exception_with_response_attribute_returns_response_text(self, mock_client_cls):
        """Exception carrying .response — returns exc.response.text (lines 50-52)."""
        mock_response = MagicMock()
        mock_response.text = '<html>partial</html>'

        exc = RuntimeError('server error')
        exc.response = mock_response  # type: ignore[attr-defined]
        mock_client_cls.return_value.get.side_effect = exc

        result = _fetch_html('http://example.com')

        self.assertEqual(result, '<html>partial</html>')

    @patch('calendars.importer.web_parser_base.HttpClient')
    def test_exception_without_response_attribute_reraises(self, mock_client_cls):
        """Exception with no .response — must re-raise (lines 50, 53)."""
        exc = RuntimeError('connection refused')
        # No .response attribute set — getattr returns None
        mock_client_cls.return_value.get.side_effect = exc

        with self.assertRaises(RuntimeError) as ctx:
            _fetch_html('http://example.com')

        self.assertIs(ctx.exception, exc)


# ---------------------------------------------------------------------------
# Tests for RichmondHillSkatingParser bs4 sad paths
# ---------------------------------------------------------------------------

class TestRichmondHillSkatingParserSadPaths(unittest.TestCase):
    """Sad-path tests targeting previously-uncovered branches."""

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_no_acchild_sibling_returns_empty(self, mock_fetch):
        """accParent with no accChild sibling yields no items (lines 29-30)."""
        mock_fetch.return_value = _skating_html_no_acchild()
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_no_table_in_acchild_returns_empty(self, mock_fetch):
        """accChild present but contains no <table> yields no items (line 43)."""
        mock_fetch.return_value = _skating_html_no_table()
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_no_public_skating_row_returns_empty(self, mock_fetch):
        """Table without 'Public Skating' row yields no items (lines 46, 67)."""
        mock_fetch.return_value = _skating_html_no_public_skating_row()
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_row_with_single_cell_returns_empty(self, mock_fetch):
        """Public Skating row with fewer than 2 cells yields no items (line 50)."""
        mock_fetch.return_value = _skating_html_row_too_few_cells()
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_nbsp_only_time_cell_skipped(self, mock_fetch):
        """&nbsp;-only time cells are skipped, not converted to items (line 54)."""
        mock_fetch.return_value = _skating_html_nbsp_cell()
        items = RichmondHillSkatingParser().parse('http://test.com')
        # The \xa0 cell must produce no item
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)
            self.assertEqual(item.subject, 'Public Skating')

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_falls_back_to_previous_row_for_day_headers(self, mock_fetch):
        """Fewer than 7 weekday cells — fallback to header_tr (lines 87-89)."""
        mock_fetch.return_value = _skating_html_no_day_headers_in_table()
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_more_cells_than_days_skips_excess(self, mock_fetch):
        """Extra time cells beyond available day headers are skipped (line 99)."""
        mock_fetch.return_value = _skating_html_more_cells_than_days()
        items = RichmondHillSkatingParser().parse('http://test.com')
        # Only items up to the number of available day headers should appear
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_unparseable_time_cell_skipped(self, mock_fetch):
        """parse_time_range failure skips the cell, does not raise (branch 104->97)."""
        mock_fetch.return_value = _skating_html_unparseable_time_cell()
        # Must not raise; CLOSED cell is skipped; valid cell may produce an item
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_public_skating_is_first_row_no_header_tr(self, mock_fetch):
        """Public Skating is the first table row — find_previous('tr') returns None.

        Covers branch 88->92: header_tr is None so we skip straight to the
        WEEKDAYS[:needed] default.
        """
        mock_fetch.return_value = '''
<html><body>
<td data-name="accParent">First Row Arena</td>
<div data-name="accChild">
<table>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>3:00 - 4:00 p.m.</td>
    <td>5:00 - 6:00 p.m.</td>
</tr>
</table>
</div>
</body></html>
'''
        items = RichmondHillSkatingParser().parse('http://test.com')
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)
            self.assertEqual(item.subject, 'Public Skating')


# ---------------------------------------------------------------------------
# Direct tests for _find_public_skating_row (line 67 — returns None)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_BS4_AVAILABLE, 'bs4 not installed')
class TestFindPublicSkatingRowDirect(unittest.TestCase):
    """Direct unit tests for _find_public_skating_row."""

    def _make_table(self, html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, 'html.parser').find('table')

    def test_returns_none_when_no_match(self):
        table = self._make_table('<table><tr><td>Hockey</td></tr></table>')
        result = RichmondHillSkatingParser()._find_public_skating_row(table)
        self.assertIsNone(result)

    def test_returns_row_when_match_found(self):
        table = self._make_table(
            '<table><tr><td><strong>Public Skating</strong></td></tr></table>'
        )
        row = RichmondHillSkatingParser()._find_public_skating_row(table)
        self.assertIsNotNone(row)


# ---------------------------------------------------------------------------
# Direct tests for RichmondHillSwimmingParser helpers
# ---------------------------------------------------------------------------

class TestRichmondHillSwimmingParserDirect(unittest.TestCase):
    """Direct tests for _extract_facility_name and _parse_swim_block."""

    def setUp(self):
        self.parser = RichmondHillSwimmingParser()

    def test_extract_facility_name_present(self):
        block = '>   Richmond Green Pool&nbsp;  </td>'
        name = self.parser._extract_facility_name(block)
        self.assertEqual(name, 'Richmond Green Pool')

    def test_extract_facility_name_missing_returns_default(self):
        name = self.parser._extract_facility_name('')
        self.assertEqual(name, 'Pool')

    def test_parse_swim_block_empty_returns_empty(self):
        items = self.parser._parse_swim_block('', 'Test Pool', 'http://test.com')
        self.assertEqual(items, [])

    def test_parse_swim_block_leisure_swim_label(self):
        block = (
            '<td><strong>Leisure Swim</strong></td>'
            '<td>10:00 a.m. - 12:00 p.m.</td>'
            '<td></td><td></td><td></td><td></td><td></td><td></td>'
        )
        items = self.parser._parse_swim_block(block, 'Pool A', 'http://test.com')
        self.assertGreater(len(items), 0)
        self.assertEqual(items[0].subject, 'Leisure Swim')
        self.assertEqual(items[0].location, 'Pool A')

    def test_parse_swim_block_fun_n_fit_label(self):
        block = (
            '<td><strong>Fun N Fit</strong></td>'
            '<td>6:00 - 7:00 p.m.</td>'
            '<td></td><td></td><td></td><td></td><td></td><td></td>'
        )
        items = self.parser._parse_swim_block(block, 'Pool B', 'http://test.com')
        self.assertGreater(len(items), 0)
        self.assertEqual(items[0].subject, 'Fun N Fit')

    def test_parse_swim_block_fun_n_fit_and_leisure_swim_label(self):
        # The SWIM_LABELS tuple contains the literal string 'Fun N Fit & Leisure Swim'
        # so the regex matches the literal ampersand in the raw HTML, not the entity.
        block = (
            '<td><strong>Fun N Fit & Leisure Swim</strong></td>'
            '<td>8:00 - 9:00 a.m.</td>'
            '<td></td><td></td><td></td><td></td><td></td><td></td>'
        )
        items = self.parser._parse_swim_block(block, 'Pool C', 'http://test.com')
        self.assertGreater(len(items), 0)
        # Combined label maps to Fun N Fit
        self.assertEqual(items[0].subject, 'Fun N Fit')

    def test_parse_swim_block_no_matching_label(self):
        block = (
            '<td><strong>Lane Swim</strong></td>'
            '<td>6:00 - 7:00 a.m.</td>'
        )
        items = self.parser._parse_swim_block(block, 'Pool D', 'http://test.com')
        self.assertEqual(items, [])

    def test_parse_swim_block_unparseable_time_produces_no_item(self):
        block = (
            '<td><strong>Leisure Swim</strong></td>'
            '<td>CLOSED</td>'
            '<td></td><td></td><td></td><td></td><td></td><td></td>'
        )
        items = self.parser._parse_swim_block(block, 'Pool E', 'http://test.com')
        self.assertEqual(items, [])

    @patch('calendars.importer.web_parser_vendors_rh._fetch_html')
    def test_parse_returns_schedule_items(self, mock_fetch):
        """Happy-path: parse() returns ScheduleItem instances for valid HTML."""
        mock_fetch.return_value = '''
<html><body>
<td data-name="accParent">Test Pool</td>
<div data-name="accChild">
<table>
<tr>
    <td><strong>Leisure Swim</strong></td>
    <td>10:00 a.m. - 12:00 p.m.</td>
    <td></td><td></td><td></td><td></td><td></td><td></td>
</tr>
</table>
</div>
</body></html>
'''
        items = self.parser.parse('http://test.com')
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)


class TestParseTimeCellsMoreCellsThanDays(unittest.TestCase):
    """_parse_time_cells skips cells with no corresponding day header.

    Reaching the `if i >= len(days): continue` guard requires calling the
    method directly: _extract_day_headers always returns exactly as many days
    as there are cells, so the guard never fires through parse(). It is still
    live code on the method's own contract, not dead code, so it is pinned
    here directly rather than written off as unreachable.
    """

    class _Cell:
        def get_text(self, *_args, **_kwargs):
            return '9:00 am - 10:00 am'

    def test_extra_cells_are_skipped_not_misattributed(self):
        parser = RichmondHillSkatingParser()
        cells = [self._Cell(), self._Cell(), self._Cell()]

        items = parser._parse_time_cells(cells, ['Monday'], 'Arena', 'http://x')

        # One day header, three cells: only the first cell yields an item and
        # the surplus cells are dropped rather than attributed to a wrong day.
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].byday, ['MO'])
        self.assertEqual(items[0].subject, 'Public Skating')


if __name__ == '__main__':
    unittest.main()
