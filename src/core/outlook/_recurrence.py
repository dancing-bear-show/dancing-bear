"""Recurrence pattern/range builders and reminder helpers for Outlook Graph API."""

from __future__ import annotations

from typing import Any

from core.outlook._location import _normalize_days


def _build_recurrence_pattern(repeat: str, interval: int, byday: list[str] | None) -> dict[str, Any]:
    """Build recurrence pattern for Graph API."""
    rpt = (repeat or "").strip().lower()
    pattern: dict[str, Any] = {"interval": max(1, int(interval))}
    if rpt == "daily":
        pattern["type"] = "daily"
    elif rpt == "weekly":
        pattern["type"] = "weekly"
        pattern["daysOfWeek"] = _normalize_days(byday or [])
    elif rpt in ("monthly", "absolutemonthly"):
        pattern["type"] = "absoluteMonthly"
    else:
        raise ValueError("Unsupported repeat; use daily|weekly|monthly")
    return pattern


def _build_recurrence_range(start_date: str, until: str | None, count: int | None) -> dict[str, Any]:
    """Build recurrence range for Graph API."""
    rng: dict[str, Any] = {"startDate": start_date}
    if until:
        rng["type"] = "endDate"
        rng["endDate"] = until
    elif count:
        rng["type"] = "numbered"
        rng["numberOfOccurrences"] = int(count)
    else:
        rng["type"] = "noEnd"
    return rng


def _apply_reminder(payload: dict[str, Any], no_reminder: bool, reminder_minutes: int | None) -> None:
    """Apply reminder settings to an event payload."""
    if no_reminder:
        payload["isReminderOn"] = False
    elif reminder_minutes is not None:
        payload["isReminderOn"] = True
        payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
