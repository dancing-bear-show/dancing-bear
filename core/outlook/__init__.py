"""Outlook API client for Microsoft Graph operations.

This package provides a modular client for Outlook mail and calendar operations:
- client.py: Base authentication and config caching
- calendar.py: Calendar and event operations
- mail.py: Messages, folders, rules, and categories

Usage:
    from core.outlook import OutlookClient

    client = OutlookClient(client_id="...", tenant="consumers", token_path="...")
    client.authenticate()
    calendars = client.list_calendars()
"""

from .client import OutlookClientBase, _requests
from core.constants import GRAPH_API_URL, GRAPH_API_SCOPES
from .calendar import (
    OutlookCalendarMixin,
    CalendarRef,
    ReminderSettings,
    EventContent,
    RecurrenceSettings,
    EventParams,
    RecurringEventParams,
    EventUpdateParams,
)
from .mail import OutlookMailMixin, SearchParams


class OutlookClient(OutlookClientBase, OutlookCalendarMixin, OutlookMailMixin):
    """Microsoft Graph client for Outlook mail and calendar operations.

    Combines base auth/caching with calendar and mail mixins.

    Maps Gmail-like operations to nearest Outlook constructs:
    - Labels -> Outlook categories (many-to-many on messages)
    - Filters -> Inbox rules (messageRules on Inbox)
    - Forwarding -> Rule action forwardTo
    """
    pass


__all__ = [
    "OutlookClient",
    "OutlookClientBase",
    "OutlookCalendarMixin",
    "OutlookMailMixin",
    # Parameter dataclasses
    "CalendarRef",
    "ReminderSettings",
    "EventContent",
    "RecurrenceSettings",
    "EventParams",
    "RecurringEventParams",
    "EventUpdateParams",
    "SearchParams",
    # Constants
    "GRAPH_API_URL",
    "GRAPH_API_SCOPES",
    "_requests",
]
