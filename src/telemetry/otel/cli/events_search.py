"""events-search subcommand — search telemetry events by pattern."""

from __future__ import annotations

import argparse
import re
from datetime import datetime

from core.cli_output import emit_rows
from telemetry.otel.cli._format_helpers import (
    add_data_dir_argument,
    add_format_argument,
    add_since_argument,
    resolve_data_dir,
    resolve_since,
    truncate_sid,
)
from telemetry.otel.reader import OTLPDataDir, OTLPReader


def main(argv: list[str] | None = None) -> int:
    """Search telemetry events by substring or regex pattern."""
    args = _parse_args(argv)
    data_dir = resolve_data_dir(args)
    since, err = resolve_since(args)
    if err is not None:
        return err

    pattern = _compile_pattern(args.contains)
    matches = _search_events(data_dir, since, pattern, args.session, args.limit)

    headers = ["timestamp", "session_id", "event_type", "matching_text"]
    display_rows = [
        {
            "timestamp": m["timestamp"],
            "session_id": truncate_sid(m["session_id"]),
            "event_type": m["event_type"],
            "matching_text": m["matching_text"][:60] if args.format == "table" else m["matching_text"],
        }
        for m in matches
    ]
    return emit_rows(display_rows, args.format, headers=headers, empty_msg="No matching events found.")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="telemetry events-search",
        description="Search telemetry events by pattern",
    )
    parser.add_argument(
        "--contains",
        type=str,
        required=True,
        help="Substring or regex pattern to match against event body or attribute values",
    )
    add_since_argument(parser)
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of results (default: 50)",
    )
    parser.add_argument(
        "--session",
        type=str,
        help="Filter to a specific session ID",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    add_data_dir_argument(parser)
    return parser.parse_args(argv)


def _compile_pattern(contains: str) -> re.Pattern[str]:
    """Compile a search pattern, falling back to escaped literal."""
    try:
        return re.compile(contains)
    except re.error:
        return re.compile(re.escape(contains))


def _search_events(
    data_dir: OTLPDataDir,
    since: datetime | None,
    pattern: re.Pattern[str],
    session_filter: str | None,
    limit: int,
) -> list[dict]:
    """Search OTLP events for pattern matches."""
    reader = OTLPReader(data_dir)
    events = reader.read_events()

    matches: list[dict] = []
    for record in events:
        for event in record.log_records:
            match = _check_event(event, since, pattern, session_filter)
            if match is not None:
                matches.append(match)
                if len(matches) >= limit:
                    return matches

    return matches


def _get_session_id(event: object) -> str:
    """Extract session ID from an event."""
    return (
        event.get_attr("session.id")  # type: ignore[union-attr]
        or event.get_attr("session_id")  # type: ignore[union-attr]
        or "unknown"
    )


def _check_event(
    event: object,
    since: datetime | None,
    pattern: re.Pattern[str],
    session_filter: str | None,
) -> dict | None:
    """Check a single event against filters and pattern. Returns match dict or None."""
    if since and event.timestamp < since:  # type: ignore[union-attr]
        return None

    session_id = _get_session_id(event)
    if session_filter and session_id != session_filter:
        return None

    matching_text = _find_match(event, pattern)
    if matching_text is None:
        return None

    return {
        "timestamp": event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),  # type: ignore[union-attr]
        "session_id": session_id,
        "event_type": event.body,  # type: ignore[union-attr]
        "matching_text": matching_text,
    }


def _find_match(event: object, pattern: re.Pattern[str]) -> str | None:
    """Check if event body or any attribute value matches the pattern."""
    if pattern.search(event.body):  # type: ignore[union-attr]
        return event.body  # type: ignore[union-attr]

    for attr in event.attributes:  # type: ignore[union-attr]
        val = attr.value.as_str()
        if pattern.search(val):
            return f"{attr.key}={val}"

    return None
