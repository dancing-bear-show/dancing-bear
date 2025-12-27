"""WhatsApp local database helpers (macOS).

Read-only utilities to query the local desktop app database to find
messages by text/contact/time. No external dependencies.

Notes
- Default DB path: ~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite
- Timestamps: Apple epoch seconds (since 2001-01-01). Convert by adding
  978307200 to get Unix epoch seconds.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


APPLE_EPOCH_OFFSET = 978307200  # seconds to add to get Unix epoch


def default_db_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(
        home,
        "Library",
        "Group Containers",
        "group.net.whatsapp.WhatsApp.shared",
        "ChatStorage.sqlite",
    )


@dataclass
class MessageRow:
    ts: str  # local time, ISO-like
    partner: str
    from_me: int  # 1 or 0
    text: str


def _connect_ro(path: str) -> sqlite3.Connection:
    # Use URI mode for read-only
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _build_like_clause(column: str, terms: Iterable[str], match_all: bool) -> Tuple[str, List[Any]]:
    cleaned = [t.strip().lower() for t in terms if isinstance(t, str) and t.strip()]
    if not cleaned:
        return "", []
    parts = [f"lower({column}) LIKE ?" for _ in cleaned]
    joiner = " AND " if match_all else " OR "
    clause = "(" + joiner.join(parts) + ")"
    params = [f"%{t}%" for t in cleaned]
    return clause, params


def _build_where(
    contains: List[str],
    match_all: bool,
    contact: Optional[str],
    from_me: Optional[bool],
    since_days: Optional[int],
) -> Tuple[str, List[Any]]:
    conds: List[str] = ["m.ZTEXT IS NOT NULL"]
    params: List[Any] = []
    # contains
    clause, clause_params = _build_like_clause("m.ZTEXT", contains or [], match_all)
    if clause:
        conds.append(clause)
        params.extend(clause_params)
    # contact display name
    contact_clause, contact_params = _build_like_clause("s.ZPARTNERNAME", [contact or ""], True)
    if contact_clause:
        conds.append(contact_clause)
        params.extend(contact_params)
    # from_me
    if from_me is True:
        conds.append("m.ZISFROMME = 1")
    elif from_me is False:
        conds.append("m.ZISFROMME = 0")
    # since days -> apple epoch cutoff
    if since_days and since_days > 0:
        now = time.time()
        cutoff_unix = now - (since_days * 86400)
        cutoff_apple = int(cutoff_unix - APPLE_EPOCH_OFFSET)
        conds.append("m.ZMESSAGEDATE >= ?")
        params.append(cutoff_apple)
    return " AND ".join(conds), params


def search_messages(
    *,
    db_path: Optional[str] = None,
    contains: Optional[List[str]] = None,
    match_all: bool = False,
    contact: Optional[str] = None,
    from_me: Optional[bool] = None,
    since_days: Optional[int] = None,
    limit: int = 50,
) -> List[MessageRow]:
    path = os.path.expanduser(db_path or default_db_path())
    if not os.path.exists(path):
        raise FileNotFoundError(f"WhatsApp ChatStorage not found: {path}")
    where, params = _build_where(contains or [], match_all, contact, from_me, since_days)
    # where clause built via _build_where uses parameterized queries (? placeholders)
    sql = (
        "SELECT datetime(m.ZMESSAGEDATE+?,'unixepoch','localtime') AS ts, "  # noqa: S608
        "s.ZPARTNERNAME, m.ZISFROMME, m.ZTEXT "
        "FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION "
        f"WHERE {where} "
        "ORDER BY m.ZMESSAGEDATE DESC "
        "LIMIT ?"
    )
    rows: List[MessageRow] = []
    with _connect_ro(path) as conn:
        cur = conn.cursor()
        args = [APPLE_EPOCH_OFFSET, *params, int(limit)]
        for ts, partner, fromme, text in cur.execute(sql, args):
            rows.append(MessageRow(ts=str(ts or ""), partner=str(partner or ""), from_me=int(fromme or 0), text=str(text or "")))
    return rows


def format_rows_text(rows: Iterable[MessageRow]) -> str:
    out_lines: List[str] = []
    for r in rows:
        who = "me" if r.from_me == 1 else "them"
        snippet = (r.text or "").replace("\n", " ")
        if len(snippet) > 140:
            snippet = snippet[:137] + "…"
        out_lines.append(f"{r.ts}\t{r.partner}\t{who}\t{snippet}")
    return "\n".join(out_lines)


def rows_to_dicts(rows: Iterable[MessageRow]) -> List[Dict[str, Any]]:
    return [
        {"ts": r.ts, "partner": r.partner, "from_me": bool(r.from_me), "text": r.text}
        for r in rows
    ]


def format_rows_json(rows: Iterable[MessageRow], indent: int = 2) -> str:
    return json.dumps(rows_to_dicts(rows), ensure_ascii=False, indent=indent)


