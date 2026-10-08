"""Tests for workflow count-blocking: derive blocking count from sweep-findings.json."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.cli import main
from workflow.count_blocking import CountBlockingError, cmd_count_blocking, count_blocking


def _write(tmp: Path, doc: object, name: str = "findings.json") -> str:
    path = str(tmp / name)
    Path(path).write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run(path: str) -> tuple[int, str, str]:
    """Run cmd_count_blocking, return (exit_code, stdout, stderr)."""
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_count_blocking(path, stderr=err)
    return rc, buf.getvalue(), err.getvalue()


class TestCountBlocking(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    # ------------------------------------------------------------------
    # count_blocking() — pure logic, happy paths
    # ------------------------------------------------------------------

    def test_counts_critical_and_major(self) -> None:
        path = _write(self.tmp, {
            "blocking": 2,
            "findings": [
                {"severity": "critical"},
                {"severity": "major"},
                {"severity": "minor"},
                {"severity": "info"},
            ],
        })
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 2)
        self.assertEqual(reported, 2)

    def test_unknown_severity_counts_as_blocking_fail_closed(self) -> None:
        """An unknown severity string (not minor/info) is counted as blocking."""
        path = _write(self.tmp, {
            "blocking": 1,
            "findings": [{"severity": "unknown-future-level"}],
        })
        derived, _ = count_blocking(path)
        self.assertEqual(derived, 1)

    def test_mismatch_returns_both_values(self) -> None:
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

    # ------------------------------------------------------------------
    # count_blocking() — malformed inputs that must raise CountBlockingError
    # ------------------------------------------------------------------

    def test_missing_findings_key_raises(self) -> None:
        """A file with no 'findings' key (e.g. fix-results.json) must exit 2."""
        path = _write(self.tmp, {"blocking": 0, "results": []})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("findings", str(cm.exception))

    def test_findings_not_a_list_raises(self) -> None:
        path = _write(self.tmp, {"findings": {"bad": "value"}})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_findings_not_a_list_integer_raises(self) -> None:
        path = _write(self.tmp, {"findings": 99})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_finding_not_an_object_raises(self) -> None:
        """Any finding that is not a dict is malformed."""
        path = _write(self.tmp, {"findings": [{"severity": "critical"}, "bad"]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("findings[1]", str(cm.exception))

    def test_finding_null_raises(self) -> None:
        path = _write(self.tmp, {"findings": [None]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("findings[0]", str(cm.exception))

    def test_finding_missing_severity_raises(self) -> None:
        path = _write(self.tmp, {"findings": [{"concern_id": "foo"}]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("severity", str(cm.exception))

    def test_finding_non_string_severity_raises(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": 42}]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("severity", str(cm.exception))

    def test_finding_empty_severity_raises(self) -> None:
        """Empty string severity is malformed — not a valid level."""
        path = _write(self.tmp, {"findings": [{"severity": ""}]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("severity", str(cm.exception))

    def test_finding_whitespace_severity_raises(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": "   "}]})
        with self.assertRaises(CountBlockingError) as cm:
            count_blocking(path)
        self.assertIn("severity", str(cm.exception))

    # blocking field: absent is allowed; present-but-invalid exits 2
    def test_blocking_not_an_int_raises(self) -> None:
        path = _write(self.tmp, {"blocking": "oops", "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_null_raises(self) -> None:
        """JSON null for blocking is invalid — absent is the allowed form."""
        path = _write(self.tmp, {"blocking": None, "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_bool_true_raises(self) -> None:
        """JSON true is a bool which subclasses int; must be rejected."""
        path = _write(self.tmp, {"blocking": True, "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_bool_false_raises(self) -> None:
        path = _write(self.tmp, {"blocking": False, "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_float_raises(self) -> None:
        path = _write(self.tmp, {"blocking": 2.0, "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_negative_raises(self) -> None:
        path = _write(self.tmp, {"blocking": -1, "findings": []})
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_blocking_absent_is_allowed(self) -> None:
        """Missing 'blocking' key is allowed; reported is None."""
        path = _write(self.tmp, {"findings": [{"severity": "critical"}]})
        derived, reported = count_blocking(path)
        self.assertEqual(derived, 1)
        self.assertIsNone(reported)

    def test_not_valid_json_raises(self) -> None:
        path = str(self.tmp / "bad.json")
        Path(path).write_text("not json", encoding="utf-8")
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_top_level_not_an_object_raises(self) -> None:
        path = _write(self.tmp, [{"severity": "critical"}])
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(CountBlockingError):
            count_blocking(str(self.tmp / "nonexistent.json"))

    # ------------------------------------------------------------------
    # cmd_count_blocking() — exit 2 cases: stdout must NOT be a number
    # ------------------------------------------------------------------

    def _assert_exit2_no_number(self, path: str) -> None:
        rc, out, err = _run(path)
        self.assertEqual(rc, 2, f"expected exit 2; stderr={err!r}")
        self.assertIn("count-blocking:", err)
        # stdout must not contain a number — a caller that captured stdout
        # and treated it as the count would get an empty or error string.
        self.assertFalse(out.strip().isdigit(),
                         f"stdout must not be a number on exit 2, got {out!r}")

    def test_exit2_missing_findings_key(self) -> None:
        path = _write(self.tmp, {"blocking": 0, "results": []}, "no_findings.json")
        self._assert_exit2_no_number(path)

    def test_exit2_findings_not_a_list(self) -> None:
        path = _write(self.tmp, {"findings": "bad"}, "bad_list.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_not_an_object(self) -> None:
        path = _write(self.tmp, {"findings": ["bad"]}, "bad_item.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_null(self) -> None:
        path = _write(self.tmp, {"findings": [None]}, "null_item.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_missing_severity(self) -> None:
        path = _write(self.tmp, {"findings": [{"concern_id": "x"}]}, "no_sev.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_non_string_severity(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": 99}]}, "bad_sev.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_empty_severity(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": ""}]}, "empty_sev.json")
        self._assert_exit2_no_number(path)

    def test_exit2_finding_whitespace_severity(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": "  "}]}, "ws_sev.json")
        self._assert_exit2_no_number(path)

    def test_exit2_blocking_not_an_int(self) -> None:
        path = _write(self.tmp, {"blocking": "oops", "findings": []}, "bad_blocking.json")
        self._assert_exit2_no_number(path)

    def test_exit2_blocking_null(self) -> None:
        path = _write(self.tmp, {"blocking": None, "findings": []}, "null_blocking.json")
        self._assert_exit2_no_number(path)

    def test_exit2_blocking_bool_true(self) -> None:
        path = _write(self.tmp, {"blocking": True, "findings": []}, "bool_blocking.json")
        self._assert_exit2_no_number(path)

    def test_exit2_blocking_float(self) -> None:
        path = _write(self.tmp, {"blocking": 1.0, "findings": []}, "float_blocking.json")
        self._assert_exit2_no_number(path)

    def test_exit2_blocking_negative(self) -> None:
        path = _write(self.tmp, {"blocking": -1, "findings": []}, "neg_blocking.json")
        self._assert_exit2_no_number(path)

    def test_exit2_missing_file(self) -> None:
        rc, stdout, _ = _run(str(self.tmp / "missing.json"))
        self.assertEqual(rc, 2)
        self.assertFalse(stdout.strip().isdigit())

    def test_exit2_not_valid_json(self) -> None:
        path = str(self.tmp / "notjson.json")
        Path(path).write_text("!!!not json", encoding="utf-8")
        self._assert_exit2_no_number(path)

    def test_exit2_top_level_list(self) -> None:
        path = _write(self.tmp, [{"severity": "critical"}], "list.json")
        self._assert_exit2_no_number(path)

    # ------------------------------------------------------------------
    # cmd_count_blocking() — happy path stdout / stderr
    # ------------------------------------------------------------------

    def test_cmd_prints_derived_count_to_stdout(self) -> None:
        path = _write(self.tmp, {"blocking": 2, "findings": [
            {"severity": "critical"}, {"severity": "major"}, {"severity": "minor"},
        ]})
        rc, out, err = _run(path)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "2")
        self.assertEqual(err, "")

    def test_cmd_writes_mismatch_to_stderr(self) -> None:
        path = _write(self.tmp, {"blocking": 5, "findings": [{"severity": "critical"}]})
        rc, _, err = _run(path)
        self.assertEqual(rc, 0)
        self.assertIn("summary_mismatch", err)
        self.assertIn("reported=5", err)
        self.assertIn("derived=1", err)

    def test_cmd_no_mismatch_on_correct_blocking(self) -> None:
        path = _write(self.tmp, {"blocking": 1, "findings": [{"severity": "major"}]})
        rc, _, err = _run(path)
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_cmd_absent_blocking_no_mismatch(self) -> None:
        """Missing 'blocking' → no mismatch diagnostic."""
        path = _write(self.tmp, {"findings": [{"severity": "critical"}]})
        rc, out, err = _run(path)
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertEqual(out.strip(), "1")

    # ------------------------------------------------------------------
    # CLI integration — ./bin/workflow count-blocking via main()
    # ------------------------------------------------------------------

    def test_cli_exits_0_on_well_formed(self) -> None:
        path = _write(self.tmp, {"blocking": 1, "findings": [{"severity": "critical"}]})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 0)

    def test_cli_exits_2_on_missing_findings_key(self) -> None:
        path = _write(self.tmp, {"results": []})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 2)

    def test_cli_exits_2_on_malformed_findings(self) -> None:
        path = _write(self.tmp, {"findings": 99})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 2)

    def test_cli_exits_2_on_non_object_finding(self) -> None:
        path = _write(self.tmp, {"findings": ["not-an-object"]})
        rc = main(["count-blocking", path])
        self.assertEqual(rc, 2)

    def test_cli_exits_2_on_missing_file(self) -> None:
        rc = main(["count-blocking", str(self.tmp / "no.json")])
        self.assertEqual(rc, 2)

    # ------------------------------------------------------------------
    # info / minor severity — non-blocking
    # ------------------------------------------------------------------

    def test_info_severity_is_not_blocking(self) -> None:
        """An info-level finding must not count as blocking."""
        path = _write(self.tmp, {"findings": [{"severity": "info"}]}, "info.json")
        derived, _ = count_blocking(path)
        self.assertEqual(derived, 0)

    def test_minor_severity_is_not_blocking(self) -> None:
        path = _write(self.tmp, {"findings": [{"severity": "minor"}]}, "minor.json")
        derived, _ = count_blocking(path)
        self.assertEqual(derived, 0)

    def test_cmd_info_severity_prints_zero(self) -> None:
        """count-blocking on a file with only info findings must print 0."""
        path = _write(self.tmp, {
            "blocking": 0,
            "findings": [{"severity": "info"}, {"severity": "minor"}],
        }, "info_cmd.json")
        rc, out, _ = _run(path)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    # ------------------------------------------------------------------
    # UnicodeDecodeError — non-UTF-8 files exit 2
    # ------------------------------------------------------------------

    def test_non_utf8_file_raises(self) -> None:
        """A file with non-UTF-8 bytes must raise CountBlockingError, not crash."""
        path = str(self.tmp / "latin1.json")
        Path(path).write_bytes(b'{"findings": [{"severity": "\xff\xfe"}]}')
        with self.assertRaises(CountBlockingError):
            count_blocking(path)

    def test_exit2_non_utf8_file(self) -> None:
        """cmd_count_blocking on a non-UTF-8 file must exit 2."""
        path = str(self.tmp / "latin1_cmd.json")
        Path(path).write_bytes(b'{"findings": [{"severity": "\xff\xfe"}]}')
        self._assert_exit2_no_number(path)


if __name__ == "__main__":
    unittest.main()
