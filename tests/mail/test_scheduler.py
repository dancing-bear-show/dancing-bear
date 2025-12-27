"""Tests for mail/scheduler.py scheduled send queue."""

import json
import os
import tempfile
import time
import unittest

from mail.scheduler import (
    ScheduledItem,
    parse_send_at,
    parse_send_in,
    enqueue,
    pop_due,
    _queue_path,
    _load_queue,
    _save_queue,
)


class ParseSendAtTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(parse_send_at(""))
        self.assertIsNone(parse_send_at(None))

    def test_date_space_time(self):
        result = parse_send_at("2025-01-15 14:30")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)

    def test_date_space_time_seconds(self):
        result = parse_send_at("2025-01-15 14:30:00")
        self.assertIsNotNone(result)

    def test_iso8601_format(self):
        result = parse_send_at("2025-01-15T14:30")
        self.assertIsNotNone(result)

    def test_iso8601_with_seconds(self):
        result = parse_send_at("2025-01-15T14:30:45")
        self.assertIsNotNone(result)

    def test_invalid_format_returns_none(self):
        self.assertIsNone(parse_send_at("not a date"))
        self.assertIsNone(parse_send_at("01/15/2025"))
        self.assertIsNone(parse_send_at("tomorrow"))

    def test_whitespace_stripped(self):
        result = parse_send_at("  2025-01-15 14:30  ")
        self.assertIsNotNone(result)

    def test_returns_epoch_seconds(self):
        result = parse_send_at("2025-01-01 00:00")
        # Should be a reasonable epoch timestamp
        self.assertGreater(result, 1700000000)


class ParseSendInTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(parse_send_in(""))
        self.assertIsNone(parse_send_in(None))

    def test_minutes(self):
        self.assertEqual(parse_send_in("90m"), 90 * 60)
        self.assertEqual(parse_send_in("5m"), 5 * 60)

    def test_hours(self):
        self.assertEqual(parse_send_in("2h"), 2 * 3600)
        self.assertEqual(parse_send_in("1h"), 3600)

    def test_days(self):
        self.assertEqual(parse_send_in("1d"), 86400)
        self.assertEqual(parse_send_in("7d"), 7 * 86400)

    def test_seconds(self):
        self.assertEqual(parse_send_in("30s"), 30)
        self.assertEqual(parse_send_in("120s"), 120)

    def test_combined_units(self):
        self.assertEqual(parse_send_in("1h30m"), 3600 + 1800)
        self.assertEqual(parse_send_in("2d4h"), 2 * 86400 + 4 * 3600)
        self.assertEqual(parse_send_in("1d2h30m"), 86400 + 7200 + 1800)

    def test_case_insensitive(self):
        self.assertEqual(parse_send_in("1H"), 3600)
        self.assertEqual(parse_send_in("30M"), 1800)
        self.assertEqual(parse_send_in("1D"), 86400)

    def test_whitespace_stripped(self):
        self.assertEqual(parse_send_in("  1h  "), 3600)

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_send_in("abc"))
        self.assertIsNone(parse_send_in("tomorrow"))


class ScheduledItemTests(unittest.TestCase):
    def test_create_item(self):
        item = ScheduledItem(
            provider="gmail",
            profile="gmail_personal",
            due_at=1700000000,
            raw_b64="base64encodeddata",
        )
        self.assertEqual(item.provider, "gmail")
        self.assertEqual(item.profile, "gmail_personal")
        self.assertEqual(item.due_at, 1700000000)

    def test_optional_fields(self):
        item = ScheduledItem(
            provider="gmail",
            profile="test",
            due_at=1700000000,
            raw_b64="data",
            thread_id="thread123",
            to="recipient@example.com",
            subject="Test Subject",
        )
        self.assertEqual(item.thread_id, "thread123")
        self.assertEqual(item.to, "recipient@example.com")
        self.assertEqual(item.subject, "Test Subject")


class QueueOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue_file = os.path.join(self.tmpdir, "scheduled_sends.json")
        os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = self.queue_file

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if "MAIL_ASSISTANT_SCHEDULE_PATH" in os.environ:
            del os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"]

    def test_load_empty_queue(self):
        result = _load_queue()
        self.assertEqual(result, [])

    def test_save_and_load_queue(self):
        items = [{"provider": "gmail", "due_at": 1700000000}]
        _save_queue(items)

        result = _load_queue()
        self.assertEqual(result, items)

    def test_enqueue_item(self):
        item = ScheduledItem(
            provider="gmail",
            profile="test",
            due_at=1700000000,
            raw_b64="data",
        )
        enqueue(item)

        queue = _load_queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["provider"], "gmail")

    def test_enqueue_sets_created_at(self):
        item = ScheduledItem(
            provider="gmail",
            profile="test",
            due_at=1700000000,
            raw_b64="data",
        )
        before = int(time.time())
        enqueue(item)
        after = int(time.time())

        queue = _load_queue()
        self.assertGreaterEqual(queue[0]["created_at"], before)
        self.assertLessEqual(queue[0]["created_at"], after)

    def test_pop_due_returns_due_items(self):
        now = 1700000000
        items = [
            {"provider": "gmail", "profile": "test", "due_at": now - 100, "raw_b64": "a"},
            {"provider": "gmail", "profile": "test", "due_at": now + 100, "raw_b64": "b"},
        ]
        _save_queue(items)

        due = pop_due(now_ts=now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["raw_b64"], "a")

        # Check remaining queue
        remaining = _load_queue()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["raw_b64"], "b")

    def test_pop_due_with_profile_filter(self):
        now = 1700000000
        items = [
            {"provider": "gmail", "profile": "personal", "due_at": now - 100, "raw_b64": "a"},
            {"provider": "gmail", "profile": "work", "due_at": now - 100, "raw_b64": "b"},
        ]
        _save_queue(items)

        due = pop_due(now_ts=now, profile="personal")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["profile"], "personal")

    def test_pop_due_with_limit(self):
        now = 1700000000
        items = [
            {"provider": "gmail", "profile": "test", "due_at": now - 100, "raw_b64": "a"},
            {"provider": "gmail", "profile": "test", "due_at": now - 50, "raw_b64": "b"},
            {"provider": "gmail", "profile": "test", "due_at": now - 25, "raw_b64": "c"},
        ]
        _save_queue(items)

        due = pop_due(now_ts=now, limit=2)
        self.assertEqual(len(due), 2)

        # Third item should remain in queue
        remaining = _load_queue()
        self.assertEqual(len(remaining), 1)


if __name__ == "__main__":
    unittest.main()
