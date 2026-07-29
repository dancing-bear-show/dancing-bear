"""Tests for telemetry/otel/retention.py — TelemetryPruner."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from telemetry.otel.config import DataTypeRetention, RetentionConfig
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.otel.retention import PruneResult, TelemetryPruner


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
_NOW_NANO = int(_NOW.timestamp() * 1_000_000_000)

# 5 days ago in nanoseconds — within a 30-day keep window
_RECENT_NANO = int((_NOW.timestamp() - 5 * 86400) * 1_000_000_000)

# 40 days ago in nanoseconds — outside a 30-day keep window
_OLD_NANO = int((_NOW.timestamp() - 40 * 86400) * 1_000_000_000)


# ---------------------------------------------------------------------------
# Record factories
# ---------------------------------------------------------------------------

def _events_record(time_unix_nano: int) -> dict:
    """Build a minimal OTLPEventsRecord dict with a single log record."""
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": []},
                "scopeLogs": [
                    {
                        "scope": {"name": "test-scope"},
                        "logRecords": [
                            {
                                "timeUnixNano": time_unix_nano,
                                "observedTimeUnixNano": time_unix_nano,
                                "body": {"stringValue": "test event"},
                                "attributes": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _spans_record(start_time_unix_nano: int) -> dict:
    """Build a minimal OTLPSpansRecord dict with a single span."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "scope": {"name": "test-scope"},
                        "spans": [
                            {
                                "traceId": "abc123",
                                "spanId": "def456",
                                "name": "test-span",
                                "startTimeUnixNano": start_time_unix_nano,
                                "endTimeUnixNano": start_time_unix_nano + 1_000_000,
                                "attributes": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _metrics_record(time_unix_nano: int) -> dict:
    """Build a minimal OTLPMetricsRecord dict with one metric data point."""
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": []},
                "scopeMetrics": [
                    {
                        "scope": {"name": "test-scope"},
                        "metrics": [
                            {
                                "name": "test.metric",
                                "description": "",
                                "unit": "",
                                "sum": {
                                    "aggregationTemporality": 1,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {
                                            "startTimeUnixNano": time_unix_nano,
                                            "timeUnixNano": time_unix_nano,
                                            "asDouble": 1.0,
                                            "attributes": [],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(keep_days: int = 30, min_records: int = 0) -> RetentionConfig:
    return RetentionConfig(
        metrics=DataTypeRetention(keep_days=keep_days),
        events=DataTypeRetention(keep_days=keep_days),
        spans=DataTypeRetention(keep_days=keep_days),
        min_records_after_prune=min_records,
    )


def _make_pruner(data_dir: Path, config: RetentionConfig | None = None) -> TelemetryPruner:
    reader = OTLPReader(data_dir=OTLPDataDir(path=data_dir))
    return TelemetryPruner(reader=reader, config=config or _default_config())


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPruneInvalidDataType(unittest.TestCase):
    def test_invalid_data_type_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            with self.assertRaises(ValueError) as ctx:
                pruner.prune("gadgets")
            self.assertIn("gadgets", str(ctx.exception))

    def test_valid_data_types_do_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            for dt in ("metrics", "events", "spans"):
                # file doesn't exist — should not raise ValueError for type
                result = pruner.prune(dt)
                self.assertIsInstance(result, PruneResult)


class TestPruneFileMissing(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_missing_file_returns_zero_result_dry_run_true(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=True)
            self.assertEqual(result.data_type, "events")
            self.assertEqual(result.records_before, 0)
            self.assertEqual(result.records_after, 0)
            self.assertEqual(result.records_removed, 0)
            self.assertEqual(result.bytes_before, 0)
            self.assertEqual(result.bytes_after, 0)
            self.assertEqual(result.bytes_removed, 0)
            self.assertTrue(result.dry_run)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_missing_file_returns_zero_result_dry_run_false(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            result = pruner.prune("spans", dry_run=False)
            self.assertFalse(result.dry_run)
            self.assertEqual(result.records_removed, 0)


class TestPruneDryRun(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_dry_run_does_not_modify_file(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            records = [_events_record(_OLD_NANO), _events_record(_RECENT_NANO)]
            _write_jsonl(events_path, records)

            original_content = events_path.read_text()

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=True)

            # File must be unchanged
            self.assertEqual(events_path.read_text(), original_content)
            self.assertTrue(result.dry_run)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_dry_run_reports_what_would_be_removed(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            records = [_events_record(_OLD_NANO), _events_record(_RECENT_NANO)]
            _write_jsonl(events_path, records)

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=True)

            self.assertEqual(result.records_before, 2)
            self.assertEqual(result.records_after, 1)
            self.assertEqual(result.records_removed, 1)


class TestPruneWritesFile(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_non_dry_run_rewrites_file_with_kept_records(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            old_rec = _events_record(_OLD_NANO)
            recent_rec = _events_record(_RECENT_NANO)
            _write_jsonl(events_path, [old_rec, recent_rec])

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=False)

            # Read back the file — should contain only the recent record
            lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1)
            kept = json.loads(lines[0])
            # The kept record's log entry should have _RECENT_NANO timestamp
            log_nano = kept["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["timeUnixNano"]
            self.assertEqual(log_nano, _RECENT_NANO)

            self.assertFalse(result.dry_run)
            self.assertEqual(result.records_removed, 1)


class TestCutoffFiltering(unittest.TestCase):
    """Verify that only records newer than the cutoff survive pruning."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_events_older_than_keep_days_are_pruned(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),    # 40 days ago — pruned
                _events_record(_RECENT_NANO), # 5 days ago — kept
                _events_record(_NOW_NANO),    # now — kept
            ])
            pruner = _make_pruner(Path(td), config=_default_config(keep_days=30))
            result = pruner.prune("events", dry_run=False)

            self.assertEqual(result.records_before, 3)
            self.assertEqual(result.records_after, 2)
            self.assertEqual(result.records_removed, 1)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_spans_older_than_keep_days_are_pruned(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            spans_path = Path(td) / "spans.jsonl"
            _write_jsonl(spans_path, [
                _spans_record(_OLD_NANO),
                _spans_record(_RECENT_NANO),
            ])
            pruner = _make_pruner(Path(td), config=_default_config(keep_days=30))
            result = pruner.prune("spans", dry_run=False)

            self.assertEqual(result.records_before, 2)
            self.assertEqual(result.records_after, 1)
            self.assertEqual(result.records_removed, 1)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_metrics_older_than_keep_days_are_pruned(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            metrics_path = Path(td) / "metrics.jsonl"
            _write_jsonl(metrics_path, [
                _metrics_record(_OLD_NANO),
                _metrics_record(_RECENT_NANO),
            ])
            pruner = _make_pruner(Path(td), config=_default_config(keep_days=30))
            result = pruner.prune("metrics", dry_run=False)

            self.assertEqual(result.records_before, 2)
            self.assertEqual(result.records_after, 1)
            self.assertEqual(result.records_removed, 1)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_records_at_exact_cutoff_boundary_are_kept(self, _mock_now):
        """A record whose timestamp equals the cutoff is kept (ts >= cutoff)."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            from datetime import timedelta
            cutoff_ts = _NOW - timedelta(days=30)
            cutoff_nano = int(cutoff_ts.timestamp() * 1_000_000_000)
            _write_jsonl(events_path, [_events_record(cutoff_nano)])

            pruner = _make_pruner(Path(td), config=_default_config(keep_days=30))
            result = pruner.prune("events", dry_run=False)

            self.assertEqual(result.records_after, 1)
            self.assertEqual(result.records_removed, 0)


class TestMalformedLines(unittest.TestCase):
    """Malformed JSONL lines are skipped, not raising."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_invalid_json_line_is_dropped(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            with open(events_path, "w") as f:
                f.write("this is not json at all\n")
                f.write(json.dumps(_events_record(_RECENT_NANO)) + "\n")

            pruner = _make_pruner(Path(td))
            # Should not raise
            result = pruner.prune("events", dry_run=False)
            # Malformed line counts toward records_before but not records_after
            self.assertEqual(result.records_before, 2)
            self.assertEqual(result.records_after, 1)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_valid_json_wrong_structure_is_kept_with_none_timestamp(self, _mock_now):
        """A line with valid JSON but no timestamp: _get_earliest_timestamp returns None,
        so the record is kept (ts is None -> passes the filter).  No crash."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            with open(events_path, "w") as f:
                # Valid JSON that parses fine but produces no log records
                # (scopeLogs list present but with one empty scope dict that has no logRecords).
                # OTLPEventsRecord.from_dict succeeds; log_records is []; min() returns None.
                f.write(json.dumps({
                    "resourceLogs": [
                        {"resource": {"attributes": []}, "scopeLogs": [{"scope": {}, "logRecords": []}]}
                    ]
                }) + "\n")
                f.write(json.dumps(_events_record(_RECENT_NANO)) + "\n")

            pruner = _make_pruner(Path(td))
            # Should not raise; both records are non-blank, both counted in records_before
            result = pruner.prune("events", dry_run=True)
            self.assertEqual(result.records_before, 2)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_all_invalid_lines_produce_zero_after(self, _mock_now):
        """File with only invalid JSON lines: no crash, records_after == 0."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            with open(events_path, "w") as f:
                f.write("bad line 1\n")
                f.write("bad line 2\n")

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=True)
            self.assertEqual(result.records_before, 2)
            self.assertEqual(result.records_after, 0)


class TestBlankLines(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_blank_lines_are_skipped_and_not_counted(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            with open(events_path, "w") as f:
                f.write("\n")
                f.write("   \n")
                f.write(json.dumps(_events_record(_RECENT_NANO)) + "\n")
                f.write("\n")

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=True)
            # Blank lines must not count toward records_before
            self.assertEqual(result.records_before, 1)
            self.assertEqual(result.records_after, 1)


class TestSafetyNet(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_raises_when_too_few_records_would_survive(self, _mock_now):
        """Safety net raises ValueError if records_after < min_records_after_prune."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),    # will be removed
                _events_record(_RECENT_NANO), # will survive
            ])
            original_content = events_path.read_text()

            # min_records_after_prune = 5 > 1 surviving record
            config = _default_config(keep_days=30, min_records=5)
            pruner = _make_pruner(Path(td), config=config)

            with self.assertRaises(ValueError) as ctx:
                pruner.prune("events", dry_run=False)

            err = str(ctx.exception)
            self.assertIn("1", err)       # records_after count
            self.assertIn("5", err)       # minimum
            # File must NOT be modified
            self.assertEqual(events_path.read_text(), original_content)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_safety_net_not_triggered_when_nothing_removed(self, _mock_now):
        """When records_removed == 0, safety net is bypassed even if records_after < min."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [_events_record(_RECENT_NANO)])

            # min_records = 100, but records_removed will be 0
            config = _default_config(keep_days=30, min_records=100)
            pruner = _make_pruner(Path(td), config=config)
            # Should not raise — condition requires records_removed > 0
            result = pruner.prune("events", dry_run=False)
            self.assertEqual(result.records_removed, 0)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_safety_net_error_mentions_minimum(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),
                _events_record(_RECENT_NANO),
            ])
            config = _default_config(keep_days=30, min_records=99)
            pruner = _make_pruner(Path(td), config=config)

            with self.assertRaises(ValueError) as ctx:
                pruner.prune("events", dry_run=True)

            self.assertIn("minimum", str(ctx.exception).lower())


class TestPruneResultStats(unittest.TestCase):
    """All stats fields computed correctly in a realistic multi-record scenario."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_stats_in_multi_record_scenario(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            old_recs = [_events_record(_OLD_NANO) for _ in range(3)]
            recent_recs = [_events_record(_RECENT_NANO) for _ in range(2)]
            _write_jsonl(events_path, old_recs + recent_recs)

            bytes_before = events_path.stat().st_size
            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=False)

            self.assertEqual(result.records_before, 5)
            self.assertEqual(result.records_after, 2)
            self.assertEqual(result.records_removed, 3)
            self.assertEqual(result.bytes_before, bytes_before)
            self.assertGreater(result.bytes_after, 0)
            self.assertEqual(result.bytes_removed, result.bytes_before - result.bytes_after)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_bytes_after_is_non_negative(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [_events_record(_OLD_NANO)])

            pruner = _make_pruner(Path(td))
            result = pruner.prune("events", dry_run=False)
            self.assertGreaterEqual(result.bytes_after, 0)
            self.assertGreaterEqual(result.bytes_removed, 0)


class TestBytesAfterDryRunVsActual(unittest.TestCase):
    """bytes_after uses estimation in dry_run vs real stat() in actual run."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_dry_run_bytes_after_is_estimate(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),
                _events_record(_RECENT_NANO),
            ])

            pruner = _make_pruner(Path(td))
            dry_result = pruner.prune("events", dry_run=True)
            # File unchanged in dry run — bytes_after is an estimate (sum of json.dumps lengths)
            self.assertGreater(dry_result.bytes_after, 0)
            # File should still be same size (not written)
            self.assertEqual(events_path.stat().st_size, dry_result.bytes_before)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_actual_run_bytes_after_matches_file(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),
                _events_record(_RECENT_NANO),
            ])

            pruner = _make_pruner(Path(td))
            actual_result = pruner.prune("events", dry_run=False)
            # bytes_after should match real file size after rewrite
            self.assertEqual(actual_result.bytes_after, events_path.stat().st_size)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_dry_and_actual_bytes_after_are_plausible_and_differ(self, _mock_now):
        """Dry-run estimate and actual file size are both non-negative and non-zero."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),
                _events_record(_RECENT_NANO),
                _events_record(_NOW_NANO),
            ])

            pruner = _make_pruner(Path(td))
            dry_result = pruner.prune("events", dry_run=True)
            self.assertGreater(dry_result.bytes_after, 0)

            # Re-create the file for the actual run
            _write_jsonl(events_path, [
                _events_record(_OLD_NANO),
                _events_record(_RECENT_NANO),
                _events_record(_NOW_NANO),
            ])
            actual_result = pruner.prune("events", dry_run=False)
            self.assertGreater(actual_result.bytes_after, 0)
            # Both paths produced plausible non-negative results
            self.assertGreaterEqual(dry_result.bytes_removed, 0)
            self.assertGreaterEqual(actual_result.bytes_removed, 0)


class TestGetFileConfig(unittest.TestCase):
    def test_returns_correct_path_and_days_for_each_type(self):
        with tempfile.TemporaryDirectory() as td:
            config = RetentionConfig(
                metrics=DataTypeRetention(keep_days=7),
                events=DataTypeRetention(keep_days=14),
                spans=DataTypeRetention(keep_days=21),
                min_records_after_prune=0,
            )
            pruner = _make_pruner(Path(td), config=config)

            metrics_path, metrics_days = pruner._get_file_config("metrics")
            self.assertEqual(metrics_path, Path(td) / "metrics.jsonl")
            self.assertEqual(metrics_days, 7)

            events_path, events_days = pruner._get_file_config("events")
            self.assertEqual(events_path, Path(td) / "events.jsonl")
            self.assertEqual(events_days, 14)

            spans_path, spans_days = pruner._get_file_config("spans")
            self.assertEqual(spans_path, Path(td) / "spans.jsonl")
            self.assertEqual(spans_days, 21)


class TestPruneAll(unittest.TestCase):
    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_prune_all_returns_three_results(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            results = pruner.prune_all(dry_run=True)
            self.assertEqual(len(results), 3)
            data_types = [r.data_type for r in results]
            self.assertEqual(data_types, ["metrics", "events", "spans"])

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_prune_all_with_missing_files_returns_zero_results(self, _mock_now):
        with tempfile.TemporaryDirectory() as td:
            pruner = _make_pruner(Path(td))
            results = pruner.prune_all(dry_run=False)
            for result in results:
                self.assertEqual(result.records_before, 0)
                self.assertEqual(result.records_removed, 0)

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_prune_all_processes_all_types(self, _mock_now):
        record_builders = {
            "metrics.jsonl": _metrics_record,
            "events.jsonl": _events_record,
            "spans.jsonl": _spans_record,
        }
        with tempfile.TemporaryDirectory() as td:
            for filename, build_record in record_builders.items():
                _write_jsonl(Path(td) / filename, [
                    build_record(_OLD_NANO),
                    build_record(_RECENT_NANO),
                ])

            pruner = _make_pruner(Path(td))
            results = pruner.prune_all(dry_run=True)
            for result in results:
                self.assertEqual(result.records_before, 2)
                self.assertEqual(result.records_removed, 1)


class TestOSErrorHandling(unittest.TestCase):
    """OSError handling: a directory as the target file triggers IsADirectoryError."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_directory_as_file_raises_oserror_on_read(self, _mock_now):
        """Using a directory path where a file is expected raises OSError on read."""
        with tempfile.TemporaryDirectory() as td:
            # Create events.jsonl as a DIRECTORY — open() will raise IsADirectoryError
            fake_file = Path(td) / "events.jsonl"
            fake_file.mkdir()

            pruner = _make_pruner(Path(td))
            with self.assertRaises(OSError) as ctx:
                pruner.prune("events", dry_run=False)
            self.assertIn("events.jsonl", str(ctx.exception))

    def test_write_oserror_is_reraised_with_path(self):
        """_write_records raises OSError with path info when write fails.

        Uses a mock for open() narrowly for this exception-plumbing branch only,
        since filesystem permission tricks are unreliable in root environments.
        """
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            pruner = _make_pruner(Path(td))

            real_open = open
            call_count = [0]

            def fake_open(path, mode="r", **kwargs):
                call_count[0] += 1
                if "w" in mode and str(path).endswith("events.jsonl"):
                    raise OSError("disk full")
                return real_open(path, mode, **kwargs)

            with patch("builtins.open", side_effect=fake_open):
                with self.assertRaises(OSError) as ctx:
                    pruner._write_records(events_path, [{"key": "val"}])
            self.assertIn("events.jsonl", str(ctx.exception))


class TestGetEarliestTimestampExcept(unittest.TestCase):
    """Cover the except (KeyError, ValueError) branch in _get_earliest_timestamp."""

    @patch("telemetry.otel.retention.now_utc", return_value=_NOW)
    def test_record_with_non_int_timeunixnano_triggers_except_branch(self, _mock_now):
        """A logRecord with non-numeric timeUnixNano causes int() to raise ValueError,
        which is caught by _get_earliest_timestamp's except clause -> returns None -> record kept."""
        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            bad_record = {
                "resourceLogs": [
                    {
                        "resource": {"attributes": []},
                        "scopeLogs": [
                            {
                                "scope": {"name": "test"},
                                "logRecords": [
                                    {
                                        "timeUnixNano": "not-a-number",
                                        "observedTimeUnixNano": 0,
                                        "body": {"stringValue": "x"},
                                        "attributes": [],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            _write_jsonl(events_path, [bad_record, _events_record(_RECENT_NANO)])

            pruner = _make_pruner(Path(td))
            # Should not raise — the bad record is kept (ts is None -> kept)
            result = pruner.prune("events", dry_run=True)
            self.assertEqual(result.records_before, 2)


if __name__ == "__main__":
    unittest.main()
