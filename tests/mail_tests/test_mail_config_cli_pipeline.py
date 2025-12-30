"""Tests for mail/config_cli/pipeline.py."""

import io
import os
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from tests.fixtures import test_path
from core.pipeline import ResultEnvelope

from mail.config_cli.pipeline import (
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
    # Derive labels
    DeriveLabelsRequest,
    DeriveLabelsRequestConsumer,
    DeriveLabelsProcessor,
    DeriveLabelsProducer,
    DeriveLabelsResult,
    # Derive filters
    DeriveFiltersRequest,
    DeriveFiltersRequestConsumer,
    DeriveFiltersProcessor,
    DeriveFiltersProducer,
    DeriveFiltersResult,
    # Optimize filters
    OptimizeFiltersRequest,
    OptimizeFiltersRequestConsumer,
    OptimizeFiltersProcessor,
    OptimizeFiltersProducer,
    OptimizeFiltersResult,
    MergedGroup,
    # Audit filters
    AuditFiltersRequest,
    AuditFiltersRequestConsumer,
    AuditFiltersProcessor,
    AuditFiltersProducer,
    AuditFiltersResult,
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
            payload=CacheStatsResult(path=test_path("cache"), files=10, size_bytes=1024),  # noqa: S108
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheStatsProducer().produce(result)
        output = buf.getvalue()
        self.assertIn(test_path("cache"), output)  # noqa: S108
        self.assertIn("files=10", output)
        self.assertIn("size=1024", output)


class CacheClearTests(TestCase):
    """Tests for cache clear pipeline."""

    def test_cache_clear_consumer_returns_request(self):
        """CacheClearRequestConsumer returns the request."""
        request = CacheClearRequest(cache_path=test_path("test"))  # noqa: S108
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
            payload=CacheClearResult(path=test_path("cache"), cleared=True),  # noqa: S108
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("Cleared cache", buf.getvalue())

    def test_cache_clear_producer_not_cleared(self):
        """CacheClearProducer prints not exist message."""
        result = ResultEnvelope(
            status="success",
            payload=CacheClearResult(path=test_path("cache"), cleared=False),  # noqa: S108
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("does not exist", buf.getvalue())


class CachePruneTests(TestCase):
    """Tests for cache prune pipeline."""

    def test_cache_prune_consumer_returns_request(self):
        """CachePruneRequestConsumer returns the request."""
        request = CachePruneRequest(cache_path=test_path("test"), days=7)  # noqa: S108
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
            payload=CachePruneResult(path=test_path("cache"), removed=5, days=7),  # noqa: S108
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
        request = ConfigInspectRequest(path=test_path("test.ini"))  # noqa: S108
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


class DeriveLabelsTests(TestCase):
    """Tests for derive labels pipeline."""

    def test_derive_labels_consumer_returns_request(self):
        """DeriveLabelsRequestConsumer returns the request."""
        request = DeriveLabelsRequest(in_path="in.yaml", out_gmail="g.yaml", out_outlook="o.yaml")
        consumer = DeriveLabelsRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_derive_labels_processor_creates_files(self):
        """DeriveLabelsProcessor creates gmail and outlook label files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "labels.yaml"
            in_path.write_text("labels:\n  - name: Test\n    color: red\n")

            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            request = DeriveLabelsRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveLabelsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.labels_count)
            self.assertTrue(out_gmail.exists())
            self.assertTrue(out_outlook.exists())

    def test_derive_labels_processor_empty_labels(self):
        """DeriveLabelsProcessor handles empty labels list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("labels: []\n")

            out_gmail = Path(tmpdir) / "g.yaml"
            out_outlook = Path(tmpdir) / "o.yaml"

            request = DeriveLabelsRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveLabelsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.labels_count)

    def test_derive_labels_producer_output(self):
        """DeriveLabelsProducer prints paths."""
        result = ResultEnvelope(
            status="success",
            payload=DeriveLabelsResult(
                gmail_path=test_path("gmail.yaml"),  # noqa: S108
                outlook_path=test_path("outlook.yaml"),  # noqa: S108
                labels_count=5,
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            DeriveLabelsProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("gmail:", output)
        self.assertIn("outlook:", output)


class DeriveFiltersTests(TestCase):
    """Tests for derive filters pipeline."""

    def test_derive_filters_consumer_returns_request(self):
        """DeriveFiltersRequestConsumer returns the request."""
        request = DeriveFiltersRequest(in_path="in.yaml", out_gmail="g.yaml", out_outlook="o.yaml")
        consumer = DeriveFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_derive_filters_processor_creates_files(self):
        """DeriveFiltersProcessor creates gmail and outlook filter files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            in_path.write_text("filters:\n  - match:\n      from: test@example.com\n    action:\n      add: [Label]\n")

            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            request = DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.filters_count)
            self.assertTrue(out_gmail.exists())
            self.assertTrue(out_outlook.exists())

    def test_derive_filters_processor_empty_filters(self):
        """DeriveFiltersProcessor handles empty filters list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("filters: []\n")

            out_gmail = Path(tmpdir) / "g.yaml"
            out_outlook = Path(tmpdir) / "o.yaml"

            request = DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.filters_count)

    def test_derive_filters_producer_output(self):
        """DeriveFiltersProducer prints paths."""
        result = ResultEnvelope(
            status="success",
            payload=DeriveFiltersResult(
                gmail_path=test_path("gmail.yaml"),  # noqa: S108
                outlook_path=test_path("outlook.yaml"),  # noqa: S108
                filters_count=10,
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            DeriveFiltersProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("gmail:", output)
        self.assertIn("outlook:", output)


class OptimizeFiltersTests(TestCase):
    """Tests for optimize filters pipeline."""

    def test_optimize_filters_consumer_returns_request(self):
        """OptimizeFiltersRequestConsumer returns the request."""
        request = OptimizeFiltersRequest(in_path="in.yaml", out_path="out.yaml")
        consumer = OptimizeFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_optimize_filters_processor_merges_rules(self):
        """OptimizeFiltersProcessor merges rules with same destination."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            # Three rules going to same label - should merge
            in_path.write_text("""filters:
  - match:
      from: a@example.com
    action:
      add: [Label1]
  - match:
      from: b@example.com
    action:
      add: [Label1]
  - match:
      from: c@example.com
    action:
      add: [Label1]
  - match:
      from: x@example.com
    action:
      add: [Label2]
""")
            out_path = Path(tmpdir) / "optimized.yaml"

            request = OptimizeFiltersRequest(
                in_path=str(in_path),
                out_path=str(out_path),
                merge_threshold=2,
            )
            result = OptimizeFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(4, result.payload.original_count)
            # 3 merged into 1 + 1 passthrough = 2
            self.assertEqual(2, result.payload.optimized_count)
            self.assertEqual(1, len(result.payload.merged_groups))
            self.assertEqual("Label1", result.payload.merged_groups[0].destination)
            self.assertEqual(3, result.payload.merged_groups[0].rules_merged)

    def test_optimize_filters_processor_empty_filters(self):
        """OptimizeFiltersProcessor handles empty filters list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("filters: []\n")

            out_path = Path(tmpdir) / "out.yaml"

            request = OptimizeFiltersRequest(
                in_path=str(in_path),
                out_path=str(out_path),
            )
            result = OptimizeFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.original_count)
            self.assertEqual(0, result.payload.optimized_count)

    def test_optimize_filters_producer_output(self):
        """OptimizeFiltersProducer prints results."""
        result = ResultEnvelope(
            status="success",
            payload=OptimizeFiltersResult(
                out_path=test_path("optimized.yaml"),  # noqa: S108
                original_count=10,
                optimized_count=5,
                merged_groups=[MergedGroup(destination="Label", rules_merged=3, unique_from_terms=3)],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OptimizeFiltersProducer(preview=False).produce(result)
        output = buf.getvalue()
        self.assertIn("Original=10", output)
        self.assertIn("Optimized=5", output)

    def test_optimize_filters_producer_preview_mode(self):
        """OptimizeFiltersProducer shows merged groups in preview mode."""
        result = ResultEnvelope(
            status="success",
            payload=OptimizeFiltersResult(
                out_path=test_path("optimized.yaml"),  # noqa: S108
                original_count=10,
                optimized_count=5,
                merged_groups=[MergedGroup(destination="Label", rules_merged=3, unique_from_terms=3)],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OptimizeFiltersProducer(preview=True).produce(result)
        output = buf.getvalue()
        self.assertIn("Merged groups", output)
        self.assertIn("Label", output)
        self.assertIn("merged 3 rules", output)


class AuditFiltersTests(TestCase):
    """Tests for audit filters pipeline."""

    def test_audit_filters_consumer_returns_request(self):
        """AuditFiltersRequestConsumer returns the request."""
        request = AuditFiltersRequest(in_path="in.yaml", export_path="export.yaml")
        consumer = AuditFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_audit_filters_processor_calculates_coverage(self):
        """AuditFiltersProcessor calculates filter coverage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Unified filters
            unified_path = Path(tmpdir) / "unified.yaml"
            unified_path.write_text("""filters:
  - match:
      from: known@example.com
    action:
      add: [Label1]
""")
            # Exported filters (from Gmail)
            export_path = Path(tmpdir) / "export.yaml"
            export_path.write_text("""filters:
  - match:
      from: known@example.com
    action:
      add: [Label1]
  - match:
      from: unknown@other.com
    action:
      add: [Label2]
""")
            request = AuditFiltersRequest(
                in_path=str(unified_path),
                export_path=str(export_path),
            )
            result = AuditFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(2, result.payload.simple_total)
            self.assertEqual(1, result.payload.covered)
            self.assertEqual(1, result.payload.not_covered)

    def test_audit_filters_producer_output(self):
        """AuditFiltersProducer prints audit results."""
        result = ResultEnvelope(
            status="success",
            payload=AuditFiltersResult(
                simple_total=100,
                covered=90,
                not_covered=10,
                percentage=10.0,
                missing_samples=[("Label", "missing@example.com")],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=False).produce(result)
        output = buf.getvalue()
        self.assertIn("Simple Gmail rules: 100", output)
        self.assertIn("Covered by unified: 90", output)
        self.assertIn("Not unified: 10", output)

    def test_audit_filters_producer_preview_missing(self):
        """AuditFiltersProducer shows missing samples in preview mode."""
        result = ResultEnvelope(
            status="success",
            payload=AuditFiltersResult(
                simple_total=100,
                covered=90,
                not_covered=10,
                percentage=10.0,
                missing_samples=[("Label", "missing@example.com")],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=True).produce(result)
        output = buf.getvalue()
        self.assertIn("Missing examples", output)
        self.assertIn("missing@example.com", output)
