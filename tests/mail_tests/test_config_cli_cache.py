"""Tests for config_cli pipeline — cache stats, cache clear, cache prune, config inspect."""

import io
import os
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from tests.fixtures import test_path
from core.pipeline import ResultEnvelope

from mail.config_cli.pipeline_cache import (
    # Cache stats
    CacheStatsRequest,
    CacheStatsRequestConsumer,
    CacheStatsProcessor,
    CacheStatsProducer,
    CacheStatsResult,
    # Cache clear
    CacheClearRequest,
    CacheClearRequestConsumer,
    CacheClearProcessor,
    CacheClearProducer,
    CacheClearResult,
    # Cache prune
    CachePruneRequest,
    CachePruneRequestConsumer,
    CachePruneProcessor,
    CachePruneProducer,
    CachePruneResult,
    # Config inspect
    ConfigInspectRequest,
    ConfigInspectRequestConsumer,
    ConfigInspectProcessor,
    ConfigInspectProducer,
    ConfigInspectResult,
    ConfigSection,
)


class CacheStatsTests(TestCase):
    """Tests for cache stats pipeline."""

    def test_cache_stats_consumer_returns_request(self):
        """CacheStatsRequestConsumer returns the request."""
        request = CacheStatsRequest(cache_path=test_path("test"))
        consumer = CacheStatsRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_stats_processor_counts_files(self):
        """CacheStatsProcessor counts files and sizes correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.json").write_text("hello")
            (Path(tmpdir) / "file2.json").write_text("world!")
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "file3.json").write_text("nested")

            request = CacheStatsRequest(cache_path=tmpdir)
            result = CacheStatsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(3, result.payload.files)
            self.assertEqual(5 + 6 + 6, result.payload.size_bytes)  # hello + world! + nested

    def test_cache_stats_processor_empty_dir(self):
        """CacheStatsProcessor handles empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            request = CacheStatsRequest(cache_path=tmpdir)
            result = CacheStatsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.files)
            self.assertEqual(0, result.payload.size_bytes)

    def test_cache_stats_producer_output(self):
        """CacheStatsProducer prints stats."""
        result = ResultEnvelope(
            status="success",
            payload=CacheStatsResult(path=test_path("cache"), files=10, size_bytes=1024),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheStatsProducer().produce(result)
        output = buf.getvalue()
        self.assertIn(test_path("cache"), output)  # noqa: S108 - test fixture path
        self.assertIn("files=10", output)
        self.assertIn("size=1024", output)


class CacheClearTests(TestCase):
    """Tests for cache clear pipeline."""

    def test_cache_clear_consumer_returns_request(self):
        """CacheClearRequestConsumer returns the request."""
        request = CacheClearRequest(cache_path=test_path("test"))  # noqa: S108 - test fixture path
        consumer = CacheClearRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_clear_processor_clears_directory(self):
        """CacheClearProcessor removes the cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "file.json").write_text("data")

            request = CacheClearRequest(cache_path=str(cache_dir))
            result = CacheClearProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertTrue(result.payload.cleared)
            self.assertFalse(cache_dir.exists())

    def test_cache_clear_processor_nonexistent_dir(self):
        """CacheClearProcessor handles nonexistent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "does_not_exist"

            request = CacheClearRequest(cache_path=str(nonexistent))
            result = CacheClearProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertFalse(result.payload.cleared)

    def test_cache_clear_producer_cleared(self):
        """CacheClearProducer prints cleared message."""
        result = ResultEnvelope(
            status="success",
            payload=CacheClearResult(path=test_path("cache"), cleared=True),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("Cleared cache", buf.getvalue())

    def test_cache_clear_producer_not_cleared(self):
        """CacheClearProducer prints not exist message."""
        result = ResultEnvelope(
            status="success",
            payload=CacheClearResult(path=test_path("cache"), cleared=False),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("does not exist", buf.getvalue())


class CachePruneTests(TestCase):
    """Tests for cache prune pipeline."""

    def test_cache_prune_consumer_returns_request(self):
        """CachePruneRequestConsumer returns the request."""
        request = CachePruneRequest(cache_path=test_path("test"), days=7)  # noqa: S108 - test fixture path
        consumer = CachePruneRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_prune_processor_removes_old_files(self):
        """CachePruneProcessor removes files older than specified days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            old_file = Path(tmpdir) / "old.json"
            new_file = Path(tmpdir) / "new.json"
            old_file.write_text("old")
            new_file.write_text("new")

            # Make old file appear old (2 days old)
            old_time = time.time() - (3 * 86400)
            os.utime(old_file, (old_time, old_time))

            request = CachePruneRequest(cache_path=tmpdir, days=1)
            result = CachePruneProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.removed)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())

    def test_cache_prune_processor_nonexistent_dir(self):
        """CachePruneProcessor handles nonexistent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "does_not_exist"

            request = CachePruneRequest(cache_path=str(nonexistent), days=7)
            result = CachePruneProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.removed)

    def test_cache_prune_producer_output(self):
        """CachePruneProducer prints prune results."""
        result = ResultEnvelope(
            status="success",
            payload=CachePruneResult(path=test_path("cache"), removed=5, days=7),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CachePruneProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("Pruned 5 files", output)
        self.assertIn("7 days", output)


class ConfigInspectTests(TestCase):
    """Tests for config inspect pipeline."""

    def test_config_inspect_consumer_returns_request(self):
        """ConfigInspectRequestConsumer returns the request."""
        request = ConfigInspectRequest(path=test_path("test.ini"))  # noqa: S108 - test fixture path
        consumer = ConfigInspectRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_config_inspect_processor_reads_ini(self):
        """ConfigInspectProcessor reads and masks INI values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[mail_assistant.test]\n")
            f.write("credentials = /path/to/creds.json\n")
            f.write("token = /path/to/token.json\n")
            f.name

        try:
            request = ConfigInspectRequest(path=f.name)
            result = ConfigInspectProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, len(result.payload.sections))
            self.assertEqual("mail_assistant.test", result.payload.sections[0].name)
        finally:
            os.unlink(f.name)

    def test_config_inspect_processor_file_not_found(self):
        """ConfigInspectProcessor handles missing file."""
        request = ConfigInspectRequest(path="/nonexistent/config.ini")
        result = ConfigInspectProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("not found", result.diagnostics.get("message", ""))

    def test_config_inspect_processor_section_filter(self):
        """ConfigInspectProcessor filters by section."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[section1]\nkey1 = value1\n")
            f.write("[section2]\nkey2 = value2\n")
            f.name

        try:
            request = ConfigInspectRequest(path=f.name, section="section1")
            result = ConfigInspectProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, len(result.payload.sections))
            self.assertEqual("section1", result.payload.sections[0].name)
        finally:
            os.unlink(f.name)

    def test_config_inspect_producer_output(self):
        """ConfigInspectProducer prints sections."""
        result = ResultEnvelope(
            status="success",
            payload=ConfigInspectResult(
                sections=[ConfigSection(name="test", items=[("key", "value")])]
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ConfigInspectProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("[test]", output)
        self.assertIn("key = value", output)
