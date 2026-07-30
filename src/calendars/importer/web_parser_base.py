"""Base helpers for website schedule parsers."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from core.http import HttpClient
from core.constants import DEFAULT_REQUEST_TIMEOUT

from .model import ScheduleItem

# Standard day ordering for table parsing
WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

# Common swim activity names
LEISURE_SWIM = 'Leisure Swim'


@dataclass
class ScheduleItemParams:
    """Parameters for creating a schedule item."""

    subject: str
    byday: list[str]
    start_time: str
    end_time: str
    location: str
    url: str


def _make_schedule_item_from_params(params: ScheduleItemParams) -> ScheduleItem:
    """Create a weekly recurring ScheduleItem from params."""
    return ScheduleItem(
        subject=params.subject,
        recurrence='weekly',
        byday=params.byday,
        start_time=params.start_time,
        end_time=params.end_time,
        range_start=_dt.date.today().isoformat(),
        location=params.location,
        notes=f'Imported from {params.url}',
    )


def _fetch_html(url: str) -> str:
    """Fetch HTML content from URL."""
    try:
        return HttpClient("", timeout=DEFAULT_REQUEST_TIMEOUT).get(url).text
    except Exception as exc:
        r = getattr(exc, "response", None)
        if r is not None:
            return r.text
        raise
