"""Shared fake/mock objects for testing.

Centralized location for fake clients and mock objects used across test suites.

Modules:
    gmail   - FakeGmailClient for Gmail API testing
    outlook - FakeOutlookClient, FakeCalendarService for Outlook/calendar testing
    docx    - FakeDocument, FakeParagraph, FakeRun for python-docx testing
"""

from __future__ import annotations

from tests.fakes.gmail import FakeGmailClient, make_gmail_client
from tests.fakes.outlook import (
    FakeOutlookClient,
    FakeCalendarService,
    make_outlook_client,
)
from tests.fakes.docx import FakeDocument, FakeParagraph, FakeRun

__all__ = [
    # Gmail
    "FakeGmailClient",
    "make_gmail_client",
    # Outlook
    "FakeOutlookClient",
    "FakeCalendarService",
    "make_outlook_client",
    # Docx
    "FakeDocument",
    "FakeParagraph",
    "FakeRun",
]
