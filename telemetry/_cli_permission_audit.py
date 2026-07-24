"""permission-audit subcommand: filter OTel tool_decision events for genuine user prompts.

Reuses the same raw events.jsonl reader path as ``collector events``
(``_OTEL_DATA_DIR`` / ``_parse_otlp_event``) rather than the
``telemetry.otel.reader.OTLPReader`` model layer, so both subcommands stay
consistent about what "the events file" means and degrade the same way
when it is missing, empty, or unreadable.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import datetime, timezone

from rich.console import Console

from core.cli_output import emit_rows
from telemetry.collector import (
    _EVENTS_FILE,
    _OTEL_DATA_DIR,
    _parse_otlp_event,
)

_err_console = Console(stderr=True)

_TOOL_DECISION_BODY = "claude_code.tool_decision"
_SOURCE_USER = "user"
_DEFAULT_THRESHOLD = 5

_PERMISSION_AUDIT_HEADERS = [
    "timestamp",
    "tool_name",
    "decision",
    "session_id",
    "storm_flag",
]


@dataclass(frozen=True)
class PermissionEvent:
    """A single genuine (source=="user") permission prompt event."""

    timestamp: str
    tool_name: str
    decision: str
    session_id: str
    storm: bool

    def to_dict(self) -> dict[str, str | bool]:
        """Convert to the dict shape emitted by emit_rows (storm -> storm_flag)."""
        return {
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "decision": self.decision,
            "session_id": self.session_id,
            "storm_flag": self.storm,
        }


class _EventsFileUnreadable(Exception):
    """Raised when events.jsonl exists but cannot be read."""


def _read_raw_event_lines() -> list[str] | None:
    """Read every line of events.jsonl.

    Returns None when the file is absent, [] when empty.

    Raises _EventsFileUnreadable on OSError.
    """
    events_file = _OTEL_DATA_DIR / _EVENTS_FILE
    if not events_file.exists():
        return None
    try:
        with events_file.open(encoding="utf-8") as fp:
            return [ln.rstrip("\n") for ln in fp if ln.strip()]
    except OSError as exc:
        raise _EventsFileUnreadable(str(exc)) from exc


def _parse_permission_events(lines: list[str]) -> list[dict[str, object]]:
    """Parse raw OTLP JSONL lines into {timestamp, body, attributes} dicts.

    Malformed lines are skipped.
    """
    parsed: list[dict[str, object]] = []
    for line in lines:
        record = _parse_otlp_event(line)
        if record is not None:
            parsed.append(record)
    return parsed


def _filter_tool_decision_events(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep only claude_code.tool_decision events where attributes.source == 'user'."""
    matches = []
    for record in records:
        if record.get("body") != _TOOL_DECISION_BODY:
            continue
        attributes = record.get("attributes") or {}
        if attributes.get("source") != _SOURCE_USER:
            continue
        matches.append(record)
    return matches


def _normalize_session_id(attributes: dict[str, object]) -> str:
    """Normalize the session id attribute, preferring session.id over session_id."""
    return str(attributes.get("session.id") or attributes.get("session_id") or "")


def _apply_since_filter(
    records: list[dict[str, object]], since_dt: datetime
) -> list[dict[str, object]]:
    """Keep only records whose timestamp is at or after since_dt."""
    kept = []
    for record in records:
        ts_str = str(record.get("timestamp", ""))
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if ts >= since_dt:
            kept.append(record)
    return kept


def _build_permission_events(
    records: list[dict[str, object]], threshold: int
) -> list[PermissionEvent]:
    """Group matching records by session_id, count prompts, and build storm-flagged rows."""
    session_counts: collections.Counter[str] = collections.Counter()
    normalized: list[tuple[str, str, str, str]] = []
    for record in records:
        attributes = record.get("attributes") or {}
        session_id = _normalize_session_id(attributes)
        tool_name = str(attributes.get("tool_name", ""))
        decision = str(attributes.get("decision", ""))
        timestamp = str(record.get("timestamp", ""))
        session_counts[session_id] += 1
        normalized.append((timestamp, tool_name, decision, session_id))

    return [
        PermissionEvent(
            timestamp=timestamp,
            tool_name=tool_name,
            decision=decision,
            session_id=session_id,
            storm=session_counts[session_id] >= threshold,
        )
        for timestamp, tool_name, decision, session_id in normalized
    ]


def permission_audit(
    since_dt: datetime, session_id: str | None, threshold: int, fmt: str
) -> int:
    """Filter OTel tool_decision events for genuine user prompts, flag storm sessions, and emit rows.

    A missing or empty events file, or zero events after filtering, is not an
    error — it emits an empty result and returns 0.
    """
    try:
        lines = _read_raw_event_lines()
    except _EventsFileUnreadable as exc:
        _err_console.print(f"[red]Cannot read events file: {exc}[/]")
        return 1
    if lines is None:
        return emit_rows(
            [],
            fmt=fmt,
            headers=_PERMISSION_AUDIT_HEADERS,
            empty_msg="No events file found.",
        )
    if not lines:
        return emit_rows(
            [],
            fmt=fmt,
            headers=_PERMISSION_AUDIT_HEADERS,
            empty_msg="Events file is empty.",
        )

    records = _parse_permission_events(lines)
    records = _filter_tool_decision_events(records)
    records = _apply_since_filter(records, since_dt)
    if session_id:
        records = [
            r for r in records
            if _normalize_session_id(r.get("attributes") or {}) == session_id
        ]

    events = _build_permission_events(records, threshold)
    rows = [e.to_dict() for e in events]
    return emit_rows(
        rows,
        fmt=fmt,
        headers=_PERMISSION_AUDIT_HEADERS,
        empty_msg="No matching permission prompt events.",
    )
