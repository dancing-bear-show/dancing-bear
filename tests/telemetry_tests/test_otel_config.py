"""Tests for telemetry.otel.config — RetentionConfig, _resolve_config_path, load_retention_config."""

import tempfile
import unittest
from pathlib import Path

from telemetry.otel.config import (
    DataTypeRetention,
    RetentionConfig,
    _get_repo_root,
    _resolve_config_path,
    load_retention_config,
)


class TestDataTypeRetention(unittest.TestCase):
    def test_keep_days_stored(self):
        r = DataTypeRetention(keep_days=14)
        self.assertEqual(r.keep_days, 14)

    def test_frozen(self):
        r = DataTypeRetention(keep_days=7)
        with self.assertRaises(AttributeError):
            r.keep_days = 99


class TestRetentionConfigFromDict(unittest.TestCase):
    def test_full_dict(self):
        d = {
            "metrics": {"keep_days": 7},
            "events": {"keep_days": 14},
            "spans": {"keep_days": 21},
            "min_records_after_prune": 5,
        }
        rc = RetentionConfig.from_dict(d)
        self.assertEqual(rc.metrics.keep_days, 7)
        self.assertEqual(rc.events.keep_days, 14)
        self.assertEqual(rc.spans.keep_days, 21)
        self.assertEqual(rc.min_records_after_prune, 5)

    def test_empty_dict_all_defaults(self):
        rc = RetentionConfig.from_dict({})
        self.assertEqual(rc.metrics.keep_days, 30)
        self.assertEqual(rc.events.keep_days, 30)
        self.assertEqual(rc.spans.keep_days, 30)
        self.assertEqual(rc.min_records_after_prune, 10)

    def test_missing_metrics_defaults(self):
        d = {
            "events": {"keep_days": 5},
            "spans": {"keep_days": 6},
        }
        rc = RetentionConfig.from_dict(d)
        self.assertEqual(rc.metrics.keep_days, 30)
        self.assertEqual(rc.events.keep_days, 5)
        self.assertEqual(rc.spans.keep_days, 6)

    def test_missing_events_defaults(self):
        d = {
            "metrics": {"keep_days": 3},
            "spans": {"keep_days": 4},
        }
        rc = RetentionConfig.from_dict(d)
        self.assertEqual(rc.events.keep_days, 30)
        self.assertEqual(rc.metrics.keep_days, 3)

    def test_missing_spans_defaults(self):
        d = {
            "metrics": {"keep_days": 1},
            "events": {"keep_days": 2},
        }
        rc = RetentionConfig.from_dict(d)
        self.assertEqual(rc.spans.keep_days, 30)

    def test_missing_min_records_defaults_to_10(self):
        rc = RetentionConfig.from_dict({"metrics": {"keep_days": 7}})
        self.assertEqual(rc.min_records_after_prune, 10)

    def test_partial_dict_metrics_only(self):
        rc = RetentionConfig.from_dict({"metrics": {"keep_days": 60}})
        self.assertEqual(rc.metrics.keep_days, 60)
        self.assertEqual(rc.events.keep_days, 30)
        self.assertEqual(rc.spans.keep_days, 30)

    def test_returns_retention_config_instance(self):
        rc = RetentionConfig.from_dict({})
        self.assertIsInstance(rc, RetentionConfig)
        self.assertIsInstance(rc.metrics, DataTypeRetention)
        self.assertIsInstance(rc.events, DataTypeRetention)
        self.assertIsInstance(rc.spans, DataTypeRetention)


class TestResolveConfigPath(unittest.TestCase):
    def test_explicit_config_dir(self):
        result = _resolve_config_path("/some/custom/dir")
        self.assertEqual(result, Path("/some/custom/dir") / "retention.yaml")

    def test_explicit_config_dir_name(self):
        result = _resolve_config_path("/some/custom/dir")
        self.assertEqual(result.name, "retention.yaml")

    def test_default_ends_with_expected_suffix(self):
        result = _resolve_config_path(None)
        self.assertTrue(
            str(result).endswith("configs/telemetry/retention.yaml"),
            f"Expected path to end with configs/telemetry/retention.yaml, got {result}",
        )

    def test_default_parent_is_telemetry(self):
        result = _resolve_config_path(None)
        self.assertEqual(result.parent.name, "telemetry")

    def test_default_grandparent_is_configs(self):
        result = _resolve_config_path(None)
        self.assertEqual(result.parent.parent.name, "configs")

    def test_repo_root_is_not_src(self):
        # Regression guard: _get_repo_root previously landed one level short,
        # at <repo>/src instead of <repo>, resolving retention.yaml (and the
        # otel compose file, which shares this helper) to a nonexistent path.
        root = _get_repo_root()
        self.assertNotEqual(root.name, "src")

    def test_repo_root_contains_compose_marker(self):
        # docker-compose.otel.yaml lives at the true repo root and is a
        # sibling consumer of this same helper (telemetry.collector).
        root = _get_repo_root()
        self.assertTrue(
            (root / "docker-compose.otel.yaml").exists(),
            f"Expected {root / 'docker-compose.otel.yaml'} to exist",
        )


class TestLoadRetentionConfig(unittest.TestCase):
    def _write_yaml(self, tmpdir: str, content: str) -> str:
        path = Path(tmpdir) / "retention.yaml"
        path.write_text(content, encoding="utf-8")
        return tmpdir

    def test_valid_yaml_parsed_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_yaml(
                tmpdir,
                "metrics:\n  keep_days: 7\nevents:\n  keep_days: 14\nspans:\n  keep_days: 21\nmin_records_after_prune: 5\n",
            )
            rc = load_retention_config(config_dir=tmpdir)
        self.assertEqual(rc.metrics.keep_days, 7)
        self.assertEqual(rc.events.keep_days, 14)
        self.assertEqual(rc.spans.keep_days, 21)
        self.assertEqual(rc.min_records_after_prune, 5)

    def test_returns_retention_config_instance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_yaml(tmpdir, "metrics:\n  keep_days: 3\n")
            rc = load_retention_config(config_dir=tmpdir)
        self.assertIsInstance(rc, RetentionConfig)

    def test_file_not_found_raises_file_not_found_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # No retention.yaml written
            with self.assertRaises(FileNotFoundError) as ctx:
                load_retention_config(config_dir=tmpdir)
        self.assertIn("retention", str(ctx.exception).lower())

    def test_file_not_found_error_includes_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError) as ctx:
                load_retention_config(config_dir=tmpdir)
        # Path should appear in the error message
        self.assertIn(tmpdir, str(ctx.exception))

    def test_empty_yaml_file_produces_default_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_yaml(tmpdir, "")
            rc = load_retention_config(config_dir=tmpdir)
        # Empty YAML -> safe_load returns None -> falls back to {} -> all defaults
        self.assertEqual(rc.metrics.keep_days, 30)
        self.assertEqual(rc.events.keep_days, 30)
        self.assertEqual(rc.spans.keep_days, 30)
        self.assertEqual(rc.min_records_after_prune, 10)

    def test_partial_yaml_merges_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_yaml(tmpdir, "metrics:\n  keep_days: 90\n")
            rc = load_retention_config(config_dir=tmpdir)
        self.assertEqual(rc.metrics.keep_days, 90)
        self.assertEqual(rc.events.keep_days, 30)
        self.assertEqual(rc.spans.keep_days, 30)


if __name__ == "__main__":
    unittest.main()
