"""Tests for telemetry/otel/cli/workflow_cost.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from telemetry.otel.cli.workflow_cost import (
    _build_since_rows,
    _build_workspace_rows,
    _coerce_float,
    _coerce_int,
    _earliest_started_at,
    _load_stage_if_in_window,
    _read_stage_results,
    main,
)


# ---------------------------------------------------------------------------
# _coerce_float
# ---------------------------------------------------------------------------


class TestCoerceFloat(unittest.TestCase):
    def test_valid_float(self):
        self.assertAlmostEqual(_coerce_float(1.5), 1.5)

    def test_string_float(self):
        self.assertAlmostEqual(_coerce_float("0.05"), 0.05)

    def test_none_returns_zero(self):
        self.assertEqual(_coerce_float(None), 0.0)

    def test_empty_string_returns_zero(self):
        self.assertEqual(_coerce_float(""), 0.0)

    def test_invalid_string_returns_zero(self):
        self.assertEqual(_coerce_float("bad"), 0.0)


# ---------------------------------------------------------------------------
# _coerce_int
# ---------------------------------------------------------------------------


class TestCoerceInt(unittest.TestCase):
    def test_valid_int(self):
        self.assertEqual(_coerce_int(5), 5)

    def test_string_int(self):
        self.assertEqual(_coerce_int("10"), 10)

    def test_none_returns_zero(self):
        self.assertEqual(_coerce_int(None), 0)

    def test_invalid_returns_zero(self):
        self.assertEqual(_coerce_int("bad"), 0)


# ---------------------------------------------------------------------------
# _read_stage_results
# ---------------------------------------------------------------------------


class TestReadStageResults(unittest.TestCase):
    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            result = _read_stage_results(stages)
        self.assertEqual(result, [])

    def test_nonexistent_dir_returns_empty(self):
        result = _read_stage_results(Path("/nonexistent/stages"))
        self.assertEqual(result, [])

    def test_reads_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            (stages / "stage1.json").write_text(json.dumps({"stage_name": "build"}))
            result = _read_stage_results(stages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage_name"], "build")

    def test_skips_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            (stages / "bad.json").write_text("not json!")
            (stages / "good.json").write_text(json.dumps({"stage_name": "ok"}))
            result = _read_stage_results(stages)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _build_workspace_rows
# ---------------------------------------------------------------------------


class TestBuildWorkspaceRows(unittest.TestCase):
    def test_no_cost_metadata(self):
        stages = [{"stage_name": "build", "metadata": {}}]
        rows, has_cost = _build_workspace_rows(stages)
        self.assertFalse(has_cost)
        self.assertEqual(len(rows), 2)  # stage + TOTAL

    def test_with_cost_metadata(self):
        stages = [{
            "stage_name": "build",
            "metadata": {
                "subagent_cost_usd": "0.05",
                "subagent_tokens": "1000",
                "tool_uses": "5",
                "duration_agent_ms": "30000",
                "model": "claude-sonnet-4-6",
            }
        }]
        rows, has_cost = _build_workspace_rows(stages)
        self.assertTrue(has_cost)
        self.assertEqual(rows[0]["stage"], "build")
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.05)
        self.assertEqual(rows[-1]["stage"], "TOTAL")

    def test_total_row_aggregates(self):
        stages = [
            {"stage_name": "s1", "metadata": {"subagent_cost_usd": "0.05", "subagent_tokens": "1000"}},
            {"stage_name": "s2", "metadata": {"subagent_cost_usd": "0.03", "subagent_tokens": "500"}},
        ]
        rows, _ = _build_workspace_rows(stages)
        total = rows[-1]
        self.assertAlmostEqual(total["cost_usd"], 0.08, places=4)
        self.assertEqual(total["tokens"], 1500)


# ---------------------------------------------------------------------------
# _load_stage_if_in_window
# ---------------------------------------------------------------------------


class TestLoadStageIfInWindow(unittest.TestCase):
    def test_recent_stage_returned(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({
                "stage_name": "build",
                "finished_at": "2026-04-16T10:00:00Z",
            }))
            result = _load_stage_if_in_window(p, cutoff)
        self.assertIsNotNone(result)

    def test_old_stage_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({
                "stage_name": "build",
                "finished_at": "2026-04-16T10:00:00Z",
            }))
            result = _load_stage_if_in_window(p, cutoff)
        self.assertIsNone(result)

    def test_missing_finished_at_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            p.write_text(json.dumps({"stage_name": "build"}))
            result = _load_stage_if_in_window(p, datetime.now(timezone.utc))
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            p.write_text("not json")
            result = _load_stage_if_in_window(p, datetime.now(timezone.utc))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _earliest_started_at
# ---------------------------------------------------------------------------


class TestEarliestStartedAt(unittest.TestCase):
    def test_returns_earliest(self):
        stages = [
            {"started_at": "2026-04-16T10:00:00Z"},
            {"started_at": "2026-04-16T09:00:00Z"},
        ]
        result = _earliest_started_at(stages)
        self.assertIn("09:00", result)

    def test_empty_returns_empty_string(self):
        result = _earliest_started_at([])
        self.assertEqual(result, "")

    def test_missing_started_at_skipped(self):
        stages = [{"stage_name": "x"}, {"started_at": "2026-04-16T10:00:00Z"}]
        result = _earliest_started_at(stages)
        self.assertIn("2026", result)


# ---------------------------------------------------------------------------
# _build_since_rows
# ---------------------------------------------------------------------------


class TestBuildSinceRows(unittest.TestCase):
    def test_builds_rows_per_run(self):
        run_groups = {
            "my-workflow-20260416-abc12345": [
                {
                    "started_at": "2026-04-16T09:00:00Z",
                    "finished_at": "2026-04-16T09:30:00Z",
                    "metadata": {"subagent_tokens": "500", "subagent_cost_usd": "0.02"},
                }
            ]
        }
        rows = _build_since_rows(run_groups)
        # Last row is TOTAL
        self.assertEqual(rows[-1]["run_id"], "TOTAL")
        self.assertEqual(len(rows), 2)

    def test_total_aggregates_cost(self):
        run_groups = {
            "run-a-20260416-abc12345": [
                {"metadata": {"subagent_tokens": "100", "subagent_cost_usd": "0.01"}, "started_at": ""}
            ],
            "run-b-20260416-def67890": [
                {"metadata": {"subagent_tokens": "200", "subagent_cost_usd": "0.02"}, "started_at": ""}
            ],
        }
        rows = _build_since_rows(run_groups)
        total = rows[-1]
        self.assertAlmostEqual(total["total_cost_usd"], 0.03, places=4)


# ---------------------------------------------------------------------------
# main — workspace mode
# ---------------------------------------------------------------------------


class TestWorkspaceModeMain(unittest.TestCase):
    def test_workspace_not_found_returns_1(self):
        result = main(["--workspace", "/nonexistent/path"])
        self.assertEqual(result, 1)

    def test_no_stages_returns_1(self):
        with tempfile.TemporaryDirectory() as td:
            result = main(["--workspace", td])
        self.assertEqual(result, 1)

    def test_stages_without_cost_returns_0(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            (stages / "s1.json").write_text(json.dumps({"stage_name": "build", "metadata": {}}))
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                result = main(["--workspace", td])
        self.assertEqual(result, 0)
        self.assertIn("No cost metadata", buf.getvalue())

    def test_stages_with_cost_returns_0(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            (stages / "s1.json").write_text(json.dumps({
                "stage_name": "build",
                "metadata": {"subagent_cost_usd": "0.05", "subagent_tokens": "1000"},
            }))
            with patch("telemetry.otel.cli.workflow_cost.emit_rows", return_value=0):
                result = main(["--workspace", td])
        self.assertEqual(result, 0)

    def test_json_format(self):
        with tempfile.TemporaryDirectory() as td:
            stages = Path(td) / "stages"
            stages.mkdir()
            (stages / "s1.json").write_text(json.dumps({
                "stage_name": "build",
                "metadata": {"subagent_cost_usd": "0.05", "subagent_tokens": "1000"},
            }))
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--workspace", td, "--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# main — since mode
# ---------------------------------------------------------------------------


class TestSinceModeMain(unittest.TestCase):
    def test_invalid_since_returns_1(self):
        result = main(["--since", "bad-value!!"])
        self.assertEqual(result, 1)

    def test_no_stages_in_window_returns_0(self):
        with patch("telemetry.otel.cli.workflow_cost.get_work_dir") as mock_wd:
            with tempfile.TemporaryDirectory() as td:
                mock_wd.return_value = Path(td)
                result = main(["--since", "1h"])
        self.assertEqual(result, 0)

    def test_stages_in_window_with_cost_returns_0(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            stages = p / "run-001" / "stages"
            stages.mkdir(parents=True)
            (stages / "s1.json").write_text(json.dumps({
                "stage_name": "build",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"subagent_cost_usd": "0.05", "subagent_tokens": "1000"},
            }))
            with patch("telemetry.otel.cli.workflow_cost.get_work_dir", return_value=p):
                with patch("telemetry.otel.cli.workflow_cost.emit_rows", return_value=0):
                    result = main(["--since", "1h"])
        self.assertEqual(result, 0)

    def test_no_args_causes_error(self):
        with self.assertRaises(SystemExit):
            main([])


if __name__ == "__main__":
    unittest.main()
