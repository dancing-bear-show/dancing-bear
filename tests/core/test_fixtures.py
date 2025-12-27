"""Tests for shared test fixtures."""

import unittest

from tests.fixtures import (
    FakeGmailClient,
    FakeOutlookClient,
    capture_stdout,
    make_args,
    make_gmail_client,
    make_outlook_client,
    make_outlook_event,
)


class FakeGmailClientTests(unittest.TestCase):
    def test_list_labels_returns_configured_labels(self):
        client = FakeGmailClient(labels=[{"id": "L1", "name": "Work"}])
        labels = client.list_labels()
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]["name"], "Work")

    def test_get_label_id_map_builds_mapping(self):
        client = FakeGmailClient(labels=[
            {"id": "L1", "name": "Work"},
            {"id": "L2", "name": "Personal"},
        ])
        mapping = client.get_label_id_map()
        self.assertEqual(mapping["Work"], "L1")
        self.assertEqual(mapping["Personal"], "L2")

    def test_list_message_ids_matches_query_patterns(self):
        client = FakeGmailClient(
            message_ids_by_query={
                "from:test@example.com": ["m1", "m2", "m3"],
                "subject:report": ["m4"],
            }
        )
        self.assertEqual(client.list_message_ids(query="from:test@example.com"), ["m1", "m2", "m3"])
        self.assertEqual(client.list_message_ids(query="subject:report is:unread"), ["m4"])
        self.assertEqual(client.list_message_ids(query="unmatched"), [])

    def test_create_filter_tracks_mutations(self):
        client = FakeGmailClient()
        result = client.create_filter({"from": "x@y.com"}, {"addLabelIds": ["L1"]})
        self.assertEqual(len(client.created_filters), 1)
        self.assertIn("id", result)

    def test_delete_filter_tracks_deletions(self):
        client = FakeGmailClient()
        client.delete_filter("F123")
        self.assertIn("F123", client.deleted_filter_ids)

    def test_batch_modify_messages_tracks_batches(self):
        client = FakeGmailClient()
        client.batch_modify_messages(["m1", "m2"], ["L1"], ["INBOX"])
        self.assertEqual(len(client.modified_batches), 1)
        self.assertEqual(client.modified_batches[0], (["m1", "m2"], ["L1"], ["INBOX"]))


class FakeOutlookClientTests(unittest.TestCase):
    def test_list_events_returns_configured_events(self):
        events = [make_outlook_event("Meeting", "2025-01-01T10:00:00", "2025-01-01T11:00:00")]
        client = FakeOutlookClient(events=events)
        result = client.list_events_in_range()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["subject"], "Meeting")

    def test_create_event_tracks_mutations(self):
        client = FakeOutlookClient()
        event = {"subject": "New Event"}
        result = client.create_event("cal1", event)
        self.assertEqual(len(client.created_events), 1)
        self.assertIn("id", result)

    def test_get_calendar_by_name(self):
        client = FakeOutlookClient(calendars=[
            {"id": "c1", "name": "Work"},
            {"id": "c2", "name": "Personal"},
        ])
        work = client.get_calendar_by_name("Work")
        self.assertEqual(work["id"], "c1")
        self.assertIsNone(client.get_calendar_by_name("Unknown"))


class HelperTests(unittest.TestCase):
    def test_make_args_includes_defaults(self):
        args = make_args(config="path.yaml")
        self.assertEqual(args.config, "path.yaml")
        self.assertIsNone(args.credentials)
        self.assertIsNone(args.token)

    def test_capture_stdout_captures_print_output(self):
        with capture_stdout() as buf:
            print("Hello, world!")
        self.assertIn("Hello, world!", buf.getvalue())

    def test_make_outlook_event_builds_event_dict(self):
        event = make_outlook_event(
            subject="Test",
            start_iso="2025-01-01T10:00:00",
            end_iso="2025-01-01T11:00:00",
            location="Room A",
        )
        self.assertEqual(event["subject"], "Test")
        self.assertEqual(event["start"]["dateTime"], "2025-01-01T10:00:00")
        self.assertEqual(event["location"]["displayName"], "Room A")


class FactoryTests(unittest.TestCase):
    def test_make_gmail_client_creates_configured_client(self):
        client = make_gmail_client(
            labels=[{"id": "L1", "name": "Test"}],
            message_ids_by_query={"test": ["m1"]},
        )
        self.assertEqual(len(client.list_labels()), 1)
        self.assertEqual(client.list_message_ids(query="test"), ["m1"])

    def test_make_outlook_client_creates_configured_client(self):
        client = make_outlook_client(
            events=[make_outlook_event("Event", "2025-01-01T10:00:00", "2025-01-01T11:00:00")]
        )
        self.assertEqual(len(client.list_events_in_range()), 1)


if __name__ == "__main__":
    unittest.main()
