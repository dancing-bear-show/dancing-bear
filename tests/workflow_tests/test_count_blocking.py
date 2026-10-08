"""Tests for workflow count-blocking: derive blocking count from sweep-findings.json."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.cli import main
from workflow.count_blocking import CountBlockingError, cmd_count_blocking, count_blocking


def _write(tmp: Path, doc: object) -> str:
    path = str(tmp / "findings.json")
    Path(path).write_text(json.dumps(doc), encoding="utf-8")
    return path


class TestCountBlocking(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    # ------------------------------------------------------------------
    # count_blocking() — pure logic
    # ------------------------------------------------------------------

    def test_match_counts_critical_and_major(self) -> None:
        path = _write(self.tmp, {
            "blocking": 2,
            "findings": [
                {"severity": "critical"},
                {"severity": "major"},
                {"severity": "minor"},
            ],
        })
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 2)
        self.assertEqual(reported, 2)

    def test_mismatch_returns_both_values(self) -> None:
        """Reported != derived: both values returned, caller writes the diagnostic."""
        path = _write(self.tmp, {
            "blocking": 5,
            "findings": [{"severity": "critical"}, {"severity": "major"}],
        })
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 2)
        self.assertEqual(reported, 5)

    def test_empty_findings_returns_zero(self) -> None:
        path = _write(self.tmp, {"blocking": 0, "findings": []})
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 0)
        self.assertEqual(reported, 0)

    def test_absent_blocking_returns_none(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": "critical"}]})
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 1)
        self.assertIsNone(reported)

    def test_absent_findings_defaults_to_zero(self) -> None:
        path = _write(self.tmp, {"blocking": 0})
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 0)
        self.assertEqual(reported, 0)

    def test_non_dict_findings_items_are_skipped(self) -> None:
        """Non-dict entries in findings must not crash the count."""
        path = _write(self.tmp, {
            "blocking": 1,
            "findings": [None, "string", {"severity": "critical"}, 42],
        })
        derived, _ = count_blocking(path)
        self.assertEqual(derived, 1)

    def test_malformed_findings_not_a_list(self) -> None:
        path = _write(self.tmp, {"findings": {"bad": "value"}})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_malformed_blocking_not_an_int(self) -> None:
        path = _write(self.tmp, {"blocking": "oops", "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_not_valid_json(self) -> None:
        path = str(self.tmp / "bad.json")
        Path(path).write_text("not json", encoding="utf-8")
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_top_level_not_an_object(self) -> None:
        path = _write(self.tmp, [{"severity": "critical"}])
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_missing_file(self) -> None:
        with self.assertRaises(CountBlockingError):
            count_blocking(str(self.tmp / "nonexistent.json"))

    # ------------------------------------------------------------------
    # cmd_count_blocking() — exit codes and stderr
    # ------------------------------------------------------------------

    def test_cmd_exits_0_on_match(self) -> None:
        path = _write(self.tmp, {"blocking": 2, "findings": [
            {"severity": "critical"}, {"severity": "major"},
        ]})
        err = io.StringIO()
        rc = cmd_count_blocking(path, stderr=err)
        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "")

    def test_cmd_prints_derived_count(self) -> None:
        path = _write(self.tmp, {"blocking": 3, "findings": [
            {"severity": "critical"}, {"severity": "major"}, {"severity": "minor"},
        ]})
        import contextlib
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_count_blocking(path, stderr=err)
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "2")

    def test_cmd_writes_mismatch_to_stderr(self) -> None:
        path = _write(self.tmp, {"blocking": 5, "findings": [{"severity": "critical"}]})
        err = io.StringIO()
        rc = cmd_count_blocking(path, stderr=err)
        self.assertEqual(rc, 0)
        self.assertIn("summary_mismatch", err.getvalue())
        self.assertIn("reported=5", err.getvalue())
        self.assertIn("derived=1", err.getvalue())

    def test_cmd_no_mismatch_on_correct_blocking(self) -> None:
        path = _write(self.tmp, {"blocking": 1, "findings": [{"severity": "major"}]})
        err = io.StringIO()
        cmd_count_blocking(path, stderr=err)
        self.assertEqual(err.getvalue(), "")

    def test_cmd_exits_2_on_malformed_input(self) -> None:
        path = _write(self.tmp, {"findings": "not-a-list"})
        err = io.StringIO()
        rc = cmd_count_blocking(path, stderr=err)
        self.assertEqual(rc, 2)
        self.assertIn("count-blocking:", err.getvalue())

    def test_cmd_exits_2_on_missing_file(self) -> None:
        err = io.StringIO()
        rc = cmd_count_blocking(str(self.tmp / "missing.json"), stderr=err)
        self.assertEqual(rc, 2)

    # ------------------------------------------------------------------
    # CLI integration — ./bin/workflow count-blocking via main()
    # ------------------------------------------------------------------

    def test_cli_exits_0_on_well_formed(self) -> None:
        path = _write(self.tmp, {"blocking": 1, "findings": [{"severity": "critical"}]})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 0)

    def test_cli_exits_2_on_malformed(self) -> None:
        path = _write(self.tmp, {"findings": 99})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 2)

    def test_cli_exits_2_on_missing_file(self) -> None:
        rc = main(["count-blocking", str(self.tmp / "no.json")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
