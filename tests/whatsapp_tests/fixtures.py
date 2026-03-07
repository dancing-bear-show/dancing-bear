"""Shared test fixtures for WhatsApp module tests.

Provides common test data, factory functions, and utilities to reduce
duplication across WhatsApp test files.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from whatsapp.search import MessageRow, APPLE_EPOCH_OFFSET
from whatsapp.pipeline import SearchRequest

# Re-export commonly used constants
__all__ = [
    'APPLE_EPOCH_OFFSET',
    'DEFAULT_TIMESTAMP',
    'DEFAULT_PARTNER',
    'DEFAULT_TEXT',
    'message_row',
    'search_request',
    'make_args_mock',
    'create_test_db',
    'temp_test_db',
]

# Default test values
DEFAULT_TIMESTAMP = "2024-01-01 10:00:00"
DEFAULT_PARTNER = "Alice"
DEFAULT_TEXT = "Hello"


def message_row(
    ts: str = DEFAULT_TIMESTAMP,
    partner: str = DEFAULT_PARTNER,
    from_me: int = 1,
    text: str = DEFAULT_TEXT,
) -> MessageRow:
    """Create a MessageRow instance with sensible defaults.

    Args:
        ts: Timestamp string (local time, ISO-like)
        partner: Contact partner name
        from_me: 1 if message from self, 0 if from partner
        text: Message text content

    Returns:
        MessageRow instance

    Example:
        row = message_row(partner="Bob", text="Hi there")
        assert row.partner == "Bob"
    """
    return MessageRow(ts=ts, partner=partner, from_me=from_me, text=text)


def search_request(
    db_path: Optional[str] = None,
    contains: Optional[List[str]] = None,
    match_all: bool = False,
    contact: Optional[str] = None,
    from_me: Optional[bool] = None,
    since_days: Optional[int] = None,
    limit: int = 50,
    emit_json: bool = False,
) -> SearchRequest:
    """Create a SearchRequest instance with sensible defaults.

    Args:
        db_path: Path to WhatsApp database (None = use default)
        contains: List of search terms to match in message text
        match_all: If True, require all terms; if False, require any term
        contact: Filter by contact partner name
        from_me: If True, only self messages; if False, only partner messages; if None, all
        since_days: Only include messages from last N days
        limit: Maximum number of messages to return
        emit_json: If True, format output as JSON

    Returns:
        SearchRequest instance

    Example:
        req = search_request(contains=["meeting"], contact="Bob", limit=10)
        assert req.contains == ["meeting"]
    """
    return SearchRequest(
        db_path=db_path,
        contains=contains,
        match_all=match_all,
        contact=contact,
        from_me=from_me,
        since_days=since_days,
        limit=limit,
        emit_json=emit_json,
    )


def make_args_mock(
    from_me: bool = False,
    from_them: bool = False,
    db: Optional[str] = None,
    contains: Optional[List[str]] = None,
    match_all: bool = False,
    match_any: bool = False,
    contact: Optional[str] = None,
    since_days: Optional[int] = None,
    limit: int = 50,
    json: bool = False,
) -> MagicMock:
    """Create an argparse Namespace mock with WhatsApp CLI arguments.

    Args:
        from_me: Show only messages sent by self
        from_them: Show only messages received from others
        db: Path to WhatsApp database
        contains: List of search terms
        match_all: Require all search terms
        match_any: Require any search term
        contact: Filter by contact name
        since_days: Only messages from last N days
        limit: Maximum messages to return
        json: Output as JSON

    Returns:
        MagicMock with all arguments as attributes

    Example:
        args = make_args_mock(contact="Alice", limit=10, json=True)
        assert args.contact == "Alice"
        assert args.json is True
    """
    args = MagicMock()
    args.from_me = from_me
    args.from_them = from_them
    args.db = db
    args.contains = contains or []
    args.match_all = match_all
    args.match_any = match_any
    args.contact = contact
    args.since_days = since_days
    args.limit = limit
    args.json = json
    return args


def create_test_db(
    db_path: str,
    contacts: Optional[Dict[int, str]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Create a SQLite test database with WhatsApp schema.

    Creates ZWACHATSESSION and ZWAMESSAGE tables and populates them
    with test data. Uses Apple epoch timestamps (978307200 offset).

    Args:
        db_path: Path where database should be created
        contacts: Optional dict mapping Z_PK -> ZPARTNERNAME
                 Default: {1: "Alice", 2: "Bob Smith"}
        messages: Optional list of message dicts with keys:
                 - pk: Z_PK (primary key)
                 - session: ZCHATSESSION (foreign key to contacts)
                 - days_ago: Number of days before now for timestamp
                 - from_me: ZISFROMME (1 or 0)
                 - text: ZTEXT (message content, can be None)
                 Default: Creates 5 test messages

    Returns:
        The db_path for convenience

    Example:
        db_path = create_test_db(
            "/tmp/test.db",
            contacts={1: "Alice"},
            messages=[{
                "pk": 1,
                "session": 1,
                "days_ago": 0,
                "from_me": 1,
                "text": "Hello"
            }]
        )
    """
    # Default contacts
    if contacts is None:
        contacts = {1: "Alice", 2: "Bob Smith"}

    # Default messages
    if messages is None:
        now_unix = time.time()
        apple_now = int(now_unix - APPLE_EPOCH_OFFSET)
        day_ago = apple_now - 86400
        week_ago = apple_now - (7 * 86400)

        messages = [
            {"pk": 1, "session": 1, "timestamp": apple_now, "from_me": 0, "text": "Hello from Alice"},
            {"pk": 2, "session": 1, "timestamp": day_ago, "from_me": 1, "text": "Reply to Alice"},
            {"pk": 3, "session": 2, "timestamp": week_ago, "from_me": 0, "text": "Message from Bob"},
            {"pk": 4, "session": 2, "timestamp": day_ago, "from_me": 1, "text": "Reply to Bob about meeting"},
            {"pk": 5, "session": 1, "timestamp": apple_now, "from_me": 0, "text": None},
        ]
    else:
        # Convert days_ago to timestamp if provided
        now_unix = time.time()
        apple_now = int(now_unix - APPLE_EPOCH_OFFSET)
        for msg in messages:
            if "days_ago" in msg and "timestamp" not in msg:
                msg["timestamp"] = apple_now - (msg["days_ago"] * 86400)
                del msg["days_ago"]

    # Create database and tables
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create ZWACHATSESSION table
    cur.execute("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY,
            ZPARTNERNAME TEXT
        )
    """)

    # Create ZWAMESSAGE table
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

    # Insert contacts
    for pk, name in contacts.items():
        cur.execute(
            "INSERT INTO ZWACHATSESSION (Z_PK, ZPARTNERNAME) VALUES (?, ?)",
            (pk, name),
        )

    # Insert messages
    for msg in messages:
        cur.execute(
            """INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT)
               VALUES (?, ?, ?, ?, ?)""",
            (msg["pk"], msg["session"], msg["timestamp"], msg["from_me"], msg["text"]),
        )

    conn.commit()
    conn.close()

    return db_path


@contextmanager
def temp_test_db(
    contacts: Optional[Dict[int, str]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
):
    """Context manager that yields path to a temporary WhatsApp test database.

    Args:
        contacts: Optional dict mapping Z_PK -> ZPARTNERNAME
        messages: Optional list of message dicts (see create_test_db for format)

    Yields:
        Path to temporary database file

    Example:
        with temp_test_db(contacts={1: "Alice"}) as db_path:
            results = search_messages(db_path=db_path)
            assert len(results) > 0
    """
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    db_path = tmp_db.name

    try:
        create_test_db(db_path, contacts=contacts, messages=messages)
        yield db_path
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
