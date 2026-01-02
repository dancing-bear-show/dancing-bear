"""Base classes and utilities for calendar pipeline components.

Provides shared functionality for Gmail and Outlook pipelines.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.collections import dedupe
from core.date_utils import DAY_MAP, MONTH_MAP, parse_month, to_iso_str
from core.pipeline import BaseProducer, RequestConsumer
from core.auth import build_gmail_service as _build_gmail_service
from core.constants import DAY_START_TIME, DAY_END_TIME

from .gmail_service import GmailService

# Re-export for backward compatibility
__all__ = [
    "RequestConsumer",
    "BaseProducer",
    "GmailAuth",
    "GmailServiceBuilder",
    "DateWindowResolver",
    "check_service_required",
    "to_iso_str",
    "dedupe_events",
    "parse_month",
    "DAY_MAP",
    "MONTH_MAP",
    "MONTH_MAP_FULL",  # Backwards-compatible alias
    "MONTH_MAP_ABBREV",  # Backwards-compatible alias
    "DAY_TO_CODE",  # Backwards-compatible alias
]

# Error message constant
ERR_SERVICE_REQUIRED = "Outlook service is required"


def check_service_required(service: Any, error_msg: str = ERR_SERVICE_REQUIRED) -> None:
    """Raise ValueError if service is None.

    Usage:
        check_service_required(payload.service)
    """
    if service is None:
        raise ValueError(error_msg)


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
        return f"{start}{DAY_START_TIME}", f"{end}{DAY_END_TIME}"

    def resolve_year_end(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Resolve window defaulting to end of current year."""
        today = self._today_factory()
        start = from_date or today.isoformat()
        end = to_date or today.replace(month=12, day=31).isoformat()
        return f"{start}{DAY_START_TIME}", f"{end}{DAY_END_TIME}"


def _default_event_key(ev: Dict[str, Any]) -> tuple:
    """Default key function for event deduplication."""
    return (
        ev.get("subject"),
        tuple(ev.get("byday") or []),
        ev.get("start_time"),
        ev.get("end_time"),
        (ev.get("range") or {}).get("start_date"),
        (ev.get("range") or {}).get("until"),
        ev.get("location"),
    )


def dedupe_events(events: List[Dict[str, Any]], key_fn=None) -> List[Dict[str, Any]]:
    """Remove duplicate events based on a key function.

    Args:
        events: List of event dictionaries.
        key_fn: Function to extract deduplication key from event.
                Defaults to standard event key (subject, byday, times, range, location).

    Returns:
        Deduplicated list of events.
    """
    return dedupe(events, key_fn or _default_event_key)


# Backwards-compatible aliases
MONTH_MAP_FULL = MONTH_MAP
MONTH_MAP_ABBREV = MONTH_MAP
DAY_TO_CODE = DAY_MAP
