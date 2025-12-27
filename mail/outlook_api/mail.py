"""Mail operations for Outlook via Microsoft Graph.

This module re-exports from core.outlook.mail for backward compatibility.
New code should import directly from core.outlook.
"""

# Re-export everything from core.outlook.mail for backward compatibility
from core.outlook.mail import OutlookMailMixin
from core.outlook.client import OutlookClientBase, _requests, GRAPH

__all__ = [
    "OutlookMailMixin",
    "OutlookClientBase",
    "_requests",
    "GRAPH",
]
