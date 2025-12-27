"""Tests for mail/cache.py JSON-based cache."""

import json
import os
import tempfile
import unittest

from mail.cache import MailCache


class MailCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = MailCache(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_directories(self):
        self.assertTrue(os.path.isdir(self.cache.meta_dir))
        self.assertTrue(os.path.isdir(self.cache.full_dir))

    def test_get_meta_returns_none_for_missing(self):
        result = self.cache.get_meta("nonexistent-id")
        self.assertIsNone(result)

    def test_put_and_get_meta(self):
        msg_id = "msg123"
        data = {"id": msg_id, "subject": "Test Subject", "from": "sender@example.com"}

        self.cache.put_meta(msg_id, data)
        result = self.cache.get_meta(msg_id)

        self.assertEqual(result, data)

    def test_get_full_returns_none_for_missing(self):
        result = self.cache.get_full("nonexistent-id")
        self.assertIsNone(result)

    def test_put_and_get_full(self):
        msg_id = "msg456"
        data = {
            "id": msg_id,
            "payload": {"body": {"data": "SGVsbG8gV29ybGQ="}},
            "headers": [{"name": "Subject", "value": "Full Message"}],
        }

        self.cache.put_full(msg_id, data)
        result = self.cache.get_full(msg_id)

        self.assertEqual(result, data)

    def test_meta_and_full_are_separate(self):
        msg_id = "msg789"
        meta_data = {"id": msg_id, "snippet": "Preview..."}
        full_data = {"id": msg_id, "payload": {"body": "full content"}}

        self.cache.put_meta(msg_id, meta_data)
        self.cache.put_full(msg_id, full_data)

        self.assertEqual(self.cache.get_meta(msg_id), meta_data)
        self.assertEqual(self.cache.get_full(msg_id), full_data)

    def test_overwrite_existing_meta(self):
        msg_id = "msg-overwrite"
        data1 = {"version": 1}
        data2 = {"version": 2}

        self.cache.put_meta(msg_id, data1)
        self.cache.put_meta(msg_id, data2)

        result = self.cache.get_meta(msg_id)
        self.assertEqual(result["version"], 2)

    def test_handles_unicode_content(self):
        msg_id = "msg-unicode"
        data = {"subject": "Test émojis 🎉 and ñ characters"}

        self.cache.put_meta(msg_id, data)
        result = self.cache.get_meta(msg_id)

        self.assertEqual(result["subject"], data["subject"])

    def test_handles_special_characters_in_id(self):
        # Message IDs can have various characters
        msg_id = "msg_123-abc"
        data = {"id": msg_id}

        self.cache.put_meta(msg_id, data)
        result = self.cache.get_meta(msg_id)

        self.assertEqual(result, data)

    def test_get_meta_handles_corrupted_json(self):
        msg_id = "corrupted"
        path = self.cache._path("meta", msg_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("not valid json {{{")

        result = self.cache.get_meta(msg_id)
        self.assertIsNone(result)

    def test_get_full_handles_corrupted_json(self):
        msg_id = "corrupted-full"
        path = self.cache._path("full", msg_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("invalid")

        result = self.cache.get_full(msg_id)
        self.assertIsNone(result)

    def test_path_generation(self):
        msg_id = "test-id"
        meta_path = self.cache._path("meta", msg_id)
        full_path = self.cache._path("full", msg_id)

        self.assertIn("meta", meta_path)
        self.assertIn("full", full_path)
        self.assertTrue(meta_path.endswith(".json"))
        self.assertTrue(full_path.endswith(".json"))


if __name__ == "__main__":
    unittest.main()
