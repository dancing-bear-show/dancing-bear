"""Calendar and event operations for Outlook via Microsoft Graph.

This module re-exports from core.outlook.calendar for backward compatibility.
New code should import directly from core.outlook.
"""

# Re-export everything from core.outlook.calendar for backward compatibility
from core.outlook.calendar import (
    OutlookCalendarMixin,
    _parse_location,
    _normalize_days,
)
from core.outlook.client import OutlookClientBase, _requests, GRAPH

__all__ = [
    "OutlookCalendarMixin",
    "OutlookClientBase",
    "_requests",
    "GRAPH",
    "_parse_location",
    "_normalize_days",
]
