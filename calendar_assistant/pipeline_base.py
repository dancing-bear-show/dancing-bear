"""Base classes and utilities for calendar pipeline components.

Provides shared functionality for Gmail and Outlook pipelines.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.pipeline import Producer, ResultEnvelope
from core.auth import build_gmail_service as _build_gmail_service

from .gmail_service import GmailService


@dataclass
class GmailAuth:
    """Gmail authentication configuration."""
    profile: Optional[str]
    credentials: Optional[str]
    token: Optional[str]
    cache_dir: Optional[str]


class GmailServiceBuilder:
    """Builds Gmail service instances."""

    @staticmethod
    def build(auth: GmailAuth, service_cls=None):
        """Build a Gmail service from auth configuration."""
        return _build_gmail_service(
            profile=auth.profile,
            cache_dir=auth.cache_dir,
            credentials_path=auth.credentials,
            token_path=auth.token,
            service_cls=service_cls or GmailService,
        )


class DateWindowResolver:
    """Resolves date windows for calendar queries."""

    def __init__(self, today_factory=None):
        self._today_factory = today_factory or _dt.date.today

    def resolve(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        days_back: int = 30,
        days_forward: int = 180,
    ) -> Tuple[str, str]:
        """Resolve start/end ISO strings for a date window.

        Args:
            from_date: Optional explicit start date (YYYY-MM-DD).
            to_date: Optional explicit end date (YYYY-MM-DD).
            days_back: Default days before today if from_date not specified.
            days_forward: Default days after today if to_date not specified.

        Returns:
            Tuple of (start_iso, end_iso) with time components.
        """
        today = self._today_factory()
        start = from_date or (today - _dt.timedelta(days=days_back)).isoformat()
        end = to_date or (today + _dt.timedelta(days=days_forward)).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"

    def resolve_year_end(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Resolve window defaulting to end of current year."""
        today = self._today_factory()
        start = from_date or today.isoformat()
        end = to_date or today.replace(month=12, day=31).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"


class BaseProducer:
    """Base class for pipeline producers with common error handling."""

    @staticmethod
    def print_error(result: ResultEnvelope) -> bool:
        """Print error message if result failed. Returns True if error was printed."""
        if result.ok():
            return False
        msg = (result.diagnostics or {}).get("message")
        if msg:
            print(msg)
        return True

    @staticmethod
    def print_logs(logs: List[str]) -> None:
        """Print a list of log messages."""
        for line in logs:
            print(line)


def to_iso_str(v: Any) -> Optional[str]:
    """Convert a value to ISO datetime string."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        if isinstance(v, _dt.datetime):
            return v.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(v, _dt.date):
            return v.strftime("%Y-%m-%dT00:00:00")
    except Exception:
        pass  # nosec B110 - fallback to str(v)
    return str(v)


def dedupe_events(events: List[Dict[str, Any]], key_fn=None) -> List[Dict[str, Any]]:
    """Remove duplicate events based on a key function.

    Args:
        events: List of event dictionaries.
        key_fn: Function to extract deduplication key from event.
                Defaults to standard event key (subject, byday, times, range, location).

    Returns:
        Deduplicated list of events.
    """
    if key_fn is None:
        def key_fn(ev):
            return (
                ev.get("subject"),
                tuple(ev.get("byday") or []),
                ev.get("start_time"),
                ev.get("end_time"),
                (ev.get("range") or {}).get("start_date"),
                (ev.get("range") or {}).get("until"),
                ev.get("location"),
            )

    uniq, seen = [], set()
    for ev in events:
        key = key_fn(ev)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ev)
    return uniq


# Month name mappings for date parsing
MONTH_MAP_FULL = {
    m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1
    )
}
MONTH_MAP_ABBREV = {k[:3]: v for k, v in MONTH_MAP_FULL.items()}

# Day name to RFC code mappings
DAY_TO_CODE = {
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
    "sunday": "SU",
}


def parse_month(month_str: str) -> Optional[int]:
    """Parse month name (full or abbreviated) to number (1-12)."""
    cleaned = (month_str or "").strip().lower()
    return MONTH_MAP_FULL.get(cleaned) or MONTH_MAP_ABBREV.get(cleaned[:3])
