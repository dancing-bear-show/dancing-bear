"""Base Outlook client with authentication and config caching.

This module re-exports from core.outlook.client for backward compatibility.
New code should import directly from core.outlook.
"""

# Re-export everything from core.outlook.client for backward compatibility
from core.outlook.client import (
    OutlookClientBase,
    GRAPH,
    SCOPES,
    DEFAULT_TIMEOUT,
    _requests,
    _msal,
    _TimeoutRequestsWrapper,
)

__all__ = [
    "OutlookClientBase",
    "GRAPH",
    "SCOPES",
    "DEFAULT_TIMEOUT",
    "_requests",
    "_msal",
    "_TimeoutRequestsWrapper",
]
