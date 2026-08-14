"""Outlook API client for Microsoft Graph operations.

Thin alias for `core.outlook`, kept because a dozen call sites across metals,
calendars, schedule, and mail import `OutlookClient` from here — and several
tests patch `mail.outlook_api.OutlookClient` as their seam. New code should
import from `core.outlook` directly.
"""

from core.outlook import OutlookClient

__all__ = ["OutlookClient"]
