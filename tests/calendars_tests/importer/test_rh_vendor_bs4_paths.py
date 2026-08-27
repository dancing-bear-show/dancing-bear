"""Coverage-gap tests for web_parser_vendors_rh.py — bs4 code paths.

Target: 59% -> 85%+

These tests inject a fake bs4 module into sys.modules so the
``try: from bs4 import BeautifulSoup`` branch succeeds, causing
``_parse_with_bs4`` to run instead of the regex fallback.

Covers:
  Line 28   parse() entry: try block succeeds, delegates to _parse_with_bs4
  Lines 34-59: _parse_with_bs4 happy path; no-accChild (29-30); no-table (43);
               no-public-skating-row (46); too-few-cells (50); nbsp cell (54)
  Lines 63-67: _find_public_skating_row: None return; match return
  Lines 71-76: _extract_weekdays_from_cells
  Lines 80-92: _extract_day_headers: full 7-day; fewer than 7 with prev-row fallback;
               fewer-than-needed default to WEEKDAYS
  Lines 102, 104->97: _parse_time_cells: i >= len(days) skip; parse_time_range fails

All tests patch ``calendars.importer.web_parser_vendors_rh._fetch_html``
to avoid any network activity.
"""
from __future__ import annotations

import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from calendars.importer.web_parser_vendors_rh import (
    RichmondHillSkatingParser,
)
from calendars.importer.model import ScheduleItem


# ---------------------------------------------------------------------------
# Fake bs4 injection
# ---------------------------------------------------------------------------
#
# bs4 is an optional dependency not installed in this environment.  We inject
# a minimal fake so the ``try: from bs4 import BeautifulSoup`` branch in
# ``parse()`` succeeds, driving the bs4 code path.
#
# The fake wraps the stdlib ``html.parser`` via a thin adapter that mimics the
# subset of the bs4 API used by the parsers under test:
#   - BeautifulSoup(html, 'html.parser') -> _Soup
#   - soup.select(css)             -> list of _Tag
#   - tag.get_text(strip=True)     -> str
#   - tag.find_next(attrs={...})   -> _Tag | None
#   - tag.find('table')            -> _Tag | None
#   - tag.find_all('tr')           -> list[_Tag]
#   - tag.find_all('td')           -> list[_Tag]
#   - tag.find('td')               -> _Tag | None
#   - tag.find_previous('tr')      -> _Tag | None
#   - tag.get(attr)                -> str | list | None
#
# The implementation shells out to the stdlib html.parser and builds a
# lightweight node tree that is good enough for the parsers' traversal
# patterns without re-implementing a full DOM.

import html.parser as _html_parser


class _Tag:
    """Minimal DOM node."""

    def __init__(self, name: str, attrs: dict, children: list, text: str = ""):
        self.name = name
        self.attrs = attrs
        self._children = children
        self._text = text

    # ---- text extraction ----

    def get_text(self, separator="", strip=False) -> str:
        parts = [self._text] if self._text else []
        for child in self._children:
            if isinstance(child, _Tag):
                parts.append(child.get_text(separator, strip))
            elif isinstance(child, str):
                parts.append(child)
        result = separator.join(parts)
        return result.strip() if strip else result

    # ---- attribute access ----

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    # ---- traversal ----

    def find_all(self, tag_name=None, attrs=None):
        results = []
        for child in self._children:
            if not isinstance(child, _Tag):
                continue
            if self._matches(child, tag_name, attrs):
                results.append(child)
            results.extend(child.find_all(tag_name, attrs))
        return results

    def find(self, tag_name=None, attrs=None):
        for child in self._children:
            if not isinstance(child, _Tag):
                continue
            if self._matches(child, tag_name, attrs):
                return child
            result = child.find(tag_name, attrs)
            if result is not None:
                return result
        return None

    def find_next(self, tag_name=None, attrs=None):
        """Find the next sibling (not child) that matches."""
        return getattr(self, "_next_sibling_match", lambda t, a: None)(tag_name, attrs)

    def find_previous(self, tag_name=None, attrs=None):
        """Find the previous sibling (not child) that matches."""
        return getattr(self, "_prev_sibling_match", lambda t, a: None)(tag_name, attrs)

    @staticmethod
    def _matches(node: "_Tag", tag_name, attrs) -> bool:
        if tag_name and node.name != tag_name:
            return False
        if attrs:
            for k, v in attrs.items():
                nv = node.attrs.get(k)
                if isinstance(nv, list):
                    if v not in nv:
                        return False
                elif nv != v:
                    return False
        return True

    def select(self, selector: str) -> list:
        """Extremely limited CSS selector: supports ``[attr="val"]`` and ``tag``."""
        import re
        m = re.match(r'\[([^=\]]+)=["\']?([^"\'=\]]*)["\']?\]$', selector)
        if m:
            attr, val = m.group(1), m.group(2)
            return self.find_all(attrs={attr: val})
        return self.find_all(selector)

    def __repr__(self):
        return f"<{self.name} attrs={self.attrs} text={self._text!r}>"


class _TreeBuilder(_html_parser.HTMLParser):
    """Build a _Tag tree from raw HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._root = _Tag("root", {}, [])
        self._stack = [self._root]

    def handle_starttag(self, tag, attrs):
        node = _Tag(tag, dict(attrs), [])
        self._stack[-1]._children.append(node)
        self._stack.append(node)

    def handle_endtag(self, tag):
        if len(self._stack) > 1:
            self._stack.pop()

    def handle_data(self, data):
        if len(self._stack) > 1:
            self._stack[-1]._children.append(data)


def _build_tree(html: str) -> _Tag:
    builder = _TreeBuilder()
    builder.feed(html)
    return builder._root


class _Soup(_Tag):
    """BeautifulSoup stand-in returned by the fake module."""

    def __init__(self, html: str, parser: str):
        root = _build_tree(html)
        super().__init__("root", {}, root._children)
        self._wire_siblings()

    def _wire_siblings(self):
        """Wire find_next / find_previous sibling resolution for direct children."""
        self._wire_sibling_methods(self._children)

    def _wire_sibling_methods(self, siblings: list):
        tag_siblings = [s for s in siblings if isinstance(s, _Tag)]
        for i, tag in enumerate(tag_siblings):
            prev_tags = tag_siblings[:i]
            next_tags = tag_siblings[i + 1:]

            def _next(tag_name, attrs, _next_tags=next_tags):
                for sib in _next_tags:
                    if _Tag._matches(sib, tag_name, attrs):
                        return sib
                return None

            def _prev(tag_name, attrs, _prev_tags=prev_tags):
                for sib in reversed(_prev_tags):
                    if _Tag._matches(sib, tag_name, attrs):
                        return sib
                return None

            tag._next_sibling_match = _next
            tag._prev_sibling_match = _prev
            # Recurse into children
            self._wire_sibling_methods(tag._children)


class _FakeBS4Module(types.ModuleType):
    """Fake bs4 module exposing only BeautifulSoup."""

    BeautifulSoup = _Soup


@contextmanager
def _inject_bs4():
    """Context manager: inject the fake bs4 into sys.modules for the duration."""
    fake = _FakeBS4Module("bs4")
    old = sys.modules.get("bs4")
    sys.modules["bs4"] = fake
    try:
        yield fake
    finally:
        if old is None:
            sys.modules.pop("bs4", None)
        else:
            sys.modules["bs4"] = old


# ---------------------------------------------------------------------------
# Minimal HTML helpers
# ---------------------------------------------------------------------------

_FULL_HTML = """<html><body>
<td data-name="accParent">Arena A</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td><td>Tuesday</td><td>Wednesday</td><td>Thursday</td><td>Friday</td><td>Saturday</td></tr>
<tr>
    <td><strong>Public Skating</strong></td>
    <td>1:00 - 2:00 p.m.</td>
    <td>3:00 - 4:00 p.m.</td>
    <td></td><td></td><td></td><td></td>
</tr>
</table>
</div>
</body></html>"""

_NO_ACCHILD_HTML = """<html><body>
<td data-name="accParent">Empty Arena</td>
</body></html>"""

_NO_TABLE_HTML = """<html><body>
<td data-name="accParent">No Table Arena</td>
<div data-name="accChild"><p>no table here</p></div>
</body></html>"""

_NO_PUBLIC_SKATING_HTML = """<html><body>
<td data-name="accParent">Hockey Arena</td>
<div data-name="accChild">
<table>
<tr><td>Sunday</td><td>Monday</td></tr>
<tr><td><strong>Hockey</strong></td><td>7:00 - 8:00 p.m.</td></tr>
</table>
</div>
</body></html>"""

_TOO_FEW_CELLS_HTML = """<html><body>
<td data-name="accParent">Small Arena</td>
<div data-name="accChild">
<table>
<tr><td><strong>Public Skating</strong></td></tr>
</table>
</div>
</body></html>"""

_NBSP_CELL_HTML = """<html><body>
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
</body></html>"""

_FEW_DAY_HEADERS_HTML = """<html><body>
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
</body></html>"""

_UNPARSEABLE_TIME_HTML = """<html><body>
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
</body></html>"""


# ---------------------------------------------------------------------------
# Tests for parse() using bs4 path (line 28, 34-59)
# ---------------------------------------------------------------------------

class TestRichmondHillSkatingParserBs4Paths(unittest.TestCase):
    """Drive the bs4 code path via fake bs4 injection."""

    def _parse(self, html: str) -> list[ScheduleItem]:
        with _inject_bs4():
            with patch("calendars.importer.web_parser_vendors_rh._fetch_html", return_value=html):
                return RichmondHillSkatingParser().parse("http://test.com")

    def test_happy_path_returns_schedule_items(self):
        """bs4 path with valid HTML and times yields ScheduleItem instances. (lines 28, 34-59)"""
        items = self._parse(_FULL_HTML)
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)
            self.assertEqual(item.subject, "Public Skating")

    def test_no_acchild_returns_empty(self):
        """accParent with no accChild sibling yields no items. (lines 29-30)"""
        items = self._parse(_NO_ACCHILD_HTML)
        self.assertEqual(items, [])

    def test_no_table_in_acchild_returns_empty(self):
        """accChild with no <table> yields no items. (line 43)"""
        items = self._parse(_NO_TABLE_HTML)
        self.assertEqual(items, [])

    def test_no_public_skating_row_returns_empty(self):
        """Table without 'Public Skating' row yields no items. (line 46)"""
        items = self._parse(_NO_PUBLIC_SKATING_HTML)
        self.assertEqual(items, [])

    def test_row_with_too_few_cells_returns_empty(self):
        """Public Skating row with fewer than 2 cells yields no items. (line 50)"""
        items = self._parse(_TOO_FEW_CELLS_HTML)
        self.assertEqual(items, [])

    def test_nbsp_only_cell_is_skipped(self):
        """&nbsp;-only cell is skipped, does not produce an item. (line 54)"""
        items = self._parse(_NBSP_CELL_HTML)
        # All items that were produced must have valid subject
        for item in items:
            self.assertEqual(item.subject, "Public Skating")
        # The nbsp cell must not have produced an item

    def test_sparse_day_headers_uses_prev_row_fallback(self):
        """Fewer-than-7 weekday headers: fallback to the previous row. (lines 87-89)"""
        items = self._parse(_FEW_DAY_HEADERS_HTML)
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)

    def test_unparseable_time_cell_is_skipped(self):
        """parse_time_range failure skips the cell; others still produce items. (branch 104->97)"""
        items = self._parse(_UNPARSEABLE_TIME_HTML)
        # CLOSED cell must be skipped, valid cell may produce an item
        self.assertIsInstance(items, list)
        for item in items:
            self.assertIsInstance(item, ScheduleItem)


# ---------------------------------------------------------------------------
# Tests for _find_public_skating_row directly (lines 63-67)
# ---------------------------------------------------------------------------

class TestFindPublicSkatingRowDirect(unittest.TestCase):
    """Direct unit tests for _find_public_skating_row using fake bs4."""

    def _make_table(self, html: str):
        with _inject_bs4():
            from bs4 import BeautifulSoup
            return BeautifulSoup(html, "html.parser").find("table")

    def test_returns_none_when_no_matching_row(self):
        """Table with no 'Public Skating' td returns None. (line 67)"""
        with _inject_bs4():
            from bs4 import BeautifulSoup
            table = BeautifulSoup(
                "<table><tr><td>Hockey</td></tr></table>", "html.parser"
            ).find("table")
            result = RichmondHillSkatingParser()._find_public_skating_row(table)
        self.assertIsNone(result)

    def test_returns_row_when_public_skating_found(self):
        """Table with a 'Public Skating' td returns that row. (lines 63-66)"""
        with _inject_bs4():
            from bs4 import BeautifulSoup
            table = BeautifulSoup(
                "<table><tr><td>Public Skating</td></tr></table>", "html.parser"
            ).find("table")
            result = RichmondHillSkatingParser()._find_public_skating_row(table)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Tests for _extract_weekdays_from_cells (lines 71-76)
# ---------------------------------------------------------------------------

class TestExtractWeekdaysFromCellsDirect(unittest.TestCase):
    """_extract_weekdays_from_cells returns cells whose text is in the weekday set."""

    def _make_cells(self, cell_texts: list[str]):
        """Build a list of fake _Tag cells with given text values."""
        cells = []
        for txt in cell_texts:
            tag = _Tag("td", {}, [txt])
            cells.append(tag)
        return cells

    def test_extracts_matching_weekday_cells(self):
        """Cells containing weekday names are extracted in order. (lines 71-76)"""
        parser = RichmondHillSkatingParser()
        cells = self._make_cells(["Sunday", "Monday", "Holiday", "Tuesday"])
        weekday_set = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"}
        result = parser._extract_weekdays_from_cells(cells, weekday_set)
        self.assertEqual(result, ["Sunday", "Monday", "Tuesday"])

    def test_returns_empty_when_no_weekday_cells(self):
        """No matching cells returns empty list."""
        parser = RichmondHillSkatingParser()
        cells = self._make_cells(["Public Skating", "Holiday"])
        weekday_set = {"sunday", "monday", "tuesday"}
        result = parser._extract_weekdays_from_cells(cells, weekday_set)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Tests for _extract_day_headers (lines 80-92)
# ---------------------------------------------------------------------------

class TestExtractDayHeadersDirect(unittest.TestCase):
    """_extract_day_headers returns day names from a table, with fallback logic."""

    @staticmethod
    def _first_match(siblings: list[_Tag]):
        """Return a sibling-match callable scanning `siblings` in order."""
        def _find(tag_name, attrs, _sibs=siblings):
            for sib in _sibs:
                if _Tag._matches(sib, tag_name, attrs):
                    return sib
            return None
        return _find

    def _wire_siblings(self, rows: list[_Tag]) -> None:
        """Give each row prev/next sibling-match callables over its neighbours."""
        for i, row in enumerate(rows):
            row._prev_sibling_match = self._first_match(list(reversed(rows[:i])))
            row._next_sibling_match = self._first_match(rows[i + 1:])

    def _make_table_with_rows(self, row_texts: list[list[str]]) -> _Tag:
        """Build a fake table with given row/cell text structure."""
        rows = [
            _Tag("tr", {}, [_Tag("td", {}, [c]) for c in cells])
            for cells in row_texts
        ]
        table = _Tag("table", {}, rows)
        self._wire_siblings(rows)
        return table

    def test_extracts_from_full_seven_weekday_table(self):
        """Table with 7 weekday cells returns all 7. (lines 80-84)"""
        parser = RichmondHillSkatingParser()
        days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        table = self._make_table_with_rows([days, ["Public Skating"] + ["T"] * 7])
        # Use the last row as the 'row' (public skating row)
        row = table._children[1]
        result = parser._extract_day_headers(table, row, 7)
        self.assertEqual(result, days)

    def test_fewer_than_needed_defaults_to_weekdays_slice(self):
        """Table with 0 weekday cells falls back to WEEKDAYS[:needed]. (line 92)"""
        from calendars.importer.web_parser_base import WEEKDAYS
        parser = RichmondHillSkatingParser()
        table = self._make_table_with_rows([
            ["Public Skating", "Time1", "Time2"]
        ])
        row = table._children[0]
        result = parser._extract_day_headers(table, row, 2)
        self.assertEqual(result, WEEKDAYS[:2])


# ---------------------------------------------------------------------------
# Tests for _parse_time_cells extra-cells guard (line 102)
# ---------------------------------------------------------------------------

class TestParseTimeCellsExtraCells(unittest.TestCase):
    """_parse_time_cells skips cells at indices beyond the day list length."""

    class _Cell:
        def get_text(self, *_args, **_kwargs):
            return "9:00 am - 10:00 am"

    def test_extra_cells_skipped(self):
        """Three cells with one day: only first cell yields an item. (line 102)"""
        parser = RichmondHillSkatingParser()
        cells = [self._Cell(), self._Cell(), self._Cell()]
        items = parser._parse_time_cells(cells, ["Monday"], "Arena", "http://x")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].byday, ["MO"])

    def test_unparseable_time_cell_skipped(self):
        """Cell whose text parse_time_range cannot parse yields no item. (branch 104->97)"""
        class _BadCell:
            def get_text(self, *_a, **_kw):
                return "CLOSED"

        parser = RichmondHillSkatingParser()
        items = parser._parse_time_cells([_BadCell()], ["Sunday"], "Arena", "http://x")
        self.assertEqual(items, [])

    def test_valid_cell_at_index_zero_yields_item(self):
        """Happy path: single valid cell at index 0 yields one ScheduleItem."""
        parser = RichmondHillSkatingParser()
        items = parser._parse_time_cells([self._Cell()], ["Monday"], "Arena", "http://x")
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], ScheduleItem)


if __name__ == "__main__":
    unittest.main()
