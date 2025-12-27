"""Outlook API client for Microsoft Graph operations.

This module re-exports from core.outlook for backward compatibility.
New code should import directly from core.outlook.

Usage:
    from mail.outlook_api import OutlookClient  # Legacy
    from core.outlook import OutlookClient      # Preferred
"""

# Re-export everything from core.outlook for backward compatibility
from core.outlook import (
    OutlookClient,
    OutlookClientBase,
    OutlookCalendarMixin,
    OutlookMailMixin,
    GRAPH,
    SCOPES,
)

# Also re-export from submodules for code that imports from mail.outlook_api.client etc
from core.outlook.client import _requests, DEFAULT_TIMEOUT

__all__ = [
    "OutlookClient",
    "OutlookClientBase",
    "OutlookCalendarMixin",
    "OutlookMailMixin",
    "GRAPH",
    "SCOPES",
    "_requests",
    "DEFAULT_TIMEOUT",
]
