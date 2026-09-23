"""Tests for workflow.review_ids and its three ``./bin/workflow`` subcommands.

These checks were Python snippets embedded in review-fix-threads.yaml that no
test ever ran. Every rule here records a real failure on PR #391: shifted and
fabricated thread ids, swapped ids on a shared (path, line), and result keys
that collide or are unsafe as filenames. The fix-index and aggregate checks key
on PR #400's ``id`` / ``file_id`` scheme (core.copilot_overview).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from core.copilot_overview import _file_id
from tests.fixtures import TempDirMixin, bin_path, repo_root
from workflow.cli_dispatch_review import (
    _cmd_aggregate_fix_results,
    _cmd_check_fix_index,
    _cmd_check_thread_ids,
    _cmd_thread_fingerprints,
)
from workflow.review_ids import (
    ISSUE_ABSENT,
    ISSUE_BAD_DISCRIMINATOR,
    ISSUE_FETCH_HAS_NO_VALUE,
    ISSUE_MISMATCH,
    ISSUE_NO_RECORDED_VALUE,
    FixIndexResult,
    aggregate_fix_results,
    body_fingerprint,
    check_fix_index,
    check_thread_ids,
    thread_fingerprints,
)

#: Cap on the wrapper subprocess: a hung wrapper must not hang the suite.
_WRAPPER_TIMEOUT_S = 60

#: A fixed body exercising every normalisation step: CRLF, tabs, runs of
#: spaces, a blank line, leading/trailing whitespace on lines and on the whole.
KNOWN_BODY = "First   line\twith  tabs  \r\n\r\n   indented   second line\r\nthird line   \n\n"

#: Computed ONCE with the exact expression the workflow specified:
#:   sha256("\n".join(" ".join(line.split()) for line in
#:          body.replace("\r\n", "\n").split("\n")).strip().encode("utf-8")).hexdigest()
#: Values recorded by earlier runs are compared against this algorithm, so
#: this pin is what stops a "cleanup" from silently changing it.
KNOWN_FINGERPRINT = "4e0f866081ac2e316851cb8aed1ccadedf2a8bd3dea4c4df2bf74be8ecd86005"

#: Real thread ids from PR #391. Note the trailing dash on the first.
REAL_ID_TRAILING_DASH = "PRRT_kwDOQr1kjM6k7gn-"
REAL_ID_A = "PRRT_kwDOQr1kjM6k6s65"
REAL_ID_B = "PRRT_kwDOQr1kjM6k67nb"

#: Unlinked overview ids that sanitise to the same characters; only
#: _file_id's hash suffix keeps their result files apart.
UNLINKED_A = "unlinked:src/a/b.py:10"
UNLINKED_B = "unlinked:src/a-b.py:10"

UNSAFE_FILE_IDS = ("../x", "a/b", ".hidden", "..", "a$(id)b", "body 0", "a;rm", "a'b", "-x", "a:b")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _fetched(thread_id: str | None, path: str | None, line: int | None,
             *, db_id: int | None, body: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id, "path": path, "line": line,
        "comments": [{"author": "bot", "body": body, "database_id": db_id}],
    }


def _triage(thread_id: str | None, path: str | None, line: int | None, *,
            db_id: int | str | None = None,
            discriminator: str | None = "database_id") -> dict[str, Any]:
    return {
        "thread_id": thread_id, "path": path, "line": line,
        "discriminator": discriminator,
        "comment_database_id": db_id, "body_fingerprint": None,
        "id": thread_id or f"comment:{db_id}",
    }


def _triage_fp(thread_id: str, path: str, line: int, fingerprint: str | None) -> dict[str, Any]:
    """A triage entry that names the fingerprint as its discriminator."""
    entry = _triage(thread_id, path, line, discriminator="fingerprint")
    entry["body_fingerprint"] = fingerprint
    return entry


_ABSENT = object()


def _entry(finding_id: object, file_id: object = _ABSENT, thread_id: str | None = None) -> dict[str, Any]:
    """A fix-index entry. file_id defaults to the parser's real _file_id(id).
    Pass _ABSENT as finding_id to leave ``id`` out; any explicit file_id,
    None included, is written as given."""
    entry: dict[str, Any] = {"thread_id": thread_id}
    if finding_id is not _ABSENT:
        entry["id"] = finding_id
    if file_id is _ABSENT and isinstance(finding_id, str):
        entry["file_id"] = _file_id(finding_id)
    elif file_id is not _ABSENT:
        entry["file_id"] = file_id
    return entry


def _index(*groups: Sequence[dict[str, Any]], paths: Sequence[str] = ()) -> dict[str, Any]:
    """Build a fix-index.json with one item per group of entries. Group i's
    file is paths[i], or f{i}.py when no paths are given."""
    return {
        "total": len(groups),
        "items": [
            {"index": str(i), "data": {"path": paths[i] if paths else f"f{i}.py", "threads": list(entries)}}
            for i, entries in enumerate(groups)
        ],
    }


def _ids(*ids: str) -> list[dict[str, Any]]:
    return [_entry(i) for i in ids]


class _JsonFiles(TempDirMixin, unittest.TestCase):
    """Temp dir plus a JSON writer. The dir name carries a space, like
    ``Application Support``, so path handling is exercised too."""

    def setUp(self) -> None:
        super().setUp()
        self.root = Path(self.tmpdir) / "Application Support"
        self.root.mkdir()

    def write(self, name: str, doc: object) -> str:
        path = self.root / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def read(self, name: str) -> Any:
        return json.loads((self.root / name).read_text(encoding="utf-8"))


def _call(handler: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> tuple[int, str, str]:
    """Run a handler, returning (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = handler(args)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestBodyFingerprint(unittest.TestCase):

    def test_known_answer(self) -> None:
        """Pinned value: any change to the algorithm fails here first."""
        self.assertEqual(body_fingerprint(KNOWN_BODY), KNOWN_FINGERPRINT)

    def test_keeps_line_structure(self) -> None:
        """Newlines are NOT collapsed -- the paraphrase that did so was wrong."""
        self.assertNotEqual(body_fingerprint("a\nb"), body_fingerprint("a b"))

    def test_crlf_equals_lf(self) -> None:
        self.assertEqual(body_fingerprint("a\r\nb"), body_fingerprint("a\nb"))

    def test_intra_line_whitespace_collapses(self) -> None:
        self.assertEqual(body_fingerprint("  a \t  b  "), body_fingerprint("a b"))

    def test_is_lowercase_sha256_hex(self) -> None:
        self.assertRegex(body_fingerprint("x"), r"\A[0-9a-f]{64}\Z")


class TestThreadFingerprints(_JsonFiles):

    def test_rows_by_position(self) -> None:
        path = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "a.py", 1, db_id=11, body=KNOWN_BODY),
            {"thread_id": None, "path": None, "line": None, "comments": []},
        ]})
        rows = thread_fingerprints(path)
        self.assertEqual([r.index for r in rows], [0, 1])
        self.assertEqual(rows[0].thread_id, REAL_ID_A)
        self.assertEqual(rows[0].database_id, 11)
        self.assertEqual(rows[0].body_fingerprint, KNOWN_FINGERPRINT)
        self.assertIsNone(rows[1].body_fingerprint)
        self.assertIsNone(rows[1].database_id)

    def test_missing_threads_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            thread_fingerprints(self.write("threads.json", {"threads": {}}))

    def test_non_object_entry_raises(self) -> None:
        with self.assertRaises(ValueError):
            thread_fingerprints(self.write("threads.json", {"threads": ["x"]}))

    def test_handler_emits_json(self) -> None:
        path = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "a.py", 1, db_id=11, body=KNOWN_BODY),
        ]})
        code, out, _ = _call(_cmd_thread_fingerprints, argparse.Namespace(file=path))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["body_fingerprint"], KNOWN_FINGERPRINT)

    def test_handler_unreadable_file_exits_one(self) -> None:
        missing = str(self.root / "absent.json")
        code, out, _ = _call(_cmd_thread_fingerprints, argparse.Namespace(file=missing))
        self.assertEqual((code, out), (1, ""))


# ---------------------------------------------------------------------------
# fix-index gate: id and file_id
# ---------------------------------------------------------------------------


class TestCheckFixIndex(_JsonFiles):

    def check(self, *groups: Sequence[dict[str, Any]]) -> FixIndexResult:
        return check_fix_index(self.write("fix-index.json", _index(*groups)))

    def test_real_ids_and_their_file_ids_pass(self) -> None:
        result = self.check(_ids(REAL_ID_TRAILING_DASH, UNLINKED_A),
                            _ids("comment:123456789", REAL_ID_A, UNLINKED_B))
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.checked, 5)

    def test_parser_file_id_with_dot_passes(self) -> None:
        """PR #400's file_ids keep '.', e.g. unlinked-src-a-b.py-10-<hash>."""
        self.assertIn(".", _file_id(UNLINKED_A))
        self.assertTrue(self.check(_ids(UNLINKED_A)).ok)

    def test_id_is_not_pattern_checked(self) -> None:
        """An id is identity, not a filename: ':' and '/' are legitimate."""
        self.assertTrue(self.check([_entry("unlinked:a/b.py:1", "safe-name")]).ok)

    def test_empty_index_passes(self) -> None:
        self.assertTrue(check_fix_index(self.write("fix-index.json", {"total": 0, "items": []})).ok)

    def test_duplicate_id_across_items_fails(self) -> None:
        result = self.check([_entry(REAL_ID_A, "f-one")], [_entry(REAL_ID_A, "f-two")])
        self.assertEqual(
            result.failures, ("items[1].data.threads[0]: id duplicates items[0].data.threads[0]",),
        )

    def test_duplicate_file_id_fails(self) -> None:
        """Two findings writing one result file: the second overwrites the first."""
        result = self.check([_entry(UNLINKED_A, "same"), _entry(UNLINKED_B, "same")])
        self.assertEqual(
            result.failures,
            ("items[0].data.threads[1]: file_id duplicates items[0].data.threads[0]",),
        )

    def test_several_missing_report_as_missing_not_duplicate(self) -> None:
        result = self.check([_entry(_ABSENT, "f1"), _entry(None, "f2"), _entry("", "f3"),
                             _entry("x1", None), _entry("x2", "")])
        self.assertEqual(len(result.failures), 5)
        for failure in result.failures:
            with self.subTest(failure=failure):
                self.assertIn("is missing", failure)
                self.assertNotIn("duplicate", failure)

    def test_each_unsafe_file_id_fails(self) -> None:
        for file_id in UNSAFE_FILE_IDS:
            with self.subTest(file_id=file_id):
                result = self.check([_entry("x", file_id)])
                self.assertFalse(result.ok)
                self.assertIn("file_id is not [A-Za-z0-9]", result.failures[0])

    def test_leading_dash_or_dot_is_rejected(self) -> None:
        """A leading '-' reads as an option and a leading '.' as hidden or
        '..'; the verdict, not just the message, must reject both."""
        for file_id in ("-x", "-", ".x", ".", "..", "--help"):
            with self.subTest(file_id=file_id):
                self.assertFalse(self.check([_entry("x", file_id)]).ok)

    def test_non_string_values_fail(self) -> None:
        self.assertIn("id is not a string", self.check([_entry(123, "f")]).failures[0])
        self.assertIn("file_id is not a string", self.check([_entry("x", 123)]).failures[0])

    def test_length_boundary(self) -> None:
        self.assertTrue(self.check([_entry("x", "a" * 200)]).ok)
        self.assertFalse(self.check([_entry("x", "a" * 201)]).ok)

    def test_trailing_newline_is_rejected(self) -> None:
        """fullmatch, not match-with-$: '$' would accept a trailing newline."""
        self.assertFalse(self.check([_entry("x", "abc\n")]).ok)

    def test_rejected_values_never_echoed(self) -> None:
        entries = [_entry(f"id-{n}", f) for n, f in enumerate(UNSAFE_FILE_IDS)]
        entries += [_entry("dup-id", "f-a"), _entry("dup-id", "f-b"),
                    _entry("i-a", "dup-file"), _entry("i-b", "dup-file")]
        text = "\n".join(self.check(entries).failures)
        for value in (*UNSAFE_FILE_IDS, "dup-id", "dup-file"):
            with self.subTest(value=value):
                self.assertNotIn(value, text)

    def test_malformed_index_raises(self) -> None:
        malformed: tuple[dict[str, object], ...] = (
            {"items": {}}, {"items": [{"data": {}}]}, {"items": ["x"]},
        )
        for doc in malformed:
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                check_fix_index(self.write("fix-index.json", doc))


class TestCheckFixIndexHandler(_JsonFiles):

    def run_handler(self, doc: object) -> tuple[int, str, str]:
        path = self.write("fix-index.json", doc)
        return _call(_cmd_check_fix_index, argparse.Namespace(file=path))

    def test_pass_exits_zero(self) -> None:
        code, out, err = self.run_handler(_index(_ids(UNLINKED_A, REAL_ID_A)))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ok checked=2 failed=0", out)

    def test_fail_exits_one_without_echo(self) -> None:
        entries = [_entry(f"id-{n}", f) for n, f in enumerate(UNSAFE_FILE_IDS)]
        code, out, err = self.run_handler(_index(entries))
        self.assertEqual(code, 1)
        self.assertIn(f"failed={len(UNSAFE_FILE_IDS)}", out)
        for value in UNSAFE_FILE_IDS:
            with self.subTest(value=value):
                self.assertNotIn(value, out + err)

    def test_malformed_file_exits_one(self) -> None:
        path = self.write("fix-index.json", {"items": 3})
        code, _, err = _call(_cmd_check_fix_index, argparse.Namespace(file=path))
        self.assertEqual(code, 1)
        self.assertIn("check-fix-index:", err)


# ---------------------------------------------------------------------------
# Thread-id coherence gate
# ---------------------------------------------------------------------------


def _coherent_triage() -> list[dict[str, Any]]:
    """Triage entries that agree with ``_Coherence``'s threads.json."""
    return [
        _triage(REAL_ID_A, "wf.yaml", 7, db_id=101),
        _triage(REAL_ID_B, "wf.yaml", 7, db_id=102),
        _triage_fp(REAL_ID_TRAILING_DASH, "src/x.py", 40, body_fingerprint("x")),
        _triage(None, "wf.yaml", 289, db_id=900),
    ]


class _Coherence(_JsonFiles):
    """Two live threads anchored to ONE (path, line) -- the shape observed on
    PR #391 -- plus an unrelated one and a review-body finding."""

    BODY_A = "Handle the None case.\r\n\r\nSee   line 12."
    BODY_B = "Handle the None case.\n\nAlso line 12."

    def setUp(self) -> None:
        super().setUp()
        self.threads = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "wf.yaml", 7, db_id=101, body=self.BODY_A),
            _fetched(REAL_ID_B, "wf.yaml", 7, db_id=102, body=self.BODY_B),
            _fetched(REAL_ID_TRAILING_DASH, "src/x.py", 40, db_id=103, body="x"),
            _fetched(None, None, None, db_id=900, body="review body"),
        ]})

    def triage(self, *entries: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
        return self.write("triage.json", {"threads": list(entries), **(extra or {})})


class TestCheckThreadIds(_Coherence):

    def test_coherent_triage_passes(self) -> None:
        result = check_thread_ids(self.threads, self.triage(*_coherent_triage()))
        self.assertEqual(result.halts(repair=False), ())
        self.assertEqual((result.checked, result.skipped_null), (3, 1))

    def test_null_ids_skipped_even_with_coordinates(self) -> None:
        """A review-body finding quoting a path:line must not halt the run."""
        path = self.triage(_triage(None, "wf.yaml", 289, db_id=900),
                           _triage(None, "other.py", 3, db_id=None, discriminator=None))
        result = check_thread_ids(self.threads, path)
        self.assertEqual((result.checked, result.skipped_null, result.halts(repair=False)), (0, 2, ()))

    def test_fabricated_id_halts(self) -> None:
        entry = _triage(REAL_ID_A + "_missing_defer_case", "wf.yaml", 7, db_id=101)
        result = check_thread_ids(self.threads, self.triage(entry))
        self.assertEqual(result.issues, (f"triage threads[0]: {ISSUE_ABSENT}",))

    def test_swapped_ids_on_shared_coordinates_halt(self) -> None:
        """Coordinates match both ways round; only the discriminator sees it."""
        path = self.triage(
            _triage(REAL_ID_A, "wf.yaml", 7, db_id=102),
            _triage(REAL_ID_B, "wf.yaml", 7, db_id=101),
        )
        result = check_thread_ids(self.threads, path)
        self.assertEqual(result.issues, (
            f"triage threads[0]: {ISSUE_MISMATCH}",
            f"triage threads[1]: {ISSUE_MISMATCH}",
        ))
        self.assertEqual(result.relabels, ())
        self.assertEqual(result.halts(repair=True), result.issues)

    def test_swapped_fingerprints_halt(self) -> None:
        path = self.triage(
            _triage_fp(REAL_ID_A, "wf.yaml", 7, body_fingerprint(self.BODY_B)),
            _triage_fp(REAL_ID_B, "wf.yaml", 7, body_fingerprint(self.BODY_A)),
        )
        self.assertEqual(len(check_thread_ids(self.threads, path).issues), 2)

    def test_fingerprint_with_newlines_collapsed_halts(self) -> None:
        """The paraphrased algorithm must not pass the gate."""
        wrong = body_fingerprint(" ".join(self.BODY_A.split()))
        path = self.triage(_triage_fp(REAL_ID_A, "wf.yaml", 7, wrong))
        self.assertEqual(len(check_thread_ids(self.threads, path).issues), 1)

    def test_shifted_id_with_other_coordinates_halts_not_relabels(self) -> None:
        """A real id belonging to another thread: discriminator catches it
        before the coordinate difference could be 'repaired'."""
        path = self.triage(_triage(REAL_ID_TRAILING_DASH, "wf.yaml", 7, db_id=101))
        result = check_thread_ids(self.threads, path)
        self.assertEqual(result.issues, (f"triage threads[0]: {ISSUE_MISMATCH}",))
        self.assertEqual(result.relabels, ())

    def test_discriminator_missing_or_unknown_halts(self) -> None:
        for disc in (None, "coordinates", ""):
            with self.subTest(discriminator=disc):
                path = self.triage(_triage(REAL_ID_A, "wf.yaml", 7, db_id=101, discriminator=disc))
                self.assertEqual(check_thread_ids(self.threads, path).issues,
                                 (f"triage threads[0]: {ISSUE_BAD_DISCRIMINATOR}",))

    def test_named_discriminator_without_value_halts(self) -> None:
        path = self.triage(
            _triage(REAL_ID_A, "wf.yaml", 7, db_id=None),
            _triage_fp(REAL_ID_B, "wf.yaml", 7, None),
        )
        self.assertEqual(check_thread_ids(self.threads, path).issues, (
            f"triage threads[0]: {ISSUE_NO_RECORDED_VALUE}",
            f"triage threads[1]: {ISSUE_NO_RECORDED_VALUE}",
        ))

    def test_fetch_without_database_id_halts(self) -> None:
        threads = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "wf.yaml", 7, db_id=None, body=self.BODY_A),
        ]})
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 7, db_id=101))
        self.assertEqual(check_thread_ids(threads, path).issues,
                         (f"triage threads[0]: {ISSUE_FETCH_HAS_NO_VALUE}",))

    def test_database_id_as_digit_string_matches(self) -> None:
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 7, db_id="101"))
        self.assertEqual(check_thread_ids(self.threads, path).halts(repair=False), ())

    def test_bool_database_id_is_not_a_value(self) -> None:
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 7, db_id=True))
        self.assertEqual(len(check_thread_ids(self.threads, path).issues), 1)

    def test_coordinate_only_difference_is_a_relabel(self) -> None:
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 9, db_id=101))
        result = check_thread_ids(self.threads, path)
        self.assertEqual(result.issues, ())
        self.assertEqual(len(result.relabels), 1)
        self.assertEqual(len(result.halts(repair=False)), 1)
        self.assertEqual(result.halts(repair=True), ())

    def test_repeated_id_in_fetch_raises(self) -> None:
        threads = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "a", 1, db_id=1, body="a"),
            _fetched(REAL_ID_A, "b", 2, db_id=2, body="b"),
        ]})
        with self.assertRaises(ValueError):
            check_thread_ids(threads, self.triage())

    def test_malformed_triage_raises(self) -> None:
        with self.assertRaises(ValueError):
            check_thread_ids(self.threads, self.write("triage.json", {"threads": None}))


class TestCheckThreadIdsHandler(_Coherence):

    def run_handler(self, triage_path: str, *, repair: bool) -> tuple[int, str, str]:
        args = argparse.Namespace(threads=self.threads, triage=triage_path, repair=repair)
        return _call(_cmd_check_thread_ids, args)

    def test_pass_states_zero_repairs_explicitly(self) -> None:
        code, out, err = self.run_handler(self.triage(*_coherent_triage()), repair=True)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ok checked=3 repaired=0 skipped_null=1 halted=0", out)

    def test_relabel_without_repair_halts_and_writes_nothing(self) -> None:
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 9, db_id=101))
        before = self.read("triage.json")
        code, out, _ = self.run_handler(path, repair=False)
        self.assertEqual(code, 1)
        self.assertIn("HALT", out)
        self.assertEqual(self.read("triage.json"), before)

    def test_repair_rewrites_coordinates_and_records_audit(self) -> None:
        path = self.triage(_triage(REAL_ID_A, "wf.yaml", 9, db_id=101),
                           extra={"_id_repairs": [{"earlier": True}]})
        code, out, _ = self.run_handler(path, repair=True)
        self.assertEqual(code, 0)
        self.assertIn("repaired=1", out)
        doc = self.read("triage.json")
        self.assertEqual((doc["threads"][0]["path"], doc["threads"][0]["line"]), ("wf.yaml", 7))
        self.assertEqual(doc["_id_repairs"], [
            {"earlier": True},
            {"thread_id": REAL_ID_A, "from": {"path": "wf.yaml", "line": 9},
             "to": {"path": "wf.yaml", "line": 7}},
        ])
        # Idempotent: a second pass finds nothing left to repair.
        self.assertIn("repaired=0", self.run_handler(path, repair=True)[1])

    def test_repair_writes_nothing_when_anything_halts(self) -> None:
        path = self.triage(
            _triage(REAL_ID_A, "wf.yaml", 9, db_id=101),
            _triage(REAL_ID_B, "wf.yaml", 7, db_id=999),
        )
        before = self.read("triage.json")
        code, _, _ = self.run_handler(path, repair=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.read("triage.json"), before)

    def test_rejected_id_never_echoed(self) -> None:
        hostile = "PRRT_x$(touch pwned)'; rm -rf /"
        code, out, err = self.run_handler(
            self.triage(_triage(hostile, "wf.yaml", 7, db_id=101)), repair=True
        )
        self.assertEqual(code, 1)
        self.assertNotIn("pwned", out + err)
        self.assertIn("triage threads[0]", err)

    def test_unreadable_triage_exits_one(self) -> None:
        code, _, err = self.run_handler(str(self.root / "absent.json"), repair=False)
        self.assertEqual(code, 1)
        self.assertIn("check-thread-ids:", err)


# ---------------------------------------------------------------------------
# End to end through the real wrapper
# ---------------------------------------------------------------------------


class TestReviewIdsEndToEnd(_Coherence):
    """Exit status through ./bin/workflow is the contract the YAML branches on."""

    def workflow(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fixed argv, no shell, repo-owned binary
            [str(bin_path("workflow")), *argv], capture_output=True, text=True,
            cwd=str(repo_root()), check=False, timeout=_WRAPPER_TIMEOUT_S,
        )

    def test_check_fix_index_pass_and_fail(self) -> None:
        good = self.write("fix-index.json", _index(_ids(REAL_ID_TRAILING_DASH, UNLINKED_A)))
        self.assertEqual(self.workflow("check-fix-index", good).returncode, 0)
        bad = self.write("bad-index.json", _index([_entry("x", "a$(id)b"), *_ids("y", "y")]))
        proc = self.workflow("check-fix-index", bad)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("$(id)", proc.stdout + proc.stderr)

    def test_thread_fingerprints_known_answer(self) -> None:
        path = self.write("threads.json", {"threads": [
            _fetched(REAL_ID_A, "a.py", 1, db_id=1, body=KNOWN_BODY),
        ]})
        proc = self.workflow("thread-fingerprints", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)[0]["body_fingerprint"], KNOWN_FINGERPRINT)

    def test_check_thread_ids_pass_swap_and_repair(self) -> None:
        self.assertEqual(
            self.workflow("check-thread-ids", self.threads, self.triage(*_coherent_triage())).returncode, 0
        )
        swap = self.triage(_triage(REAL_ID_A, "wf.yaml", 7, db_id=102),
                           _triage(REAL_ID_B, "wf.yaml", 7, db_id=101))
        self.assertEqual(self.workflow("check-thread-ids", self.threads, swap, "--repair").returncode, 1)
        relabel = self.triage(_triage(REAL_ID_A, "wf.yaml", 9, db_id=101))
        self.assertEqual(self.workflow("check-thread-ids", self.threads, relabel).returncode, 1)
        self.assertEqual(
            self.workflow("check-thread-ids", self.threads, relabel, "--repair").returncode, 0
        )
        self.assertEqual(self.read("triage.json")["threads"][0]["line"], 7)


# ---------------------------------------------------------------------------
# fix-aggregate
# ---------------------------------------------------------------------------


def _result(finding_id: str, thread_id: str | None, **overrides: object) -> dict[str, Any]:
    """A thread-fixer result object with a passing fix, overridable per field."""
    base: dict[str, Any] = {
        "id": finding_id, "thread_id": thread_id, "action": "fixed",
        "files_changed": ["src/a.py"], "tests_added": [f"tests/test_{_file_id(finding_id)}.py"],
        "test_result": "pass",
    }
    base.update(overrides)
    return base


class _Aggregate(_JsonFiles):
    """An index with two threaded findings and two unlinked (null-thread) ones
    whose ids sanitise to the same characters. The threaded pair is anchored
    to src/b.py, the unlinked pair to src/a.py."""

    def setUp(self) -> None:
        super().setUp()
        self.fixes = self.root / "fixes"
        self.fixes.mkdir()
        self.index = self._write_index("src/b.py", "src/a.py")

    def _write_index(self, *paths: str) -> str:
        return self.write("fix-index.json", _index(
            [_entry(REAL_ID_A, thread_id=REAL_ID_A),
             _entry(REAL_ID_TRAILING_DASH, thread_id=REAL_ID_TRAILING_DASH)],
            _ids(UNLINKED_A, UNLINKED_B),
            paths=paths,
        ))

    def _write_result(self, stem: str, doc: object) -> None:
        (self.fixes / f"{stem}.json").write_text(json.dumps(doc), encoding="utf-8")

    def _write_for(self, finding_id: str, doc: object) -> None:
        self._write_result(_file_id(finding_id), doc)

    def _write_all_valid(self) -> None:
        self._write_for(REAL_ID_A, _result(REAL_ID_A, REAL_ID_A, files_changed=["src/b.py"]))
        self._write_for(REAL_ID_TRAILING_DASH, _result(REAL_ID_TRAILING_DASH, REAL_ID_TRAILING_DASH,
                                                      action="rejected", files_changed=[]))
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None))
        self._write_for(UNLINKED_B, _result(UNLINKED_B, None, files_changed=["src/a.py"]))

    def _merged(self) -> dict[str, Any]:
        return aggregate_fix_results(self.index, self.fixes).to_json()


class TestAggregateFixResults(_Aggregate):

    def test_all_valid_results_are_credited_in_index_order(self) -> None:
        self._write_all_valid()
        doc = self._merged()
        self.assertEqual((doc["total_expected"], doc["total_results"]), (4, 4))
        self.assertEqual([r["id"] for r in doc["results"]],
                         [REAL_ID_A, REAL_ID_TRAILING_DASH, UNLINKED_A, UNLINKED_B])
        self.assertEqual((doc["missing_results"], doc["key_mismatches"], doc["failed_tests"]), ([], [], []))
        self.assertEqual(doc["by_action"], {"fixed": 3, "rejected": 1, "moot": 0, "deferred": 0})
        # REAL_ID_TRAILING_DASH is "rejected"; its tests_added must not be folded in
        # even though the fixture leaves that field at its "fixed" default.
        test_files = sorted(f"tests/test_{_file_id(i)}.py"
                            for i in (REAL_ID_A, UNLINKED_A, UNLINKED_B))
        self.assertEqual(doc["files_changed"], ["src/a.py", "src/b.py", *test_files])

    def test_test_files_are_committed_with_their_fix(self) -> None:
        """Dry run on PR #405: the fixer listed only the src file in
        files_changed and its test as a test id, so commit-and-push -- which
        stages exactly files_changed -- would have pushed the fix without
        its tests. The test file must be in the list."""
        self.index = self._write_index("src/b.py", "src/core/dryrun_sample.py")
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None,
            files_changed=["src/core/dryrun_sample.py"],
            tests_added=["tests/core_tests/test_dryrun_sample.py::TestX::test_rejects_bool",
                         "tests/core_tests/test_dryrun_sample.py::TestX::test_accepts_int"],
        ))
        self.assertEqual(self._merged()["files_changed"],
                         ["src/core/dryrun_sample.py", "tests/core_tests/test_dryrun_sample.py"])

    def test_rejected_results_tests_added_is_not_staged(self) -> None:
        """A rejected/moot/deferred result did not touch its test file --
        crediting tests_added from it would stage a file the fixer never
        wrote. PR #406 review: the _write_all_valid fixture already had a
        rejected result carrying a leftover tests_added value and it was
        (before this fix) folded into files_changed anyway."""
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None, action="rejected", files_changed=[],
            tests_added=["tests/unrelated/test_untouched.py::T::test_y"],
        ))
        self.assertEqual(self._merged()["files_changed"], [])

    def test_non_fixed_files_changed_is_not_authorized(self) -> None:
        """PR #406 round 5: check-unlisted subtracts this list from the dirty
        set, so a path listed by a moot/rejected result could never be
        reported as an unlisted edit. Only fixed results may authorize a
        commit; an edit a non-fixed result really made stays unlisted and
        fails the gate."""
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None, action="moot", files_changed=["src/sneaky.py"],
            tests_added=["tests/unrelated/test_untouched.py::T::test_y"],
        ))
        self._write_for(UNLINKED_B, _result(UNLINKED_B, None, files_changed=["src/a.py"],
                                            tests_added=[]))
        self.assertEqual(self._merged()["files_changed"], ["src/a.py"])

    def test_source_file_outside_the_fixers_scope_is_not_authorized(self) -> None:
        """PR #406 round 7: a fixed result could list any safe path, pass
        check-paths, and have check-unlisted subtract it -- so a compromised
        fixer's edit to an unrelated source file was committed. Only the
        group's own file and tests/ paths are authorized."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, files_changed=["src/a.py", "src/other.py"],
                                            tests_added=["tests/x/test_a.py::T::t"]))
        doc = self._merged()
        self.assertEqual(doc["files_changed"], ["src/a.py", "tests/x/test_a.py"])
        self.assertEqual(doc["out_of_scope_paths"], [{"id": UNLINKED_A, "path": "src/other.py"}])

    def test_unsafe_test_ids_never_reach_the_readable_lists(self) -> None:
        """PR #406 round 13: results stay verbatim and verify-fixes read
        every tests_added id from disk, so ../../.envrc::x was a file-read
        instruction. Only validated ids are published for reading."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, files_changed=["src/a.py"], tests_added=[
            "tests/x/test_a.py::T::t", "../../.envrc::x", "/etc/passwd::t", ".claude/hooks/test_h.py::T::t"]))
        doc = self._merged()
        self.assertEqual(doc["tests_added"], ["tests/x/test_a.py::T::t"])
        self.assertEqual(doc["tests_by_result"], {UNLINKED_A: ["tests/x/test_a.py::T::t"]})
        self.assertEqual(sorted(r["test"] for r in doc["rejected_tests_added"]),
                         ["../../.envrc::x", ".claude/hooks/test_h.py::T::t", "/etc/passwd::t"])

    def test_non_fixed_results_publish_no_tests(self) -> None:
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, action="rejected", files_changed=[],
                                            tests_added=["tests/x/test_a.py::T::t"]))
        doc = self._merged()
        self.assertEqual((doc["tests_added"], doc["tests_by_result"]), ([], {}))

    def test_unrelated_test_file_is_out_of_scope(self) -> None:
        """PR #406 round 12: every path under tests/ was authorized, so a
        fixer could edit tests/other.py, list it, and have it committed.
        Only the test files its own tests_added ids name are in scope."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None,
                                            files_changed=["src/a.py", "tests/x/test_a.py", "tests/other.py"],
                                            tests_added=["tests/x/test_a.py::T::t"]))
        doc = self._merged()
        self.assertEqual(doc["files_changed"], ["src/a.py", "tests/x/test_a.py"])
        self.assertEqual(doc["out_of_scope_paths"], [{"id": UNLINKED_A, "path": "tests/other.py"}])

    def test_another_groups_file_is_out_of_scope(self) -> None:
        """src/b.py belongs to the threaded group; the unlinked group's fixer
        may not claim it."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, files_changed=["src/b.py"], tests_added=[]))
        doc = self._merged()
        self.assertEqual(doc["files_changed"], [])
        self.assertEqual(doc["out_of_scope_paths"], [{"id": UNLINKED_A, "path": "src/b.py"}])

    def test_group_with_no_file_authorizes_only_tests(self) -> None:
        self.index = self.write("fix-index.json", {
            "total": 1, "items": [{"index": "0", "data": {"path": None, "threads": _ids(UNLINKED_A)}}]})
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, files_changed=["src/a.py"],
                                            tests_added=["tests/x/test_a.py::T::t"]))
        doc = self._merged()
        self.assertEqual(doc["files_changed"], ["tests/x/test_a.py"])
        self.assertEqual(doc["out_of_scope_paths"], [{"id": UNLINKED_A, "path": "src/a.py"}])

    def test_protected_test_path_is_never_authorized(self) -> None:
        """A test id is the one route a file could take around files_changed.
        A "test" outside tests/ is outside the fixer's scope: it is reported,
        and left off files_changed so check-unlisted refuses the edit."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, files_changed=["src/a.py"],
                                            tests_added=[".claude/hooks/test_x.py::T::t"]))
        doc = self._merged()
        self.assertNotIn(".claude/hooks/test_x.py", doc["files_changed"])
        self.assertIn({"id": UNLINKED_A, "path": ".claude/hooks/test_x.py"}, doc["out_of_scope_paths"])

    def test_non_path_test_ids_are_not_guessed_into_paths(self) -> None:
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None, files_changed=["src/a.py"],
            tests_added=["tests.core_tests.test_x.TestX.test_y", "", "::orphan", 7],
        ))
        self.assertEqual(self._merged()["files_changed"], ["src/a.py"])

    def test_nested_safe_test_path_is_folded_in(self) -> None:
        """A multi-segment path built entirely from safe characters still
        reaches files_changed -- the allowlist must not over-reject."""
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None, files_changed=["src/a.py"],
            tests_added=["tests/workflow_tests/sub-dir/test_x.py::T::test_y"],
        ))
        self.assertIn("tests/workflow_tests/sub-dir/test_x.py", self._merged()["files_changed"])

    def test_shell_metacharacter_test_ids_are_rejected(self) -> None:
        """A test id containing shell metacharacters must not reach
        files_changed: commit-and-push interpolates files_changed into shell
        command text (``git add <file1> <file2> ...``), not an argv array, so
        an unrejected ``$(...)`` or backtick would execute on staging."""
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None, files_changed=["src/a.py"],
            tests_added=[
                "tests/$(id).py::T::test",
                "tests/`id`.py::T::test",
                "tests/../../etc/passwd.py::T::test",
                "tests/a b.py::T::test",
                "tests/te;st.py::T::test",
            ],
        ))
        self.assertEqual(self._merged()["files_changed"], ["src/a.py"])

    def test_shell_metacharacter_files_changed_are_rejected(self) -> None:
        """A reported files_changed entry gets the same safe-path contract as
        a tests_added id: it too is fixer/LLM-authored text that reaches
        commit-and-push's shell-interpolated ``check-paths <...>`` and
        ``git add <...>`` before check-paths runs over the built list, so an
        unrejected ``$(...)``, backtick, or embedded whitespace must not
        survive aggregation."""
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None,
            files_changed=[
                "src/a.py",
                "src/$(id).py",
                "src/`id`.py",
                "src/../../etc/passwd",
                "src/a b.py",
                "src/te;st.py",
            ],
            tests_added=[],
        ))
        self.assertEqual(self._merged()["files_changed"], ["src/a.py"])

    def test_safe_nested_files_changed_still_reaches_the_list(self) -> None:
        """The contract must not over-reject: a plain multi-segment path
        built from safe characters is still credited."""
        self.index = self._write_index("src/b.py", "src/workflow/sub-dir/mod_1.py")
        self._write_for(UNLINKED_A, _result(
            UNLINKED_A, None,
            files_changed=["src/workflow/sub-dir/mod_1.py"],
            tests_added=[],
        ))
        self.assertEqual(self._merged()["files_changed"], ["src/workflow/sub-dir/mod_1.py"])

    def test_null_thread_findings_reconcile_on_id(self) -> None:
        """Reconciling on thread_id would look for null.json and lose both."""
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None))
        self._write_for(UNLINKED_B, _result(UNLINKED_B, None))
        doc = self._merged()
        self.assertEqual([r["id"] for r in doc["results"]], [UNLINKED_A, UNLINKED_B])

    def test_missing_results_lists_ids(self) -> None:
        self._write_all_valid()
        (self.fixes / f"{_file_id(UNLINKED_B)}.json").unlink()
        (self.fixes / f"{_file_id(REAL_ID_A)}.json").unlink()
        self.assertEqual(self._merged()["missing_results"], [REAL_ID_A, UNLINKED_B])

    def assert_mismatch(self, stem: str, doc: object, reason: str) -> dict[str, Any]:
        self._write_all_valid()
        self._write_result(stem, doc)
        merged = self._merged()
        self.assertEqual([m["file"] for m in merged["key_mismatches"]], [f"{stem}.json"])
        self.assertIn(reason, merged["key_mismatches"][0]["reason"])
        return merged

    def test_missing_in_file_id_is_a_mismatch_never_backfilled(self) -> None:
        result = _result(UNLINKED_A, None)
        del result["id"]
        merged = self.assert_mismatch(_file_id(UNLINKED_A), result, "id field is missing")
        self.assertEqual(merged["missing_results"], [UNLINKED_A])
        self.assertNotIn(UNLINKED_A, [r.get("id") for r in merged["results"]])

    def test_in_file_id_equal_to_filename_is_a_mismatch(self) -> None:
        """The file_id is not the id: an id copied from the filename fails."""
        stem = _file_id(UNLINKED_A)
        merged = self.assert_mismatch(stem, _result(stem, None), "id field does not equal")
        self.assertEqual(merged["missing_results"], [UNLINKED_A])

    def test_in_file_id_names_another_finding(self) -> None:
        merged = self.assert_mismatch(_file_id(UNLINKED_A), _result(UNLINKED_B, None),
                                      "id field does not equal")
        self.assertEqual(merged["key_mismatches"][0]["id_in_file"], UNLINKED_B)
        self.assertEqual(merged["missing_results"], [UNLINKED_A])

    def test_thread_id_differs_from_index(self) -> None:
        for finding_id, thread_id in ((UNLINKED_A, REAL_ID_A), (REAL_ID_A, None), (REAL_ID_A, REAL_ID_B)):
            with self.subTest(finding_id=finding_id, thread_id=thread_id):
                merged = self.assert_mismatch(_file_id(finding_id), _result(finding_id, thread_id),
                                              "thread_id does not equal")
                self.assertEqual(merged["missing_results"], [finding_id])

    def test_stray_file_is_a_mismatch_not_a_missing_finding(self) -> None:
        merged = self.assert_mismatch("null", _result(UNLINKED_A, None), "not a file_id")
        self.assertEqual(merged["missing_results"], [])

    def test_unreadable_result_is_a_mismatch(self) -> None:
        for doc in ([1, 2], "text"):
            with self.subTest(doc=doc):
                self.assert_mismatch(_file_id(UNLINKED_A), doc, "not a readable JSON object")
        (self.fixes / f"{_file_id(UNLINKED_B)}.json").write_text("{not json", encoding="utf-8")
        reasons = [m["reason"] for m in self._merged()["key_mismatches"]]
        self.assertIn("not a readable JSON object", reasons)

    def test_failed_tests_lists_unproven_fixes_only(self) -> None:
        self._write_for(REAL_ID_A, _result(REAL_ID_A, REAL_ID_A, test_result="fail"))
        self._write_for(REAL_ID_TRAILING_DASH, _result(REAL_ID_TRAILING_DASH, REAL_ID_TRAILING_DASH,
                                                      test_result="maybe"))
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None, action="rejected", test_result="not-run"))
        self._write_for(UNLINKED_B, _result(UNLINKED_B, None))
        self.assertEqual(self._merged()["failed_tests"], [
            {"id": REAL_ID_A, "thread_id": REAL_ID_A, "test_result": "fail"},
            {"id": REAL_ID_TRAILING_DASH, "thread_id": REAL_ID_TRAILING_DASH,
             "test_result": "not-run"},
        ])

    def test_out_of_scope_requests_lifted_and_tagged_with_id(self) -> None:
        self._write_all_valid()
        self._write_for(UNLINKED_A, _result(UNLINKED_A, None,
                                            out_of_scope_requests=["edit .github/ci.yml"]))
        self._write_result("stray", _result("stray", None, out_of_scope_requests=["x"]))
        self.assertEqual(self._merged()["out_of_scope_requests"],
                         [{"id": UNLINKED_A, "request": "edit .github/ci.yml"}])

    def test_absent_fixes_dir_reports_everything_missing(self) -> None:
        self.fixes.rmdir()
        self.assertEqual(len(self._merged()["missing_results"]), 4)

    def test_index_failing_gate_raises(self) -> None:
        index = self.write("fix-index.json", _index([_entry("a", "same"), _entry("b", "same")]))
        with self.assertRaises(ValueError):
            aggregate_fix_results(index, self.fixes)


class TestAggregateFixResultsHandler(_Aggregate):

    def args(self, index: str) -> argparse.Namespace:
        return argparse.Namespace(index=index, fixes_dir=str(self.fixes),
                                  out=str(self.root / "fix-results.json"))

    def test_writes_aggregate_and_counts(self) -> None:
        self._write_all_valid()
        (self.fixes / f"{_file_id(UNLINKED_B)}.json").unlink()
        code, out, err = _call(_cmd_aggregate_fix_results, self.args(self.index))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("expected=4 results=3 missing=1", out)
        self.assertEqual(self.read("fix-results.json")["total_results"], 3)

    def test_bad_index_exits_one_and_writes_nothing(self) -> None:
        index = self.write("bad-index.json", _index([_entry("x", "a$(id)b")]))
        code, out, err = _call(_cmd_aggregate_fix_results, self.args(index))
        self.assertEqual((code, out), (1, ""))
        self.assertNotIn("$(id)", err)
        self.assertFalse((self.root / "fix-results.json").exists())


class TestAggregateFixResultsEndToEnd(_Aggregate):

    def test_real_wrapper(self) -> None:
        self._write_all_valid()
        out = str(self.root / "fix-results.json")
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell, repo-owned binary
            [str(bin_path("workflow")), "aggregate-fix-results", self.index, str(self.fixes), out],
            capture_output=True, text=True, cwd=str(repo_root()), check=False,
            timeout=_WRAPPER_TIMEOUT_S,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read("fix-results.json")["total_results"], 4)


if __name__ == "__main__":
    unittest.main()
