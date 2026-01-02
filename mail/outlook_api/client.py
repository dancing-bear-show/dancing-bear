"""Base Outlook client with authentication and config caching.

This module re-exports from core.outlook.client for backward compatibility.
New code should import directly from core.outlook.
"""

# Re-export everything from core.outlook.client for backward compatibility
from core.outlook.client import (
    OutlookClientBase,
    _requests,
    _msal,
    _TimeoutRequestsWrapper,
)
from core.constants import (
    GRAPH_API_URL,
    GRAPH_API_SCOPES,
    DEFAULT_REQUEST_TIMEOUT,
)

__all__ = [
    "OutlookClientBase",
    "GRAPH_API_URL",
    "GRAPH_API_SCOPES",
    "DEFAULT_REQUEST_TIMEOUT",
    "_requests",
    "_msal",
    "_TimeoutRequestsWrapper",
]
