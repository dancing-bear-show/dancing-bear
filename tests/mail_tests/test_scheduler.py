"""Tests for mail/scheduler.py - targets previously uncovered branches.

Covered gaps:
  lines 15-18  _queue_path() XDG / default config-home branch
  lines 39-40  _load_queue() corrupt-JSON fallback
  line  51->53 enqueue() skips timestamp when created_at already set
  line  66     pop_due() rest.append branch (item not yet due)
  lines 68-71  pop_due() limit overflow: extras go back to rest
  lines 81-97  parse_send_at() all four datetime formats + whitespace
  line  103    parse_send_in() early-exit for empty/None input
  lines 112-117 parse_send_in() all unit branches (s/m/h/d)
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mail.scheduler import (
    ScheduledItem,
    _load_queue,
    _queue_path,
    _save_queue,
    enqueue,
    parse_send_at,
    parse_send_in,
    pop_due,
)


class QueuePathXdgFallbackTests(unittest.TestCase):
    """Exercise the XDG / default-config-home branch of _queue_path (lines 15-18)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Remove the shortcut env var so the fallback path is taken
        self.orig_schedule = os.environ.pop("MAIL_ASSISTANT_SCHEDULE_PATH", None)
        self.orig_xdg = os.environ.pop("XDG_CONFIG_HOME", None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if self.orig_schedule is not None:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = self.orig_schedule
        elif "MAIL_ASSISTANT_SCHEDULE_PATH" in os.environ:
            del os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"]
        if self.orig_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = self.orig_xdg
        elif "XDG_CONFIG_HOME" in os.environ:
            del os.environ["XDG_CONFIG_HOME"]

    def test_uses_xdg_config_home_when_set(self):
        os.environ["XDG_CONFIG_HOME"] = self.tmpdir
        path = _queue_path()
        self.assertTrue(str(path).startswith(self.tmpdir))
        self.assertEqual(path.name, "scheduled_sends.json")
        # Parent directory must be created
        self.assertTrue(path.parent.exists())

    def test_creates_parent_directory(self):
        subdir = os.path.join(self.tmpdir, "deep", "nested")
        os.environ["XDG_CONFIG_HOME"] = subdir
        path = _queue_path()
        self.assertTrue(path.parent.exists())
        self.assertEqual(path.name, "scheduled_sends.json")

    def test_falls_back_to_home_config_when_xdg_unset(self):
        # Without XDG_CONFIG_HOME the path should still end in mail/scheduled_sends.json
        # Patch Path.home so we don't create ~/.config/mail on the real machine
        with patch("pathlib.Path.home", return_value=Path(self.tmpdir)):
            path = _queue_path()
        self.assertEqual(path.name, "scheduled_sends.json")
        self.assertEqual(path.parent.name, "mail")


class LoadQueueCorruptJsonTests(unittest.TestCase):
    """Exercise _load_queue() exception handler for corrupt JSON (lines 39-40)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue_file = os.path.join(self.tmpdir, "scheduled_sends.json")
        os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = self.queue_file

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        del os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"]

    def test_corrupt_json_returns_empty_list(self):
        with open(self.queue_file, "w", encoding="utf-8") as fh:
            fh.write("{not valid json!!!}")
        result = _load_queue()
        self.assertEqual(result, [])

    def test_empty_file_returns_empty_list(self):
        with open(self.queue_file, "w", encoding="utf-8") as fh:
            fh.write("")
        result = _load_queue()
        self.assertEqual(result, [])

    def test_null_json_returns_empty_list(self):
        # json.loads("null") returns None; the `or []` guard covers this
        with open(self.queue_file, "w", encoding="utf-8") as fh:
            fh.write("null")
        result = _load_queue()
        self.assertEqual(result, [])


class EnqueueCreatedAtTests(unittest.TestCase):
    """Exercise the enqueue() branch where created_at is already set (line 51->53)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue_file = os.path.join(self.tmpdir, "scheduled_sends.json")
        os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = self.queue_file

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        del os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"]

    def test_enqueue_preserves_existing_created_at(self):
        fixed_ts = 1700000001
        item = ScheduledItem(
            provider="gmail",
            profile="test",
            due_at=1700000000,
            raw_b64="data",
            created_at=fixed_ts,
        )
        enqueue(item)
        queue = _load_queue()
        self.assertEqual(queue[0]["created_at"], fixed_ts)

    def test_enqueue_sets_created_at_when_zero(self):
        item = ScheduledItem(
            provider="gmail",
            profile="test",
            due_at=1700000000,
            raw_b64="data",
        )
        # Default created_at is 0 - enqueue should overwrite it
        self.assertEqual(item.created_at, 0)
        enqueue(item)
        queue = _load_queue()
        self.assertGreater(queue[0]["created_at"], 0)


class PopDueRestBranchTests(unittest.TestCase):
    """Exercise pop_due() rest-append branch and limit overflow (lines 66, 68-71)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue_file = os.path.join(self.tmpdir, "scheduled_sends.json")
        os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = self.queue_file

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        del os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"]

    def test_future_items_stay_in_queue(self):
        # Line 66: rest.append branch
        now = 1700000000
        _save_queue([
            {"provider": "gmail", "profile": "p", "due_at": now + 9999, "raw_b64": "x"},
        ])
        due = pop_due(now_ts=now)
        self.assertEqual(due, [])
        remaining = _load_queue()
        self.assertEqual(len(remaining), 1)

    def test_limit_overflow_items_kept_in_queue(self):
        # Lines 68-71: due items beyond limit are pushed back to rest
        now = 1700000000
        _save_queue([
            {"provider": "gmail", "profile": "p", "due_at": now - 300, "raw_b64": "a"},
            {"provider": "gmail", "profile": "p", "due_at": now - 200, "raw_b64": "b"},
            {"provider": "gmail", "profile": "p", "due_at": now - 100, "raw_b64": "c"},
        ])
        due = pop_due(now_ts=now, limit=1)
        self.assertEqual(len(due), 1)
        # The remaining two overflow items are back in the queue
        remaining = _load_queue()
        self.assertEqual(len(remaining), 2)

    def test_limit_equal_to_due_count_no_overflow(self):
        now = 1700000000
        _save_queue([
            {"provider": "gmail", "profile": "p", "due_at": now - 10, "raw_b64": "a"},
            {"provider": "gmail", "profile": "p", "due_at": now - 5, "raw_b64": "b"},
        ])
        due = pop_due(now_ts=now, limit=2)
        self.assertEqual(len(due), 2)
        self.assertEqual(_load_queue(), [])

    def test_mixed_due_and_future_with_limit(self):
        now = 1700000000
        _save_queue([
            {"provider": "gmail", "profile": "p", "due_at": now - 10, "raw_b64": "a"},
            {"provider": "gmail", "profile": "p", "due_at": now - 5, "raw_b64": "b"},
            {"provider": "gmail", "profile": "p", "due_at": now + 10, "raw_b64": "c"},
        ])
        due = pop_due(now_ts=now, limit=1)
        self.assertEqual(len(due), 1)
        # One due item overflows back + one future item = 2 remaining
        remaining = _load_queue()
        self.assertEqual(len(remaining), 2)


class ParseSendAtTests(unittest.TestCase):
    """Exercise parse_send_at() - all four datetime formats (lines 81-97)."""

    def test_empty_string_returns_none(self):
        # Line 81: early exit
        self.assertIsNone(parse_send_at(""))

    def test_none_returns_none(self):
        self.assertIsNone(parse_send_at(None))

    def test_whitespace_only_returns_none(self):
        # strip() leaves empty string -> None
        self.assertIsNone(parse_send_at("   "))

    def test_format_date_space_hhmm(self):
        # Format "%Y-%m-%d %H:%M"
        result = parse_send_at("2025-06-15 09:30")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_format_date_space_hhmmss(self):
        # Format "%Y-%m-%d %H:%M:%S"
        result = parse_send_at("2025-06-15 09:30:45")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)

    def test_format_iso_t_hhmm(self):
        # Format "%Y-%m-%dT%H:%M"
        result = parse_send_at("2025-06-15T09:30")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)

    def test_format_iso_t_hhmmss(self):
        # Format "%Y-%m-%dT%H:%M:%S"
        result = parse_send_at("2025-06-15T09:30:45")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)

    def test_leading_trailing_whitespace_stripped(self):
        result = parse_send_at("  2025-06-15 09:30  ")
        self.assertIsNotNone(result)

    def test_invalid_format_returns_none(self):
        # All four strptime attempts fail -> return None (line 97)
        self.assertIsNone(parse_send_at("15/06/2025 09:30"))
        self.assertIsNone(parse_send_at("not-a-date"))
        self.assertIsNone(parse_send_at("2025/06/15 09:30"))

    def test_returns_epoch_int(self):
        result = parse_send_at("2025-01-01 00:00")
        self.assertIsInstance(result, int)
        # 2025 epoch is well above 2023 epoch 1700000000
        self.assertGreater(result, 1700000000)

    def test_seconds_format_differs_from_no_seconds(self):
        without = parse_send_at("2025-06-15 09:30")
        with_sec = parse_send_at("2025-06-15 09:30:00")
        # Both are valid and should resolve to the same epoch second
        self.assertEqual(without, with_sec)


class ParseSendInTests(unittest.TestCase):
    """Exercise parse_send_in() - early exit and all unit branches (lines 103, 112-117)."""

    def test_empty_string_returns_none(self):
        # Line 103: early return for empty string
        self.assertIsNone(parse_send_in(""))

    def test_none_returns_none(self):
        self.assertIsNone(parse_send_in(None))

    def test_seconds_unit(self):
        # Line 112: unit == "s"
        self.assertEqual(parse_send_in("45s"), 45)
        self.assertEqual(parse_send_in("1s"), 1)

    def test_minutes_unit(self):
        # Line 113-114: unit == "m"
        self.assertEqual(parse_send_in("10m"), 600)
        self.assertEqual(parse_send_in("90m"), 5400)

    def test_hours_unit(self):
        # Line 115-116: unit == "h"
        self.assertEqual(parse_send_in("1h"), 3600)
        self.assertEqual(parse_send_in("3h"), 10800)

    def test_days_unit(self):
        # Line 116-117: unit == "d"
        self.assertEqual(parse_send_in("1d"), 86400)
        self.assertEqual(parse_send_in("2d"), 172800)

    def test_combined_hours_and_minutes(self):
        self.assertEqual(parse_send_in("1h30m"), 3600 + 1800)

    def test_combined_days_hours_minutes(self):
        self.assertEqual(parse_send_in("1d2h30m"), 86400 + 7200 + 1800)

    def test_combined_days_seconds(self):
        self.assertEqual(parse_send_in("1d45s"), 86400 + 45)

    def test_case_insensitive(self):
        self.assertEqual(parse_send_in("1H"), 3600)
        self.assertEqual(parse_send_in("30M"), 1800)
        self.assertEqual(parse_send_in("1D"), 86400)
        self.assertEqual(parse_send_in("10S"), 10)

    def test_whitespace_stripped(self):
        self.assertEqual(parse_send_in("  2h  "), 7200)

    def test_no_recognized_units_returns_none(self):
        # regex finds nothing -> total stays 0 -> return None
        self.assertIsNone(parse_send_in("tomorrow"))
        self.assertIsNone(parse_send_in("abc"))
        self.assertIsNone(parse_send_in("xyz999"))


if __name__ == "__main__":
    unittest.main()
