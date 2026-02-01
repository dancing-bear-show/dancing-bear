import json
import os
import sqlite3
import tempfile
import time
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
        self.assertIn("Line1 Line2", result)  # Newline replaced with space

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
        where, _ = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=None,
            since_days=0,
        )
        self.assertNotIn("ZMESSAGEDATE", where)

    def test_since_days_negative_ignored(self):
        """Test negative since_days is ignored."""
        where, _ = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=None,
            since_days=-5,
        )
        self.assertNotIn("ZMESSAGEDATE", where)

    def test_from_me_false_condition(self):
        """Test from_me=False adds ZISFROMME=0."""
        where, _ = search._build_where(
            contains=[],
            match_all=False,
            contact=None,
            from_me=False,
            since_days=None,
        )
        self.assertIn("m.ZISFROMME = 0", where)


class TestConnectRO(unittest.TestCase):
    """Tests for _connect_ro function."""

    def test_connects_to_database(self):
        """Test can connect to an existing database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()
            ro_conn = search._connect_ro(tmp_path)
            cursor = ro_conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            self.assertIn("test", tables)
            ro_conn.close()
        finally:
            os.unlink(tmp_path)

    def test_read_only_mode(self):
        """Test connection is read-only."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()
            ro_conn = search._connect_ro(tmp_path)
            with self.assertRaises(sqlite3.OperationalError):
                ro_conn.execute("INSERT INTO test VALUES (1)")
            ro_conn.close()
        finally:
            os.unlink(tmp_path)


class TestSearchMessages(unittest.TestCase):
    """Tests for search_messages function."""

    def setUp(self):
        """Create a temporary WhatsApp-like database."""
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE ZWACHATSESSION (
                Z_PK INTEGER PRIMARY KEY,
                ZPARTNERNAME TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE ZWAMESSAGE (
                Z_PK INTEGER PRIMARY KEY,
                ZCHATSESSION INTEGER,
                ZMESSAGEDATE INTEGER,
                ZISFROMME INTEGER,
                ZTEXT TEXT,
                FOREIGN KEY(ZCHATSESSION) REFERENCES ZWACHATSESSION(Z_PK)
            )
        """)
        cur.execute("INSERT INTO ZWACHATSESSION (Z_PK, ZPARTNERNAME) VALUES (1, 'Alice')")
        cur.execute("INSERT INTO ZWACHATSESSION (Z_PK, ZPARTNERNAME) VALUES (2, 'Bob Smith')")
        now_unix = time.time()
        apple_now = int(now_unix - search.APPLE_EPOCH_OFFSET)
        day_ago = apple_now - 86400
        week_ago = apple_now - (7 * 86400)
        cur.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (1, 1, ?, 0, 'Hello from Alice')",
            (apple_now,),
        )
        cur.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (2, 1, ?, 1, 'Reply to Alice')",
            (day_ago,),
        )
        cur.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (3, 2, ?, 0, 'Message from Bob')",
            (week_ago,),
        )
        cur.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (4, 2, ?, 1, 'Reply to Bob about meeting')",
            (day_ago,),
        )
        cur.execute("INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (5, 1, ?, 0, NULL)", (apple_now,))
        conn.commit()
        conn.close()

    def tearDown(self):
        """Clean up temporary database."""
        os.unlink(self.db_path)

    def test_search_all_messages(self):
        """Test searching without filters returns messages."""
        results = search.search_messages(db_path=self.db_path)
        self.assertGreater(len(results), 0)
        self.assertIsInstance(results[0], search.MessageRow)

    def test_search_with_contains_single_term(self):
        """Test searching with single contains term."""
        results = search.search_messages(db_path=self.db_path, contains=["Alice"])
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertIn("alice", row.text.lower())

    def test_search_with_contains_multiple_match_any(self):
        """Test searching with multiple terms, match any."""
        results = search.search_messages(db_path=self.db_path, contains=["Alice", "Bob"], match_all=False)
        self.assertGreater(len(results), 0)

    def test_search_with_contains_multiple_match_all(self):
        """Test searching with multiple terms, match all."""
        results = search.search_messages(db_path=self.db_path, contains=["Reply", "Bob"], match_all=True)
        self.assertEqual(len(results), 1)
        self.assertIn("Bob", results[0].text)
        self.assertIn("Reply", results[0].text)

    def test_search_with_contact_filter(self):
        """Test filtering by contact name."""
        results = search.search_messages(db_path=self.db_path, contact="Alice")
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertEqual(row.partner, "Alice")

    def test_search_with_from_me_true(self):
        """Test filtering messages from me."""
        results = search.search_messages(db_path=self.db_path, from_me=True)
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertEqual(row.from_me, 1)

    def test_search_with_from_me_false(self):
        """Test filtering messages from others."""
        results = search.search_messages(db_path=self.db_path, from_me=False)
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertEqual(row.from_me, 0)

    def test_search_with_since_days(self):
        """Test filtering by time range."""
        results = search.search_messages(db_path=self.db_path, since_days=3)
        self.assertGreater(len(results), 0)

    def test_search_with_limit(self):
        """Test limit parameter."""
        results = search.search_messages(db_path=self.db_path, limit=2)
        self.assertLessEqual(len(results), 2)

    def test_search_with_combined_filters(self):
        """Test multiple filters together."""
        results = search.search_messages(db_path=self.db_path, contact="Bob", from_me=True, contains=["meeting"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].partner, "Bob Smith")
        self.assertEqual(results[0].from_me, 1)

    def test_search_nonexistent_db(self):
        """Test raises error for nonexistent database."""
        with self.assertRaises(FileNotFoundError):
            search.search_messages(db_path="/nonexistent/path.db")

    def test_search_with_expanduser(self):
        """Test path expansion works."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            cur = conn.cursor()
            cur.execute("CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT)")
            cur.execute("CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZMESSAGEDATE INTEGER, ZISFROMME INTEGER, ZTEXT TEXT)")
            cur.execute("INSERT INTO ZWACHATSESSION (Z_PK, ZPARTNERNAME) VALUES (1, 'Test')")
            cur.execute("INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT) VALUES (1, 1, 0, 0, 'test')")
            conn.commit()
            conn.close()
            results = search.search_messages(db_path=tmp_path)
            self.assertIsInstance(results, list)
        finally:
            os.unlink(tmp_path)

    def test_search_returns_message_rows(self):
        """Test results contain expected fields."""
        results = search.search_messages(db_path=self.db_path)
        for row in results:
            self.assertIsInstance(row.ts, str)
            self.assertIsInstance(row.partner, str)
            self.assertIsInstance(row.from_me, int)
            self.assertIsInstance(row.text, str)

    def test_search_filters_null_text(self):
        """Test NULL text messages are excluded."""
        results = search.search_messages(db_path=self.db_path)
        for row in results:
            self.assertIsNotNone(row.text)


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
        self.assertTrue(data[0]["from_me"])
        self.assertFalse(data[1]["from_me"])
        self.assertEqual(data[0]["partner"], "Alice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
