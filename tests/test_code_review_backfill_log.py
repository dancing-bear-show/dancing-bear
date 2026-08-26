"""Unit tests for bin/code-review-backfill-log.py.

The parser reads a posted PR comment back into a findings-log record, so the
tests pin the comment format that code-review-swarm.yaml Step 2 emits. If that
format changes, these fail — which is the point: a silently mis-parsed comment
would write corrupt history into the log.

The header/body mismatch case is drawn from a real comment (PR #145), where the
posted comment listed 19 findings but the consolidated set held 18 — a
file-level finding anchored at line 1 appears in the comment but not in the
logged record.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "code-review-backfill-log.py"

_spec = importlib.util.spec_from_file_location("code_review_backfill_log", _SCRIPT)
if _spec is None or _spec.loader is None:  # pragma: no cover - import plumbing
    raise ImportError(f"cannot load {_SCRIPT}")
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


COMMENT = """## Code Review Findings (3 total: 1 critical, 1 major, 1 minor)

Some preamble prose that must not be parsed as a finding.

### Critical

**`src/a.py:85-95`** — `vacuous-test`
A finding sentence.
> evidence line

### Major

**`src/b.py:12`** — `comment-drift`
Another finding.

### Minor

**`tests/c.py:7`** — `hardcoded-magic-constant`
A third finding.
"""


class ParseCommentTests(unittest.TestCase):
    def test_returns_none_for_unrelated_comment(self):
        self.assertIsNone(backfill.parse_comment("LGTM, nice work"))

    def test_returns_none_for_copilot_inline_comment(self):
        # Copilot comments live alongside swarm comments and must not match.
        body = "This function has no assertion on the mock.\n\n```suggestion\nx = 1\n```"
        self.assertIsNone(backfill.parse_comment(body))

    def test_extracts_header_totals(self):
        parsed = backfill.parse_comment(COMMENT)
        self.assertEqual(parsed["total"], 3)
        self.assertEqual(parsed["critical"], 1)
        self.assertEqual(parsed["major"], 1)
        self.assertEqual(parsed["minor"], 1)

    def test_extracts_each_finding_with_file_line_and_concern(self):
        parsed = backfill.parse_comment(COMMENT)
        self.assertEqual(len(parsed["findings"]), 3)
        first = parsed["findings"][0]
        self.assertEqual(first["file"], "src/a.py")
        self.assertEqual(first["concern_id"], "vacuous-test")
        self.assertEqual(first["severity"], "critical")

    def test_line_range_collapses_to_start_line(self):
        # The comment writes "85-95"; the log stores the start line only.
        parsed = backfill.parse_comment(COMMENT)
        self.assertEqual(parsed["findings"][0]["line"], 85)

    def test_single_line_anchor_parses(self):
        parsed = backfill.parse_comment(COMMENT)
        self.assertEqual(parsed["findings"][1]["line"], 12)

    def test_severity_tracks_the_enclosing_heading(self):
        parsed = backfill.parse_comment(COMMENT)
        self.assertEqual(
            [f["severity"] for f in parsed["findings"]],
            ["critical", "major", "minor"],
        )

    def test_prose_is_not_mistaken_for_a_finding(self):
        parsed = backfill.parse_comment(COMMENT)
        files = [f["file"] for f in parsed["findings"]]
        self.assertEqual(files, ["src/a.py", "src/b.py", "tests/c.py"])

    def test_zero_finding_comment_parses_with_empty_list(self):
        body = "## Code Review Findings (0 total: 0 critical, 0 major, 0 minor)\n\nClean."
        parsed = backfill.parse_comment(body)
        self.assertEqual(parsed["total"], 0)
        self.assertEqual(parsed["findings"], [])

    def test_body_may_list_more_findings_than_the_header_total(self):
        # Real case (PR #145): a file-level finding appears in the comment but
        # not in the consolidated set. The header total stays authoritative;
        # the caller reports the difference rather than silently inflating.
        body = COMMENT + "\n**`src/extra.py:1`** — `file-too-large`\nExtra.\n"
        parsed = backfill.parse_comment(body)
        self.assertEqual(parsed["total"], 3)
        self.assertEqual(len(parsed["findings"]), 4)


class BuildRecordTests(unittest.TestCase):
    def test_record_is_marked_backfilled(self):
        parsed = backfill.parse_comment(COMMENT)
        record = backfill.build_record(
            "o/r", 271, {"created_at": "2026-08-20T10:00:00Z"}, parsed
        )
        self.assertTrue(record["backfilled"])

    def test_record_carries_the_consumer_contract_fields(self):
        parsed = backfill.parse_comment(COMMENT)
        record = backfill.build_record(
            "o/r", 271, {"created_at": "2026-08-20T10:00:00Z"}, parsed
        )
        for key in ("ts", "pr_number", "repo", "total", "critical", "major",
                    "minor", "posted", "findings", "worktree"):
            self.assertIn(key, record)
        self.assertEqual(record["pr_number"], 271)
        self.assertEqual(record["repo"], "o/r")
        self.assertEqual(record["ts"], "2026-08-20T10:00:00Z")


class ExistingPrNumbersTests(unittest.TestCase):
    def test_reads_pr_numbers_regardless_of_int_or_str(self):
        # The live log contains both shapes.
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.ndjson"
            log.write_text(
                json.dumps({"pr_number": 93}) + "\n"
                + json.dumps({"pr_number": "121"}) + "\n"
            )
            self.assertEqual(backfill.existing_pr_numbers(log), {"93", "121"})

    def test_missing_log_is_empty_not_an_error(self):
        self.assertEqual(backfill.existing_pr_numbers(Path("/nonexistent/x")), set())

    def test_malformed_line_is_skipped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.ndjson"
            log.write_text('{"pr_number": 1}\nnot json{\n{"pr_number": 2}\n')
            self.assertEqual(backfill.existing_pr_numbers(log), {"1", "2"})


class ScanPrsTests(unittest.TestCase):
    """scan_prs buckets each PR; the network calls are stubbed."""

    def setUp(self):
        self._real_find = backfill.find_summary_comment
        self.addCleanup(setattr, backfill, "find_summary_comment", self._real_find)

    def _stub(self, mapping):
        backfill.find_summary_comment = lambda repo, pr: mapping.get(pr)

    def test_already_logged_pr_is_skipped_without_fetching(self):
        fetched = []

        def _spy(repo, pr):
            fetched.append(pr)
            return None

        backfill.find_summary_comment = _spy
        scan = backfill.scan_prs("o/r", [1, 2], already={"1"})
        self.assertEqual(scan["skipped"], [1])
        self.assertEqual(fetched, [2])

    def test_pr_without_summary_comment_is_bucketed_not_errored(self):
        self._stub({})
        scan = backfill.scan_prs("o/r", [7], already=set())
        self.assertEqual(scan["no_comment"], [7])
        self.assertEqual(scan["records"], [])

    def test_non_swarm_comment_counts_as_no_comment(self):
        self._stub({7: {"body": "LGTM", "created_at": "t"}})
        scan = backfill.scan_prs("o/r", [7], already=set())
        self.assertEqual(scan["no_comment"], [7])

    def test_parsed_pr_produces_a_record(self):
        self._stub({7: {"body": COMMENT, "created_at": "2026-08-20T10:00:00Z"}})
        scan = backfill.scan_prs("o/r", [7], already=set())
        self.assertEqual(len(scan["records"]), 1)
        self.assertEqual(scan["records"][0]["pr_number"], 7)
        self.assertEqual(scan["mismatched"], [])

    def test_count_mismatch_is_flagged_but_record_is_kept(self):
        body = COMMENT + "\n**`src/extra.py:1`** — `file-too-large`\nExtra.\n"
        self._stub({7: {"body": body, "created_at": "t"}})
        scan = backfill.scan_prs("o/r", [7], already=set())
        self.assertEqual(scan["mismatched"], [7])
        self.assertEqual(len(scan["records"]), 1)
        # The header total stays authoritative, not the parsed length.
        self.assertEqual(scan["records"][0]["total"], 3)


class ReportScanTests(unittest.TestCase):
    def _report(self, scan):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            backfill.report_scan(scan, preview_limit=2)
        return buf.getvalue()

    def test_truncates_long_pr_lists_and_says_how_many_were_hidden(self):
        out = self._report(
            {"records": [], "skipped": [], "no_comment": [1, 2, 3, 4], "mismatched": []}
        )
        self.assertIn("#1, #2", out)
        self.assertIn("+2 more", out)

    def test_no_truncation_note_when_list_fits(self):
        out = self._report(
            {"records": [], "skipped": [], "no_comment": [1], "mismatched": []}
        )
        self.assertIn("#1", out)
        self.assertNotIn("more", out)

    def test_quiet_buckets_are_omitted(self):
        out = self._report(
            {"records": [], "skipped": [], "no_comment": [], "mismatched": []}
        )
        self.assertNotIn("no summary comment found", out)
        self.assertNotIn("header/body count differs", out)


if __name__ == "__main__":
    unittest.main()
