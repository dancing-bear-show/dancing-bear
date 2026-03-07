"""Demo tests showing builder usage patterns."""

import csv
import unittest

from tests.builders import MessageBuilder, EventBuilder, CSVBuilder


class TestMessageBuilder(unittest.TestCase):
    """Demo tests for MessageBuilder."""

    def test_minimal_message(self):
        """Test building minimal message."""
        msg = MessageBuilder("msg1").build()
        self.assertEqual(msg["id"], "msg1")
        self.assertIn("INBOX", msg["labelIds"])

    def test_full_message(self):
        """Test building message with all fields."""
        msg = (
            MessageBuilder("msg123")
            .subject("Meeting Tomorrow")
            .from_("boss@example.com")
            .to("me@example.com")
            .labels(["INBOX", "IMPORTANT", "CATEGORY_PERSONAL"])
            .header("List-ID", "team@company.com")
            .header("X-Priority", "1")
            .internal_date(1704067200000)
            .snippet("Don't forget about...")
            .build()
        )
        self.assertEqual(msg["id"], "msg123")
        self.assertEqual(msg["snippet"], "Don't forget about...")
        self.assertEqual(len(msg["labelIds"]), 3)
        # Check headers
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        self.assertEqual(headers["Subject"], "Meeting Tomorrow")
        self.assertEqual(headers["From"], "boss@example.com")
        self.assertEqual(headers["List-ID"], "team@company.com")


class TestEventBuilder(unittest.TestCase):
    """Demo tests for EventBuilder."""

    def test_minimal_event(self):
        """Test building minimal event."""
        event = EventBuilder().build()
        self.assertEqual(event["subject"], "Test Event")
        self.assertEqual(event["type"], "singleInstance")

    def test_recurring_event(self):
        """Test building recurring event occurrence."""
        event = (
            EventBuilder()
            .subject("Weekly Standup")
            .start("2025-01-13T10:00:00")
            .end("2025-01-13T10:30:00")
            .location("Zoom Room 3")
            .series_id("series_abc123")
            .event_type("occurrence")
            .event_id("evt_456")
            .created("2025-01-01T08:00:00")
            .build()
        )
        self.assertEqual(event["subject"], "Weekly Standup")
        self.assertEqual(event["type"], "occurrence")
        self.assertEqual(event["seriesMasterId"], "series_abc123")
        self.assertEqual(event["location"]["displayName"], "Zoom Room 3")


class TestCSVBuilder(unittest.TestCase):
    """Demo tests for CSVBuilder."""

    def test_build_to_temp_file(self):
        """Test building CSV and writing to temp file."""
        builder = (
            CSVBuilder(["name", "email", "role"])
            .row(["Alice", "alice@example.com", "admin"])
            .row(["Bob", "bob@example.com", "user"])
            .row(["Carol", "carol@example.com", "user"])
        )

        with builder.to_temp_file() as path:
            # Verify file exists and has correct content
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["name"], "Alice")
            self.assertEqual(rows[0]["role"], "admin")
            self.assertEqual(rows[1]["name"], "Bob")
            self.assertEqual(rows[2]["email"], "carol@example.com")

    def test_chain_multiple_rows(self):
        """Test chaining multiple row additions."""
        builder = CSVBuilder(["id", "value"])
        for i in range(5):
            builder.row([str(i), str(i * 100)])

        with builder.to_temp_file() as path:
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                all_rows = list(reader)

            # Header + 5 data rows
            self.assertEqual(len(all_rows), 6)
            self.assertEqual(all_rows[0], ["id", "value"])
            self.assertEqual(all_rows[1], ["0", "0"])
            self.assertEqual(all_rows[5], ["4", "400"])


if __name__ == "__main__":
    unittest.main()
