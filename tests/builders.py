"""Fluent builder classes for common test data.

Provides chainable builders for creating test fixtures:
- MessageBuilder: Gmail message dicts
- EventBuilder: Outlook calendar event dicts
- CSVBuilder: Generic CSV file builder with temp file support
"""

from __future__ import annotations

import csv
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List


class MessageBuilder:
    """Fluent builder for Gmail test messages.

    Example:
        msg = (MessageBuilder("msg1")
               .subject("Meeting")
               .from_("sender@example.com")
               .to("me@example.com")
               .labels(["INBOX", "IMPORTANT"])
               .header("List-ID", "team@list.example.com")
               .internal_date(1704067200000)
               .build())
    """

    def __init__(self, msg_id: str = "msg_1"):
        """Initialize builder with message ID.

        Args:
            msg_id: Message ID (default: "msg_1")
        """
        self._msg_id = msg_id
        self._subject = "Test"
        self._from = "sender@example.com"
        self._to = None
        self._labels = ["INBOX"]
        self._headers = {}
        self._internal_date = None
        self._thread_id = None
        self._snippet = ""

    def subject(self, s: str) -> MessageBuilder:
        """Set message subject.

        Args:
            s: Subject line

        Returns:
            Self for chaining
        """
        self._subject = s
        return self

    def from_(self, addr: str) -> MessageBuilder:
        """Set From header.

        Args:
            addr: Email address (e.g., "user@example.com" or "Name <user@example.com>")

        Returns:
            Self for chaining
        """
        self._from = addr
        return self

    def to(self, addr: str) -> MessageBuilder:
        """Set To header.

        Args:
            addr: Email address

        Returns:
            Self for chaining
        """
        self._to = addr
        return self

    def labels(self, labels: List[str]) -> MessageBuilder:
        """Set message labels (Gmail label IDs).

        Args:
            labels: List of label IDs (e.g., ["INBOX", "UNREAD"])

        Returns:
            Self for chaining
        """
        self._labels = labels
        return self

    def header(self, name: str, value: str) -> MessageBuilder:
        """Add custom header to message.

        Args:
            name: Header name (e.g., "List-ID", "X-Custom")
            value: Header value

        Returns:
            Self for chaining
        """
        self._headers[name] = value
        return self

    def internal_date(self, date_ms: int) -> MessageBuilder:
        """Set internal date timestamp.

        Args:
            date_ms: Timestamp in milliseconds since epoch

        Returns:
            Self for chaining
        """
        self._internal_date = date_ms
        return self

    def thread_id(self, tid: str) -> MessageBuilder:
        """Set thread ID.

        Args:
            tid: Thread ID

        Returns:
            Self for chaining
        """
        self._thread_id = tid
        return self

    def snippet(self, text: str) -> MessageBuilder:
        """Set message snippet/preview text.

        Args:
            text: Preview text

        Returns:
            Self for chaining
        """
        self._snippet = text
        return self

    def build(self) -> Dict[str, Any]:
        """Build Gmail message dict.

        Returns:
            Gmail API message dict format
        """
        # Start with base headers
        headers = [
            {"name": "Subject", "value": self._subject},
            {"name": "From", "value": self._from},
        ]
        if self._to:
            headers.append({"name": "To", "value": self._to})

        # Add custom headers
        for name, value in self._headers.items():
            headers.append({"name": name, "value": value})

        # Build message dict
        msg = {
            "id": self._msg_id,
            "threadId": self._thread_id or f"thread_{self._msg_id}",
            "labelIds": self._labels,
            "payload": {"headers": headers},
        }

        if self._snippet:
            msg["snippet"] = self._snippet

        if self._internal_date is not None:
            msg["internalDate"] = str(self._internal_date)

        return msg


class EventBuilder:
    """Fluent builder for Outlook calendar test events.

    Example:
        event = (EventBuilder()
                 .subject("Team Sync")
                 .start("2025-01-15T10:00:00")
                 .end("2025-01-15T11:00:00")
                 .location("Conference Room A")
                 .series_id("series_123")
                 .event_type("occurrence")
                 .build())
    """

    def __init__(self):
        """Initialize builder with default values."""
        self._subject = "Test Event"
        self._start_iso = "2025-01-01T10:00:00"
        self._end_iso = "2025-01-01T11:00:00"
        self._location = None
        self._series_id = None
        self._event_type = "singleInstance"
        self._id = None
        self._created = None

    def subject(self, s: str) -> EventBuilder:
        """Set event subject/title.

        Args:
            s: Event title

        Returns:
            Self for chaining
        """
        self._subject = s
        return self

    def start(self, iso: str) -> EventBuilder:
        """Set start datetime.

        Args:
            iso: ISO 8601 datetime string (e.g., "2025-01-15T10:00:00")

        Returns:
            Self for chaining
        """
        self._start_iso = iso
        return self

    def end(self, iso: str) -> EventBuilder:
        """Set end datetime.

        Args:
            iso: ISO 8601 datetime string

        Returns:
            Self for chaining
        """
        self._end_iso = iso
        return self

    def location(self, loc: str) -> EventBuilder:
        """Set event location.

        Args:
            loc: Location name

        Returns:
            Self for chaining
        """
        self._location = loc
        return self

    def series_id(self, sid: str) -> EventBuilder:
        """Set series master ID (for recurring events).

        Args:
            sid: Series master ID

        Returns:
            Self for chaining
        """
        self._series_id = sid
        return self

    def event_type(self, etype: str) -> EventBuilder:
        """Set event type.

        Args:
            etype: Event type ("singleInstance", "occurrence", "exception", "seriesMaster")

        Returns:
            Self for chaining
        """
        self._event_type = etype
        return self

    def event_id(self, eid: str) -> EventBuilder:
        """Set event ID.

        Args:
            eid: Event ID

        Returns:
            Self for chaining
        """
        self._id = eid
        return self

    def created(self, iso: str) -> EventBuilder:
        """Set creation datetime.

        Args:
            iso: ISO 8601 datetime string

        Returns:
            Self for chaining
        """
        self._created = iso
        return self

    def build(self) -> Dict[str, Any]:
        """Build Outlook event dict.

        Returns:
            Outlook Graph API event dict format
        """
        event = {
            "subject": self._subject,
            "start": {"dateTime": self._start_iso},
            "end": {"dateTime": self._end_iso},
            "type": self._event_type,
        }

        if self._id:
            event["id"] = self._id

        if self._location:
            event["location"] = {"displayName": self._location}

        if self._series_id:
            event["seriesMasterId"] = self._series_id

        if self._created:
            event["createdDateTime"] = self._created

        return event


class CSVBuilder:
    """Generic CSV builder for tests.

    Example:
        # Build and write to file
        csv = (CSVBuilder(["name", "email", "role"])
               .row(["Alice", "alice@example.com", "admin"])
               .row(["Bob", "bob@example.com", "user"])
               .to_file("/tmp/users.csv"))

        # Or use temp file context manager
        with CSVBuilder(["id", "value"]).row(["1", "100"]).to_temp_file() as path:
            # path is valid temp CSV file
            process_csv(path)
        # File automatically cleaned up after context
    """

    def __init__(self, headers: List[str]):
        """Initialize builder with CSV headers.

        Args:
            headers: Column names
        """
        self.headers = headers
        self.rows: List[List[Any]] = []

    def row(self, values: List[Any]) -> CSVBuilder:
        """Add data row.

        Args:
            values: Column values (must match header count)

        Returns:
            Self for chaining
        """
        self.rows.append(values)
        return self

    def to_file(self, path: str) -> str:
        """Write CSV to file.

        Args:
            path: Output file path

        Returns:
            Path to written file
        """
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.headers)
            writer.writerows(self.rows)
        return path

    @contextmanager
    def to_temp_file(self, suffix: str = ".csv"):
        """Write CSV to temp file and yield path.

        Context manager that automatically cleans up temp file.

        Args:
            suffix: File suffix (default: ".csv")

        Yields:
            Path to temporary CSV file

        Example:
            with builder.to_temp_file() as path:
                process(path)
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=suffix,
            newline="",
            encoding="utf-8",
            delete=False,
        ) as f:
            writer = csv.writer(f)
            writer.writerow(self.headers)
            writer.writerows(self.rows)
            temp_path = f.name

        try:
            yield temp_path
        finally:
            import os
            try:
                os.unlink(temp_path)
            except OSError:  # nosec B110 - ignore if file already deleted
                pass
