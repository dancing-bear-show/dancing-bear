"""Tests for mail/cache.py JSON-based message cache."""

from __future__ import annotations

import os
import tempfile
import unittest

from mail.cache import MailCache


class MailCacheInitTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_creates_meta_dir(self):
        cache = MailCache(self._tmpdir)
        self.assertTrue(os.path.isdir(cache.meta_dir))

    def test_init_creates_full_dir(self):
        cache = MailCache(self._tmpdir)
        self.assertTrue(os.path.isdir(cache.full_dir))

    def test_meta_dir_path(self):
        cache = MailCache(self._tmpdir)
        self.assertEqual(cache.meta_dir, os.path.join(self._tmpdir, "gmail", "messages", "meta"))

    def test_full_dir_path(self):
        cache = MailCache(self._tmpdir)
        self.assertEqual(cache.full_dir, os.path.join(self._tmpdir, "gmail", "messages", "full"))


class MailCacheMetaTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache = MailCache(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_meta_missing_returns_none(self):
        self.assertIsNone(self.cache.get_meta("no-such-id"))

    def test_put_meta_then_get_meta_roundtrip(self):
        # Covers lines 28-30: open + json.load success path
        self.cache.put_meta("m1", {"subject": "Hello", "from": "a@b.com"})
        result = self.cache.get_meta("m1")
        self.assertEqual(result, {"subject": "Hello", "from": "a@b.com"})

    def test_get_meta_returns_none_on_corrupt_json(self):
        # Covers lines 30-31: except Exception -> return None
        path = self.cache._path("meta", "bad-meta")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not: valid json}")
        self.assertIsNone(self.cache.get_meta("bad-meta"))

    def test_put_meta_overwrites_existing(self):
        self.cache.put_meta("m2", {"v": 1})
        self.cache.put_meta("m2", {"v": 2})
        self.assertEqual(self.cache.get_meta("m2"), {"v": 2})

    def test_put_meta_preserves_unicode(self):
        data = {"subject": "Café résumé 🎉"}
        self.cache.put_meta("m-uni", data)
        self.assertEqual(self.cache.get_meta("m-uni"), data)

    def test_get_meta_strips_whitespace_from_id(self):
        # _path() strips leading/trailing whitespace from msg_id
        self.cache.put_meta("spaced", {"k": "v"})
        path_clean = self.cache._path("meta", "spaced")
        path_padded = self.cache._path("meta", "  spaced  ")
        self.assertEqual(path_clean, path_padded)


class MailCacheFullTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache = MailCache(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_full_missing_returns_none(self):
        # Covers lines 40-42: path does not exist -> return None
        self.assertIsNone(self.cache.get_full("no-such-full"))

    def test_put_full_then_get_full_roundtrip(self):
        # Covers lines 43-46: open + json.load success path
        payload = {"id": "f1", "payload": {"body": {"data": "SGVsbG8="}}}
        self.cache.put_full("f1", payload)
        result = self.cache.get_full("f1")
        self.assertEqual(result, payload)

    def test_get_full_returns_none_on_corrupt_json(self):
        # Covers lines 43-47: except Exception -> return None
        path = self.cache._path("full", "bad-full")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<<<not json>>>")
        self.assertIsNone(self.cache.get_full("bad-full"))

    def test_put_full_overwrites_existing(self):
        # Covers lines 50-53: put_full writes file
        self.cache.put_full("f2", {"version": 1})
        self.cache.put_full("f2", {"version": 2})
        self.assertEqual(self.cache.get_full("f2"), {"version": 2})

    def test_put_full_preserves_unicode(self):
        data = {"subject": "Ñoño 🚀"}
        self.cache.put_full("f-uni", data)
        self.assertEqual(self.cache.get_full("f-uni"), data)

    def test_meta_and_full_stored_separately(self):
        meta = {"kind": "meta"}
        full = {"kind": "full"}
        self.cache.put_meta("shared-id", meta)
        self.cache.put_full("shared-id", full)
        self.assertEqual(self.cache.get_meta("shared-id"), meta)
        self.assertEqual(self.cache.get_full("shared-id"), full)


class MailCachePathTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache = MailCache(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_meta_path_ends_with_json(self):
        self.assertTrue(self.cache._path("meta", "abc").endswith(".json"))

    def test_full_path_ends_with_json(self):
        self.assertTrue(self.cache._path("full", "abc").endswith(".json"))

    def test_meta_path_uses_meta_dir(self):
        self.assertIn(self.cache.meta_dir, self.cache._path("meta", "abc"))

    def test_full_path_uses_full_dir(self):
        self.assertIn(self.cache.full_dir, self.cache._path("full", "abc"))

    def test_unknown_kind_uses_full_dir(self):
        # Any kind other than "meta" uses full_dir (branch coverage)
        path = self.cache._path("other", "abc")
        self.assertIn(self.cache.full_dir, path)

    def test_empty_msg_id_produces_dot_json(self):
        path = self.cache._path("meta", "")
        self.assertTrue(path.endswith(".json"))


if __name__ == "__main__":
    unittest.main()
