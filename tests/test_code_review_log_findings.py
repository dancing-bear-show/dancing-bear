"""Unit tests for bin/code-review-log-findings.py.

This script replaced an inline `python3 -c` heredoc that failed silently for an
unknown period, so the tests here focus on the failure modes that let the
breakage go unnoticed rather than on the happy path alone:

- a missing or malformed input must exit non-zero (the old form printed a
  warning and continued, leaving the stage reporting success)
- a clean review (zero findings) must still write a record — the consuming
  workflow distinguishes "reviewed, found nothing" from "never reviewed"
- post-results.json is optional, because the human-gate-discard path never
  writes one
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "code-review-log-findings.py"

_spec = importlib.util.spec_from_file_location("code_review_log_findings", _SCRIPT)
if _spec is None or _spec.loader is None:  # pragma: no cover - import plumbing
    raise ImportError(f"cannot load {_SCRIPT}")
logmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(logmod)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


class BuildRecordTests(unittest.TestCase):
    """The record shape is a contract with update-review-concerns."""

    def test_record_carries_every_field_the_consumer_reads(self):
        record = logmod.build_record(
            {"number": "271", "owner_repo": "org/repo"},
            {
                "total_findings": 2,
                "by_severity": {"critical": 1, "major": 1, "minor": 0},
                "findings": [
                    {
                        "file": "src/a.py",
                        "concern_id": "silent-failure",
                        "severity": "critical",
                        "line": 42,
                    }
                ],
            },
            {"posted": 1},
        )
        for key in (
            "ts",
            "pr_number",
            "repo",
            "total",
            "critical",
            "major",
            "minor",
            "posted",
            "findings",
            "worktree",
        ):
            self.assertIn(key, record)
        self.assertEqual(record["pr_number"], "271")
        self.assertEqual(record["repo"], "org/repo")
        self.assertEqual(record["total"], 2)
        self.assertEqual(record["critical"], 1)
        self.assertEqual(record["findings"][0]["concern_id"], "silent-failure")

    def test_pr_number_falls_back_to_pr_number_key(self):
        record = logmod.build_record({"pr_number": "9"}, {}, {})
        self.assertEqual(record["pr_number"], "9")

    def test_missing_by_severity_defaults_to_zero_not_crash(self):
        record = logmod.build_record({}, {"total_findings": 0}, {})
        self.assertEqual(record["critical"], 0)
        self.assertEqual(record["major"], 0)
        self.assertEqual(record["minor"], 0)

    def test_null_by_severity_defaults_to_zero(self):
        # consolidated.json has been seen with an explicit null here.
        record = logmod.build_record({}, {"by_severity": None}, {})
        self.assertEqual(record["critical"], 0)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.ws = self.tmp / "ws"
        self.log = self.tmp / "findings.ndjson"
        self.addCleanup(self._tmp.cleanup)

    def _seed(self, *, total=1, findings=None, post=True):
        _write(self.ws / "outputs" / "pr-context.json", {"number": "271", "owner_repo": "o/r"})
        _write(
            self.ws / "outputs" / "consolidated.json",
            {
                "total_findings": total,
                "by_severity": {"critical": 0, "major": total, "minor": 0},
                "findings": findings if findings is not None else [],
            },
        )
        if post:
            _write(self.ws / "outputs" / "post-results.json", {"posted": 1})

    def _run(self):
        return logmod.main(["--workspace", str(self.ws), "--log-path", str(self.log)])

    def test_appends_one_line_per_run(self):
        self._seed()
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._run(), 0)
        lines = [ln for ln in self.log.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        for ln in lines:
            json.loads(ln)  # each line must independently parse

    def test_clean_review_still_writes_a_record(self):
        # A zero-findings review is the case the old workflow skipped entirely.
        self._seed(total=0)
        self.assertEqual(self._run(), 0)
        record = json.loads(self.log.read_text().strip())
        self.assertEqual(record["total"], 0)

    def test_post_results_is_optional(self):
        # The human-gate-discard path never writes post-results.json.
        self._seed(post=False)
        self.assertEqual(self._run(), 0)
        self.assertEqual(json.loads(self.log.read_text().strip())["posted"], 0)

    def test_creates_parent_directory(self):
        self._seed()
        self.log = self.tmp / "nested" / "deeper" / "findings.ndjson"
        self.assertEqual(self._run(), 0)
        self.assertTrue(self.log.exists())

    def test_missing_input_exits_nonzero(self):
        # The whole point of the rewrite: this must NOT pass silently.
        with self.assertRaises(SystemExit) as ctx:
            self._run()
        self.assertNotEqual(ctx.exception.code, 0)

    def test_malformed_json_exits_nonzero_and_names_the_file(self):
        self._seed()
        (self.ws / "outputs" / "consolidated.json").write_text("not json{")
        with self.assertRaises(SystemExit) as ctx:
            self._run()
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("consolidated.json", str(ctx.exception))

    def test_failed_run_writes_no_partial_line(self):
        self._seed()
        (self.ws / "outputs" / "consolidated.json").write_text("{oops")
        with self.assertRaises(SystemExit):
            self._run()
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
