import json
import os
import unittest

from whatsapp import search


class TestDefaultDbPath(unittest.TestCase):
    """Tests for default_db_path function."""

    def test_returns_path_string(self):
        """Test returns a string path."""
        path = search.default_db_path()
        self.assertIsInstance(path, str)

    def test_path_contains_whatsapp(self):
        """Test path contains WhatsApp directory."""
        path = search.default_db_path()
        self.assertIn("WhatsApp", path)

    def test_path_contains_chatstorage(self):
        """Test path ends with ChatStorage.sqlite."""
        path = search.default_db_path()
        self.assertTrue(path.endswith("ChatStorage.sqlite"))

    def test_path_is_absolute(self):
        """Test path is absolute (starts with /)."""
        path = search.default_db_path()
        self.assertTrue(os.path.isabs(path))


class TestMessageRow(unittest.TestCase):
    """Tests for MessageRow dataclass."""

    def test_create_message_row(self):
        """Test creating a MessageRow."""
        row = search.MessageRow(ts="2024-01-02 03:04", partner="Alice", from_me=1, text="Hello")
        self.assertEqual(row.ts, "2024-01-02 03:04")
        self.assertEqual(row.partner, "Alice")
        self.assertEqual(row.from_me, 1)
        self.assertEqual(row.text, "Hello")

    def test_message_row_from_me_zero(self):
        """Test MessageRow with from_me=0."""
        row = search.MessageRow(ts="2024-01-02", partner="Bob", from_me=0, text="Hi")
        self.assertEqual(row.from_me, 0)


class TestFormatRowsText(unittest.TestCase):
    """Tests for format_rows_text function."""

    def test_formats_single_row(self):
        """Test formatting a single row."""
        rows = [search.MessageRow(ts="2024-01-02 03:04", partner="Alice", from_me=1, text="Hello")]
        result = search.format_rows_text(rows)
        self.assertIn("2024-01-02 03:04", result)
        self.assertIn("Alice", result)
        self.assertIn("me", result)
        self.assertIn("Hello", result)

    def test_from_me_false_shows_them(self):
        """Test from_me=0 shows as 'them'."""
        rows = [search.MessageRow(ts="2024-01-02", partner="Bob", from_me=0, text="Hi")]
        result = search.format_rows_text(rows)
        self.assertIn("them", result)

    def test_truncates_long_text(self):
        """Test truncates text over 140 chars."""
        long_text = "A" * 200
        rows = [search.MessageRow(ts="2024-01-02", partner="Bob", from_me=0, text=long_text)]
        result = search.format_rows_text(rows)
        last_field = result.split("\t")[-1]
        self.assertLess(len(last_field), 150)
        self.assertIn("…", result)

    def test_replaces_newlines(self):
        """Test replaces newlines with spaces."""
        rows = [search.MessageRow(ts="2024-01-02", partner="Bob", from_me=0, text="Line1\nLine2")]
        result = search.format_rows_text(rows)
        self.assertNotIn("\n\n", result)  # Original newline replaced
        self.assertIn("Line1 Line2", result)

    def test_handles_empty_list(self):
        """Test handles empty list."""
        result = search.format_rows_text([])
        self.assertEqual(result, "")


class TestRowsToDicts(unittest.TestCase):
    """Tests for rows_to_dicts function."""

    def test_converts_rows(self):
        """Test converts MessageRows to dicts."""
        rows = [
            search.MessageRow(ts="2024-01-02", partner="Alice", from_me=1, text="Hello"),
            search.MessageRow(ts="2024-01-03", partner="Bob", from_me=0, text="Hi"),
        ]
        result = search.rows_to_dicts(rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["partner"], "Alice")
        self.assertTrue(result[0]["from_me"])
        self.assertFalse(result[1]["from_me"])

    def test_handles_empty(self):
        """Test handles empty list."""
        result = search.rows_to_dicts([])
        self.assertEqual(result, [])


class TestBuildWhereWithSinceDays(unittest.TestCase):
    """Tests for _build_where with since_days parameter."""

    def test_since_days_adds_condition(self):
        """Test since_days adds ZMESSAGEDATE condition."""
        where, params = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=None,
            since_days=7,
        )
        self.assertIn("m.ZMESSAGEDATE >=", where)
        self.assertEqual(len(params), 1)

    def test_since_days_zero_ignored(self):
        """Test since_days=0 is ignored."""
        where, params = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=None,
            since_days=0,
        )
        self.assertNotIn("ZMESSAGEDATE", where)

    def test_since_days_negative_ignored(self):
        """Test negative since_days is ignored."""
        where, params = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=None,
            since_days=-5,
        )
        self.assertNotIn("ZMESSAGEDATE", where)

    def test_from_me_false_condition(self):
        """Test from_me=False adds ZISFROMME=0."""
        where, params = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=False,
            since_days=None,
        )
        self.assertIn("m.ZISFROMME = 0", where)


class TestWhatsAppSearchHelpers(unittest.TestCase):
    def test_build_like_clause_filters_terms(self):
        clause, params = search._build_like_clause(
            "m.ZTEXT", [" Hello ", "", "WORLD", None], match_all=False
        )
        self.assertEqual(clause, "(lower(m.ZTEXT) LIKE ? OR lower(m.ZTEXT) LIKE ?)")
        self.assertEqual(params, ["%hello%", "%world%"])

    def test_build_like_clause_empty(self):
        clause, params = search._build_like_clause("m.ZTEXT", [" ", ""], match_all=True)
        self.assertEqual(clause, "")
        self.assertEqual(params, [])

    def test_build_where_includes_contact_and_from(self):
        where, params = search._build_where(
            contains=["alpha", "beta"],
            match_all=True,
            contact="Teacher",
            from_me=True,
            since_days=None,
        )
        self.assertIn("m.ZTEXT IS NOT NULL", where)
        self.assertIn("lower(m.ZTEXT) LIKE ? AND lower(m.ZTEXT) LIKE ?", where)
        self.assertIn("lower(s.ZPARTNERNAME) LIKE ?", where)
        self.assertIn("m.ZISFROMME = 1", where)
        self.assertEqual(params[:3], ["%alpha%", "%beta%", "%teacher%"])

    def test_format_rows_json(self):
        rows = [
            search.MessageRow(ts="2024-01-02 03:04", partner="Alice", from_me=1, text="Hello"),
            search.MessageRow(ts="2024-01-02 03:05", partner="Bob", from_me=0, text="Hi"),
        ]
        raw = search.format_rows_json(rows)
        data = json.loads(raw)
        self.assertEqual(data[0]["from_me"], True)
        self.assertEqual(data[1]["from_me"], False)
        self.assertEqual(data[0]["partner"], "Alice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
