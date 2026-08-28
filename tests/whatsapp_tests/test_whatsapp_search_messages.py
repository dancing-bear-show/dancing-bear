"""Tests for whatsapp.search.search_messages and _connect_ro.

Covers lines 60-61 (db path expansion) and 119-140 (search_messages body):
- db path expansion via os.path.expanduser
- NotFoundError when ChatStorage db does not exist
- SQL execution returning correct MessageRow values
- None-coalescing for ts, partner, from_me, text columns
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from core.cli_errors import NotFoundError
from whatsapp import search
from whatsapp.search import MessageQuery, MessageRow, search_messages

from tests.fixtures import TempDirMixin


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _create_db(path: str) -> None:
    """Create a minimal ZWAMESSAGE/ZWACHATSESSION db at path."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY,
            ZPARTNERNAME TEXT
        );
        CREATE TABLE ZWAMESSAGE (
            Z_PK INTEGER PRIMARY KEY,
            ZCHATSESSION INTEGER,
            ZTEXT TEXT,
            ZISFROMME INTEGER,
            ZMESSAGEDATE REAL
        );
    """)
    conn.commit()
    conn.close()


def _insert_session(conn: sqlite3.Connection, pk: int, name: str | None) -> None:
    conn.execute(
        "INSERT INTO ZWACHATSESSION (Z_PK, ZPARTNERNAME) VALUES (?, ?)", (pk, name)
    )


def _insert_message(
    conn: sqlite3.Connection,
    pk: int,
    session_pk: int,
    text: str | None,
    from_me: int | None,
    date: float,
) -> None:
    conn.execute(
        "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZTEXT, ZISFROMME, ZMESSAGEDATE) VALUES (?,?,?,?,?)",
        (pk, session_pk, text, from_me, date),
    )


class TestSearchMessagesNotFound(unittest.TestCase):
    """search_messages raises NotFoundError when the db path does not exist."""

    def test_raises_not_found_for_missing_path(self):
        with self.assertRaises(NotFoundError):
            search_messages(db_path="/nonexistent/path/ChatStorage.sqlite")

    def test_raises_not_found_with_default_path_absent(self):
        """NotFoundError if the system default path doesn't exist (no real WhatsApp)."""
        default = search.default_db_path()
        if os.path.exists(default):
            self.skipTest("Real WhatsApp db present — skip this guard test")
        with self.assertRaises(NotFoundError):
            search_messages()

    def test_tilde_path_expanded_before_checking(self):
        """A ~/... path that doesn't exist should still raise NotFoundError, not OSError."""
        with self.assertRaises(NotFoundError):
            search_messages(db_path="~/nonexistent-whatsapp-test/ChatStorage.sqlite")


class TestSearchMessagesReturnsRows(TempDirMixin, unittest.TestCase):
    """search_messages executes SQL and returns correctly typed MessageRow objects."""

    def _db_path(self, name: str = "ChatStorage.sqlite") -> str:
        return os.path.join(self.tmpdir, name)

    def test_happy_path_returns_message_rows(self):
        """A single row in the db is returned as a MessageRow."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Alice")
        _insert_message(conn, 1, 1, "Hello there", 1, 1000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, MessageRow)
        self.assertEqual(row.partner, "Alice")
        self.assertEqual(row.from_me, 1)
        self.assertEqual(row.text, "Hello there")
        self.assertIsInstance(row.ts, str)

    def test_returns_empty_list_when_no_messages(self):
        """Empty db yields empty list."""
        db = self._db_path()
        _create_db(db)

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(rows, [])

    def test_none_coalescing_for_partner(self):
        """None ZPARTNERNAME is coalesced to empty string."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, None)
        _insert_message(conn, 1, 1, "text", 0, 1000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].partner, "")

    def test_none_coalescing_for_text_is_excluded_by_where(self):
        """None ZTEXT rows are excluded by WHERE ZTEXT IS NOT NULL."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Bob")
        _insert_message(conn, 1, 1, None, 0, 1000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(rows, [])

    def test_none_coalescing_for_from_me(self):
        """None ZISFROMME is coalesced to int 0."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Carol")
        _insert_message(conn, 1, 1, "hi", None, 1000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].from_me, 0)

    def test_limit_is_respected(self):
        """limit parameter caps the number of rows returned."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Alice")
        for i in range(5):
            _insert_message(conn, i + 1, 1, f"msg {i}", 0, float(i + 1))
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=3))

        self.assertEqual(len(rows), 3)

    def test_contains_filter_applied(self):
        """contains filter narrows results to matching messages."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Dave")
        _insert_message(conn, 1, 1, "hello world", 0, 1000.0)
        _insert_message(conn, 2, 1, "goodbye", 0, 2000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(contains=["hello"], limit=10))

        self.assertEqual(len(rows), 1)
        self.assertIn("hello", rows[0].text)

    def test_from_me_filter_true(self):
        """from_me=True returns only outgoing messages."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Eve")
        _insert_message(conn, 1, 1, "outgoing", 1, 1000.0)
        _insert_message(conn, 2, 1, "incoming", 0, 2000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(from_me=True, limit=10))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].from_me, 1)
        self.assertEqual(rows[0].text, "outgoing")

    def test_from_me_filter_false(self):
        """from_me=False returns only incoming messages."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Frank")
        _insert_message(conn, 1, 1, "outgoing", 1, 1000.0)
        _insert_message(conn, 2, 1, "incoming", 0, 2000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(from_me=False, limit=10))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].from_me, 0)
        self.assertEqual(rows[0].text, "incoming")

    def test_default_query_used_when_none(self):
        """Passing query=None falls back to MessageQuery() defaults."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Alice")
        _insert_message(conn, 1, 1, "test msg", 0, 1000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=None)

        self.assertEqual(len(rows), 1)

    def test_multiple_messages_returned_in_order(self):
        """Multiple messages are returned ordered by ZMESSAGEDATE DESC."""
        db = self._db_path()
        _create_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, 1, "Group")
        _insert_message(conn, 1, 1, "first", 0, 1000.0)
        _insert_message(conn, 2, 1, "second", 0, 2000.0)
        _insert_message(conn, 3, 1, "third", 0, 3000.0)
        conn.commit()
        conn.close()

        rows = search_messages(db_path=db, query=MessageQuery(limit=10))

        self.assertEqual(len(rows), 3)
        # DESC order: third, second, first
        self.assertEqual(rows[0].text, "third")
        self.assertEqual(rows[2].text, "first")


if __name__ == "__main__":
    unittest.main(verbosity=2)
