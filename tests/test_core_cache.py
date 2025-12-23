"""Tests for core/cache.py ConfigCacheMixin."""

import json
import os
import tempfile
import time
import unittest

from core.cache import ConfigCacheMixin


class TestConfigCacheMixin(unittest.TestCase):
    """Tests for ConfigCacheMixin JSON caching."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mixin = ConfigCacheMixin(self.tmpdir, provider="testprovider")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cfg_get_json_returns_none_when_no_cache_dir(self):
        mixin = ConfigCacheMixin(None, provider="test")
        self.assertIsNone(mixin.cfg_get_json("key", ttl=300))

    def test_cfg_get_json_returns_none_when_file_missing(self):
        self.assertIsNone(self.mixin.cfg_get_json("nonexistent", ttl=300))

    def test_cfg_put_and_get_json_roundtrip(self):
        data = {"foo": "bar", "count": 42}
        self.mixin.cfg_put_json("mykey", data)
        result = self.mixin.cfg_get_json("mykey", ttl=300)
        self.assertEqual(result, data)

    def test_cfg_get_json_respects_ttl(self):
        data = {"value": 123}
        self.mixin.cfg_put_json("ttlkey", data)

        # Should return data when fresh
        self.assertEqual(self.mixin.cfg_get_json("ttlkey", ttl=300), data)

        # Manually set file mtime to past
        cache_path = self.mixin._cfg_cache_path("ttlkey")
        old_time = time.time() - 400  # 400 seconds ago
        os.utime(cache_path, (old_time, old_time))

        # Should return None when expired
        self.assertIsNone(self.mixin.cfg_get_json("ttlkey", ttl=300))

    def test_cfg_get_json_ttl_zero_ignores_age(self):
        data = {"value": "old"}
        self.mixin.cfg_put_json("noexpiry", data)

        # Set mtime to very old
        cache_path = self.mixin._cfg_cache_path("noexpiry")
        old_time = time.time() - 86400  # 1 day ago
        os.utime(cache_path, (old_time, old_time))

        # TTL=0 should still return data
        self.assertEqual(self.mixin.cfg_get_json("noexpiry", ttl=0), data)

    def test_cfg_put_json_no_cache_dir_is_noop(self):
        mixin = ConfigCacheMixin(None, provider="test")
        # Should not raise
        mixin.cfg_put_json("key", {"data": True})

    def test_cfg_cache_path_structure(self):
        path = self.mixin._cfg_cache_path("labels")
        expected = os.path.join(self.tmpdir, "testprovider", "config", "labels.json")
        self.assertEqual(path, expected)

    def test_cfg_clear_removes_config_dir(self):
        self.mixin.cfg_put_json("a", {"x": 1})
        self.mixin.cfg_put_json("b", {"y": 2})

        config_dir = os.path.join(self.tmpdir, "testprovider", "config")
        self.assertTrue(os.path.isdir(config_dir))

        self.mixin.cfg_clear()
        self.assertFalse(os.path.isdir(config_dir))

    def test_cfg_get_json_handles_invalid_json(self):
        # Write invalid JSON directly
        cache_path = self.mixin._cfg_cache_path("badfile")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            f.write("not valid json {{{")

        self.assertIsNone(self.mixin.cfg_get_json("badfile", ttl=300))


if __name__ == "__main__":
    unittest.main()
