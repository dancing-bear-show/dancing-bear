"""Tests for workflow.review_ids and its three ``./bin/workflow`` subcommands.

These checks were Python snippets embedded in review-fix-threads.yaml that no
test ever ran. Every rule here records a real failure on PR #391: shifted and
fabricated thread ids, swapped ids on a shared (path, line), and finding_keys
that collide or are unsafe as filenames.
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

from tests.fixtures import TempDirMixin, bin_path, repo_root
from workflow.cli_dispatch import (
    _cmd_aggregate_fix_results,
    _cmd_check_finding_keys,
    _cmd_check_thread_ids,
    _cmd_thread_fingerprints,
)
from workflow.review_ids import (
    ISSUE_ABSENT,
    ISSUE_BAD_DISCRIMINATOR,
    ISSUE_FETCH_HAS_NO_VALUE,
    ISSUE_MISMATCH,
    ISSUE_NO_RECORDED_VALUE,
    FindingKeyResult,
    aggregate_fix_results,
    body_fingerprint,
    check_finding_keys,
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

UNSAFE_KEYS = ("../x", "a/b", ".hidden", "a$(id)b", "body 0", "a;rm", "a'b", "-x")


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
        "finding_key": thread_id or f"body-{db_id}",
    }


def _triage_fp(thread_id: str, path: str, line: int, fingerprint: str | None) -> dict[str, Any]:
    """A triage entry that names the fingerprint as its discriminator."""
    entry = _triage(thread_id, path, line, discriminator="fingerprint")
    entry["body_fingerprint"] = fingerprint
    return entry


def _index(*groups: Sequence[object]) -> dict[str, Any]:
    """Build a fix-index.json with one item per group of finding_keys."""
    return {
        "total": len(groups),
        "items": [
            {"index": str(i), "data": {"path": f"f{i}.py", "threads": [
                {"finding_key": key, "thread_id": None} if key is not _NO_KEY
                else {"thread_id": None}
                for key in keys
            ]}}
            for i, keys in enumerate(groups)
        ],
    }


_NO_KEY = object()


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
# finding_key gate
# ---------------------------------------------------------------------------


class TestCheckFindingKeys(_JsonFiles):

    def check(self, *groups: Sequence[object]) -> FindingKeyResult:
        return check_finding_keys(self.write("fix-index.json", _index(*groups)))

    def test_legitimate_shapes_pass(self) -> None:
        result = self.check([REAL_ID_TRAILING_DASH, "body-3"], ["123456789", REAL_ID_A])
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.checked, 4)

    def test_real_id_with_trailing_dash_passes(self) -> None:
        self.assertTrue(self.check([REAL_ID_TRAILING_DASH]).ok)

    def test_two_null_id_findings_with_distinct_keys_pass(self) -> None:
        self.assertTrue(self.check(["body-0", "body-1"]).ok)

    def test_empty_index_passes(self) -> None:
        self.assertTrue(check_finding_keys(self.write("fix-index.json", {"total": 0, "items": []})).ok)

    def test_duplicate_across_items_fails(self) -> None:
        result = self.check(["body-0"], ["body-0"])
        self.assertFalse(result.ok)
        self.assertEqual(
            result.failures,
            ("items[1].data.threads[0]: finding_key duplicates items[0].data.threads[0]",),
        )

    def test_duplicate_within_item_fails(self) -> None:
        self.assertFalse(self.check([REAL_ID_A, REAL_ID_A]).ok)

    def test_several_missing_report_as_missing_not_duplicate(self) -> None:
        result = self.check([_NO_KEY, None, ""])
        self.assertEqual(len(result.failures), 3)
        for failure in result.failures:
            with self.subTest(failure=failure):
                self.assertIn("is missing", failure)
                self.assertNotIn("duplicate", failure)

    def test_each_unsafe_shape_fails(self) -> None:
        for key in UNSAFE_KEYS:
            with self.subTest(key=key):
                result = self.check([key])
                self.assertFalse(result.ok)
                self.assertIn("is not [A-Za-z0-9]", result.failures[0])

    def test_non_string_key_fails(self) -> None:
        self.assertIn("not a string", self.check([123]).failures[0])

    def test_length_boundary(self) -> None:
        self.assertTrue(self.check(["a" * 100]).ok)
        self.assertFalse(self.check(["a" * 101]).ok)

    def test_trailing_newline_is_rejected(self) -> None:
        """fullmatch, not match-with-$: '$' would accept a trailing newline."""
        self.assertFalse(self.check(["body-0\n"]).ok)

    def test_rejected_values_never_echoed(self) -> None:
        result = self.check(list(UNSAFE_KEYS) + ["dup-me", "dup-me"])
        text = "\n".join(result.failures)
        for key in (*UNSAFE_KEYS, "dup-me"):
            with self.subTest(key=key):
                self.assertNotIn(key, text)

    def test_malformed_index_raises(self) -> None:
        malformed: tuple[dict[str, object], ...] = (
            {"items": {}}, {"items": [{"data": {}}]}, {"items": ["x"]},
        )
        for doc in malformed:
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                check_finding_keys(self.write("fix-index.json", doc))


class TestCheckFindingKeysHandler(_JsonFiles):

    def run_handler(self, doc: object) -> tuple[int, str, str]:
        path = self.write("fix-index.json", doc)
        return _call(_cmd_check_finding_keys, argparse.Namespace(file=path))

    def test_pass_exits_zero(self) -> None:
        code, out, err = self.run_handler(_index(["body-0", REAL_ID_A]))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ok checked=2 failed=0", out)

    def test_fail_exits_one_without_echo(self) -> None:
        code, out, err = self.run_handler(_index(list(UNSAFE_KEYS)))
        self.assertEqual(code, 1)
        self.assertIn(f"failed={len(UNSAFE_KEYS)}", out)
        for key in UNSAFE_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, out + err)

    def test_malformed_file_exits_one(self) -> None:
        path = self.write("fix-index.json", {"items": 3})
        code, _, err = _call(_cmd_check_finding_keys, argparse.Namespace(file=path))
        self.assertEqual(code, 1)
        self.assertIn("check-finding-keys:", err)


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

    def test_check_finding_keys_pass_and_fail(self) -> None:
        good = self.write("fix-index.json", _index([REAL_ID_TRAILING_DASH, "body-0"]))
        self.assertEqual(self.workflow("check-finding-keys", good).returncode, 0)
        bad = self.write("bad-index.json", _index(["a$(id)b", "body-0", "body-0"]))
        proc = self.workflow("check-finding-keys", bad)
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


def _result(key: str, thread_id: str | None, **overrides: object) -> dict[str, Any]:
    """A thread-fixer result object with a passing fix, overridable per field."""
    base: dict[str, Any] = {
        "finding_key": key, "thread_id": thread_id, "action": "fixed",
        "files_changed": ["src/a.py"], "tests_added": [f"tests/test_{key}.py"],
        "test_result": "pass",
    }
    base.update(overrides)
    return base


class _Aggregate(_JsonFiles):
    """An index with two threaded findings and two null-id findings."""

    def setUp(self) -> None:
        super().setUp()
        self.fixes = self.root / "fixes"
        self.fixes.mkdir()
        self.index = self.write("fix-index.json", {"total": 2, "items": [
            {"index": "0", "data": {"path": "a.py", "threads": [
                {"finding_key": REAL_ID_A, "thread_id": REAL_ID_A},
                {"finding_key": REAL_ID_TRAILING_DASH, "thread_id": REAL_ID_TRAILING_DASH},
            ]}},
            {"index": "1", "data": {"path": None, "threads": [
                {"finding_key": "body-0", "thread_id": None},
                {"finding_key": "body-1", "thread_id": None},
            ]}},
        ]})

    def _write_result(self, stem: str, doc: object) -> None:
        (self.fixes / f"{stem}.json").write_text(json.dumps(doc), encoding="utf-8")

    def _write_all_valid(self) -> None:
        self._write_result(REAL_ID_A, _result(REAL_ID_A, REAL_ID_A))
        self._write_result(REAL_ID_TRAILING_DASH, _result(REAL_ID_TRAILING_DASH, REAL_ID_TRAILING_DASH,
                                                action="rejected", files_changed=[]))
        self._write_result("body-0", _result("body-0", None))
        self._write_result("body-1", _result("body-1", None, files_changed=["src/a.py", "src/b.py"]))

    def _merged(self) -> dict[str, Any]:
        return aggregate_fix_results(self.index, self.fixes).to_json()


class TestAggregateFixResults(_Aggregate):

    def test_all_valid_results_are_credited_in_index_order(self) -> None:
        self._write_all_valid()
        doc = self._merged()
        self.assertEqual((doc["total_expected"], doc["total_results"]), (4, 4))
        self.assertEqual([r["finding_key"] for r in doc["results"]],
                         [REAL_ID_A, REAL_ID_TRAILING_DASH, "body-0", "body-1"])
        self.assertEqual((doc["missing_results"], doc["key_mismatches"], doc["failed_tests"]), ([], [], []))
        self.assertEqual(doc["by_action"], {"fixed": 3, "rejected": 1, "moot": 0, "deferred": 0})
        self.assertEqual(doc["files_changed"], ["src/a.py", "src/b.py"])

    def test_null_id_findings_reconcile_on_finding_key(self) -> None:
        """Reconciling on thread_id would look for null.json and lose both."""
        self._write_result("body-0", _result("body-0", None))
        self._write_result("body-1", _result("body-1", None))
        doc = self._merged()
        self.assertEqual([r["finding_key"] for r in doc["results"]], ["body-0", "body-1"])

    def test_missing_file_is_reported_with_its_thread_id(self) -> None:
        self._write_all_valid()
        (self.fixes / "body-1.json").unlink()
        (self.fixes / f"{REAL_ID_A}.json").unlink()
        self.assertEqual(self._merged()["missing_results"], [
            {"finding_key": REAL_ID_A, "thread_id": REAL_ID_A},
            {"finding_key": "body-1", "thread_id": None},
        ])

    def assert_mismatch(self, stem: str, doc: object, reason: str) -> dict[str, Any]:
        self._write_all_valid()
        self._write_result(stem, doc)
        merged = self._merged()
        self.assertEqual([m["file"] for m in merged["key_mismatches"]], [f"{stem}.json"])
        self.assertIn(reason, merged["key_mismatches"][0]["reason"])
        self.assertNotIn(stem, [r["finding_key"] for r in merged["results"]])
        return merged

    def test_missing_in_file_key_is_a_mismatch_never_backfilled(self) -> None:
        result = _result("body-0", None)
        del result["finding_key"]
        merged = self.assert_mismatch("body-0", result, "finding_key field is missing")
        self.assertIn({"finding_key": "body-0", "thread_id": None}, merged["missing_results"])

    def test_in_file_key_differs_from_filename(self) -> None:
        merged = self.assert_mismatch("body-0", _result("body-1", None), "does not equal the filename")
        self.assertEqual(merged["key_mismatches"][0]["finding_key_in_file"], "body-1")
        self.assertIn({"finding_key": "body-0", "thread_id": None}, merged["missing_results"])

    def test_thread_id_differs_from_index(self) -> None:
        for stem, thread_id in (("body-0", REAL_ID_A), (REAL_ID_A, None), (REAL_ID_A, REAL_ID_B)):
            with self.subTest(stem=stem, thread_id=thread_id):
                self.assert_mismatch(stem, _result(stem, thread_id), "thread_id does not equal")

    def test_stray_file_is_a_mismatch_not_a_missing_finding(self) -> None:
        merged = self.assert_mismatch("null", _result("null", None), "not a finding_key")
        self.assertEqual(merged["missing_results"], [])

    def test_unreadable_result_is_a_mismatch(self) -> None:
        for doc in ([1, 2], "text"):
            with self.subTest(doc=doc):
                self.assert_mismatch("body-0", doc, "not a readable JSON object")
        (self.fixes / "body-1.json").write_text("{not json", encoding="utf-8")
        reasons = [m["reason"] for m in self._merged()["key_mismatches"]]
        self.assertIn("not a readable JSON object", reasons)

    def test_failed_tests_lists_unproven_fixes_only(self) -> None:
        self._write_result(REAL_ID_A, _result(REAL_ID_A, REAL_ID_A, test_result="fail"))
        self._write_result(REAL_ID_TRAILING_DASH, _result(REAL_ID_TRAILING_DASH, REAL_ID_TRAILING_DASH,
                                                test_result="maybe"))
        self._write_result("body-0", _result("body-0", None, action="rejected", test_result="not-run"))
        self._write_result("body-1", _result("body-1", None))
        self.assertEqual(self._merged()["failed_tests"], [
            {"finding_key": REAL_ID_A, "thread_id": REAL_ID_A, "test_result": "fail"},
            {"finding_key": REAL_ID_TRAILING_DASH, "thread_id": REAL_ID_TRAILING_DASH,
             "test_result": "not-run"},
        ])

    def test_absent_fixes_dir_reports_everything_missing(self) -> None:
        self.fixes.rmdir()
        self.assertEqual(len(self._merged()["missing_results"]), 4)

    def test_index_failing_key_gate_raises(self) -> None:
        index = self.write("fix-index.json", _index(["body-0", "body-0"]))
        with self.assertRaises(ValueError):
            aggregate_fix_results(index, self.fixes)


class TestAggregateFixResultsHandler(_Aggregate):

    def args(self, index: str) -> argparse.Namespace:
        return argparse.Namespace(index=index, fixes_dir=str(self.fixes),
                                  out=str(self.root / "fix-results.json"))

    def test_writes_aggregate_and_counts(self) -> None:
        self._write_all_valid()
        (self.fixes / "body-1.json").unlink()
        code, out, err = _call(_cmd_aggregate_fix_results, self.args(self.index))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("expected=4 results=3 missing=1", out)
        self.assertEqual(self.read("fix-results.json")["total_results"], 3)

    def test_bad_index_exits_one_and_writes_nothing(self) -> None:
        index = self.write("bad-index.json", _index(["a$(id)b"]))
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
