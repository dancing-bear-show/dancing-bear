"""Identity checks for the review-fix-threads workflow, as tested code.

These checks used to be Python snippets embedded in the workflow YAML, which an
LLM agent re-typed and executed at run time. No test ever ran them, and the
body fingerprint in particular was reproduced verbatim in three stages that had
to agree byte-for-byte -- three agents re-implementing one hash can disagree,
one tested implementation cannot.

These live here, each behind a ``./bin/workflow`` subcommand:

* :func:`body_fingerprint` -- the fallback discriminator for a review thread.
* :func:`check_fix_index` -- every fixer writes ``fixes/<file_id>.json`` and
  aggregation matches it back by ``id``, so an id or file_id that is missing,
  repeated, or (for file_id) not filename-safe loses or misplaces a result.
* :func:`check_thread_ids` -- the id-coherence gate: triage has been observed
  shifting thread ids by one position and fabricating one, and a shifted id
  resolves the wrong thread successfully rather than erroring.
* :func:`aggregate_fix_results` -- merges ``fixes/<file_id>.json`` into
  fix-results.json, crediting a result only when its identity checks out.

Inputs are always read from workspace JSON files by path. Nothing a reviewer
or an LLM wrote is ever taken from the command line, and diagnostics name an
offending entry by its POSITION in the file, never by echoing its value: a
rejected id, file_id or thread_id is untrusted text by definition.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.fileutil import atomic_write_json
from workflow.param_guard import load_params

#: Allowlist for a fix-index file_id. It becomes a filename, and an LLM stage
#: builds the index, so only this narrow shape is accepted. Every legitimate
#: file_id already fits it: core.copilot_overview._file_id replaces everything
#: outside ``[A-Za-z0-9._-]`` and appends a hash, and every id starts with an
#: alphanumeric (``PRRT_``, ``unlinked:``, ``comment:``). The alphanumeric first
#: character rules out ``.``/``..``/hidden names and a leading ``-`` read as an
#: option. Do not widen it into a denylist.
FILE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")

#: Allowlist for one ``/``-separated segment of the path half of a
#: ``tests_added`` id (before ``::``), which fix-aggregate folds into
#: ``files_changed`` in :func:`_test_file_of` below. files_changed is staged
#: with commit-and-push's ``git add <file1> <file2> ...`` and
#: ``./bin/workflow check-paths <file1> <file2> ...`` -- both LLM agent stages
#: that interpolate the path into shell command text, not a sandboxed argv
#: array. A fixer/LLM-authored id such as ``tests/$(...)\.py::T::test`` would
#: otherwise reach that text unchanged. Only plain relative POSIX path
#: characters are accepted per segment (alphanumeric, ``.``, ``_``, ``-``); no
#: ``\``, quotes, ``$``, backticks, parens, semicolons, or whitespace. A
#: leading ``.`` is allowed so dotdirs like ``.claude``/``.github`` still
#: reach files_changed and get refused downstream by check-paths -- a leading
#: ``-`` is rejected so a segment can never be read as a flag, and a segment
#: of exactly ``.`` or ``..`` is rejected separately, below, to block
#: traversal. A rejected id yields ``None``, the same outcome as a
#: non-path-shaped id -- commit-and-push's unlisted-edit check (Step 3b) is
#: what catches a test file that reaches the tree without going through this
#: path.
_TEST_PATH_SEGMENT = re.compile(r"(?!-)[A-Za-z0-9._-]+")

DISCRIMINATOR_DATABASE_ID = "database_id"
DISCRIMINATOR_FINGERPRINT = "fingerprint"

#: Coherence issue kinds. Every one of them halts the gate.
ISSUE_ABSENT = "thread_id is not in threads.json"
ISSUE_BAD_DISCRIMINATOR = "discriminator is missing or not database_id|fingerprint"
ISSUE_NO_RECORDED_VALUE = "the named discriminator has no recorded value"
ISSUE_FETCH_HAS_NO_VALUE = "threads.json has no value for the named discriminator"
ISSUE_MISMATCH = "discriminator differs from threads.json (swapped or wrong id)"
ISSUE_RELABEL = "coordinates differ from threads.json (repairable with --repair)"


def body_fingerprint(body: str) -> str:
    """Return the sha256 fingerprint of a review comment body.

    Normalise CRLF, collapse whitespace WITHIN each line to single spaces, keep
    line structure, strip the whole, encode UTF-8. It does NOT collapse
    newlines. The algorithm is pinned by a known-answer test: values recorded
    by an earlier run are compared against this one, so any change to it
    silently fails every comparison.
    """
    normalised = "\n".join(
        " ".join(line.split()) for line in body.replace("\r\n", "\n").split("\n")
    ).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _list_at(doc: dict[str, Any], key: str, path: str | Path) -> list[Any]:
    value = doc.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path}: {key!r} is not a JSON list")
    return value


def _first_comment(thread: dict[str, Any]) -> dict[str, Any]:
    comments = thread.get("comments")
    if isinstance(comments, list) and comments and isinstance(comments[0], dict):
        return comments[0]
    return {}


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadFingerprint:
    """The discriminators for one threads.json entry, by position."""

    index: int
    thread_id: str | None
    database_id: int | str | None
    body_fingerprint: str | None


def thread_fingerprints(threads_path: str | Path) -> list[ThreadFingerprint]:
    """Compute the first-comment fingerprint of every thread in threads.json.

    Raises:
        ValueError: if the file is unreadable or not the expected shape.
    """
    threads = _list_at(load_params(threads_path, key=None), "threads", threads_path)
    rows: list[ThreadFingerprint] = []
    for index, thread in enumerate(threads):
        if not isinstance(thread, dict):
            raise ValueError(f"{threads_path}: threads[{index}] is not a JSON object")
        first = _first_comment(thread)
        body = first.get("body")
        thread_id = thread.get("thread_id")
        rows.append(ThreadFingerprint(
            index=index,
            thread_id=thread_id if isinstance(thread_id, str) else None,
            database_id=_db_id(first.get("database_id")),
            body_fingerprint=body_fingerprint(body) if isinstance(body, str) else None,
        ))
    return rows


# ---------------------------------------------------------------------------
# fix-index gate: id and file_id
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixIndexResult:
    """Outcome of the fix-index gate. ``ok`` is the contract.

    Each failure names an entry by position only; the value itself is never
    included, because a rejected id or file_id is untrusted text.
    """

    checked: int
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures


def _index_entries(index_path: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(position, entry)`` for every finding in a fix-index.json.

    Raises:
        ValueError: if the file is unreadable or not the expected shape.
    """
    items = _list_at(load_params(index_path, key=None), "items", index_path)
    entries: list[tuple[str, dict[str, Any]]] = []
    for i, item in enumerate(items):
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("threads"), list):
            raise ValueError(f"{index_path}: items[{i}].data.threads is not a JSON list")
        for j, entry in enumerate(data["threads"]):
            entries.append((f"items[{i}].data.threads[{j}]",
                            entry if isinstance(entry, dict) else {}))
    return entries


def check_fix_index(index_path: str | Path) -> FixIndexResult:
    """Validate every finding's ``id`` and ``file_id`` in a fix-index.json.

    ``id`` must be a non-empty string, unique across the whole index: it is
    what aggregation matches a result back to. ``file_id`` must be a string,
    unique, and match :data:`FILE_ID_PATTERN` in full: it names the result
    file, so a repeat makes one fixer overwrite another's result. Several
    missing values are reported as missing, never as duplicates of one another.

    Raises:
        ValueError: if the file is unreadable or not the expected shape.
    """
    entries = _index_entries(index_path)
    failures: list[str] = []
    seen_ids: dict[str, str] = {}
    seen_files: dict[str, str] = {}
    for where, entry in entries:
        for failure in (
            _unique_string_failure("id", entry.get("id"), where, seen_ids, None),
            _unique_string_failure("file_id", entry.get("file_id"), where, seen_files,
                                   FILE_ID_PATTERN),
        ):
            if failure:
                failures.append(failure)
    return FixIndexResult(checked=len(entries), failures=tuple(failures))


def _unique_string_failure(field_name: str, value: object, where: str,
                           first_seen: dict[str, str],
                           pattern: re.Pattern[str] | None) -> str | None:
    if value is None or value == "":
        return f"{where}: {field_name} is missing"
    if not isinstance(value, str):
        return f"{where}: {field_name} is not a string"
    if pattern is not None and not pattern.fullmatch(value):
        return f"{where}: {field_name} is not {pattern.pattern}"
    if value in first_seen:
        return f"{where}: {field_name} duplicates {first_seen[value]}"
    first_seen[value] = where
    return None


# ---------------------------------------------------------------------------
# Thread-id coherence gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Relabel:
    """A triage entry whose id and discriminator check out but whose
    coordinates do not. The id is the identity; the fetch's coordinates win."""

    index: int
    thread_id: str
    old_path: object
    old_line: object
    path: object
    line: object


@dataclass(frozen=True)
class CoherenceResult:
    """Outcome of the id-coherence gate."""

    checked: int
    skipped_null: int
    relabels: tuple[Relabel, ...] = ()
    issues: tuple[str, ...] = ()

    def halts(self, *, repair: bool) -> tuple[str, ...]:
        """Everything that stops the gate. Empty means pass.

        A relabel halts too unless the caller is going to repair it: the
        resolve-threads gate runs after repair and must see matching
        coordinates, while fix-dispatch is where repair belongs.
        """
        if repair:
            return self.issues
        return self.issues + tuple(
            f"triage threads[{r.index}]: {ISSUE_RELABEL}" for r in self.relabels
        )


def _db_id(value: object) -> int | str | None:
    """Accept a database id as an int or an all-digit string; else None.

    A bool is an int subclass and is rejected explicitly.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return value
    return None


def _fetch_map(threads_path: str | Path) -> dict[str, dict[str, Any]]:
    """Key threads.json by thread_id. A repeated id makes the fetch ambiguous."""
    threads = _list_at(load_params(threads_path, key=None), "threads", threads_path)
    by_id: dict[str, dict[str, Any]] = {}
    for index, thread in enumerate(threads):
        if not isinstance(thread, dict):
            raise ValueError(f"{threads_path}: threads[{index}] is not a JSON object")
        thread_id = thread.get("thread_id")
        if thread_id is None:
            continue
        if not isinstance(thread_id, str) or thread_id in by_id:
            raise ValueError(f"{threads_path}: threads[{index}] has a non-string or repeated thread_id")
        by_id[thread_id] = thread
    return by_id


def _recorded_and_fetched(kind: object, entry: dict[str, Any], fetched: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (value triage recorded, value the fetch holds) for ``kind``, as text."""
    first = _first_comment(fetched)
    if kind == DISCRIMINATOR_DATABASE_ID:
        held_id = _db_id(entry.get("comment_database_id"))
        truth_id = _db_id(first.get("database_id"))
        return (
            None if held_id is None else str(held_id),
            None if truth_id is None else str(truth_id),
        )
    held = entry.get("body_fingerprint")
    body = first.get("body")
    return (
        held if isinstance(held, str) and held else None,
        body_fingerprint(body) if isinstance(body, str) else None,
    )


def _discriminator_issue(entry: dict[str, Any], fetched: dict[str, Any]) -> str | None:
    """Compare the discriminator triage NAMED against the fetch's."""
    kind = entry.get("discriminator")
    if kind not in (DISCRIMINATOR_DATABASE_ID, DISCRIMINATOR_FINGERPRINT):
        return ISSUE_BAD_DISCRIMINATOR
    held, truth = _recorded_and_fetched(kind, entry, fetched)
    if held is None:
        return ISSUE_NO_RECORDED_VALUE
    if truth is None:
        return ISSUE_FETCH_HAS_NO_VALUE
    return None if held == truth else ISSUE_MISMATCH


def _relabel(index: int, thread_id: str, entry: dict[str, Any], fetched: dict[str, Any]) -> Relabel | None:
    if (entry.get("path"), entry.get("line")) == (fetched.get("path"), fetched.get("line")):
        return None
    return Relabel(
        index=index, thread_id=thread_id,
        old_path=entry.get("path"), old_line=entry.get("line"),
        path=fetched.get("path"), line=fetched.get("line"),
    )


def check_thread_ids(threads_path: str | Path, triage_path: str | Path) -> CoherenceResult:
    """Check every non-null thread_id in triage.json against threads.json.

    Per entry, in order: a null thread_id is skipped (review-body and
    issue-comment findings legitimately have none); the id must exist in the
    fetch; the discriminator triage NAMED (``database_id`` preferred,
    ``fingerprint`` as fallback) must match the fetch's. A discriminator
    mismatch halts even when coordinates match -- that is the swap case, and
    coordinates are exactly what cannot tell a swapped pair apart. Only once
    the id and discriminator agree is a coordinate difference treated as a
    relabel, which is repairable.

    Raises:
        ValueError: if either file is unreadable or not the expected shape.
    """
    by_id = _fetch_map(threads_path)
    entries = _list_at(load_params(triage_path, key=None), "threads", triage_path)
    checked = skipped = 0
    relabels: list[Relabel] = []
    issues: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{triage_path}: threads[{index}] is not a JSON object")
        thread_id = entry.get("thread_id")
        if thread_id is None:
            skipped += 1
            continue
        checked += 1
        fetched = by_id.get(thread_id) if isinstance(thread_id, str) else None
        issue = ISSUE_ABSENT if fetched is None else _discriminator_issue(entry, fetched)
        if issue or fetched is None:
            issues.append(f"triage threads[{index}]: {issue}")
            continue
        relabel = _relabel(index, thread_id, entry, fetched)
        if relabel:
            relabels.append(relabel)
    return CoherenceResult(checked, skipped, tuple(relabels), tuple(issues))


def apply_relabels(triage_path: str | Path, relabels: tuple[Relabel, ...]) -> None:
    """Rewrite triage.json with the fetch's coordinates, recording each change.

    Appends to ``_id_repairs`` so the run stays auditable. Written atomically.
    """
    doc = load_params(triage_path, key=None)
    entries = _list_at(doc, "threads", triage_path)
    log = doc.get("_id_repairs")
    repairs: list[Any] = log if isinstance(log, list) else []
    for r in relabels:
        entries[r.index]["path"] = r.path
        entries[r.index]["line"] = r.line
        repairs.append({
            "thread_id": r.thread_id,
            "from": {"path": r.old_path, "line": r.old_line},
            "to": {"path": r.path, "line": r.line},
        })
    doc["_id_repairs"] = repairs
    atomic_write_json(triage_path, doc)


# ---------------------------------------------------------------------------
# fix-aggregate: merge per-finding results, verifying each one's identity
# ---------------------------------------------------------------------------

_KNOWN_ACTIONS = ("fixed", "rejected", "moot", "deferred")
_UNPROVEN_TEST_RESULTS = ("fail", "not-run")


@dataclass(frozen=True)
class _Expected:
    id: str
    file_id: str
    thread_id: object


@dataclass(frozen=True)
class FixResults:
    """The fix-results.json document fix-aggregate writes."""

    total_expected: int
    results: tuple[dict[str, Any], ...]
    missing_results: tuple[str, ...]
    key_mismatches: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        by_action = dict.fromkeys(_KNOWN_ACTIONS, 0)
        for result in self.results:
            action = str(result.get("action"))
            by_action[action] = by_action.get(action, 0) + 1
        return {
            "total_expected": self.total_expected,
            "total_results": len(self.results),
            "by_action": by_action,
            "files_changed": _files_changed(self.results),
            "tests_added": _union_of(self.results, "tests_added"),
            "missing_results": list(self.missing_results),
            "failed_tests": [_failed_test(r) for r in self.results if _is_unproven_fix(r)],
            "key_mismatches": list(self.key_mismatches),
            "out_of_scope_requests": _out_of_scope_requests(self.results),
            "results": list(self.results),
        }


def _union_of(results: tuple[dict[str, Any], ...], field_name: str) -> list[str]:
    values: set[str] = set()
    for result in results:
        items = result.get(field_name)
        if isinstance(items, list):
            values.update(item for item in items if isinstance(item, str))
    return sorted(values)


def _test_file_of(test_id: str) -> str | None:
    """``tests/x/test_y.py::Class::method`` -> ``tests/x/test_y.py``.

    Only a path-shaped id yields a file, and only one built from safe
    characters: every ``/``-separated segment must match
    ``_TEST_PATH_SEGMENT`` (alphanumeric, ``.``, ``_``, ``-``, no leading
    ``-``) and not be exactly ``.`` or ``..``, which rejects traversal and
    every shell metacharacter (``$``, backticks, parens, quotes, ``;``,
    whitespace, ``\\``) before the value can reach files_changed and the
    shell command text commit-and-push builds from it. A dotted module id
    (``tests.x.test_y.Class``) cannot be mapped to a path without guessing
    where the module ends, so it yields None; commit-and-push's unlisted-edit
    check is what catches a test file that reaches the tree that way.
    """
    path = test_id.split("::", 1)[0].strip()
    if not path.endswith(".py"):
        return None
    segments = path.split("/")
    if any(segment in (".", "..") for segment in segments):
        return None
    if not all(_TEST_PATH_SEGMENT.fullmatch(segment) for segment in segments):
        return None
    return path


def _files_changed(results: tuple[dict[str, Any], ...]) -> list[str]:
    """Every file a fixer edited: its files_changed plus its tests' files.

    The fixer schema records tests as test ids, not paths, and a fixer that
    followed it listed only the source file here. commit-and-push stages
    exactly this list, so the fix was pushed without its tests -- and
    verify-fixes tests the working tree, where the tests still existed, so
    the run could not see it. Deriving the paths in tested code rather than
    trusting each fixer to repeat them also routes every test file through
    check-paths, which runs over this list.
    """
    paths = set(_union_of(results, "files_changed"))
    for test_id in _union_of(results, "tests_added"):
        path = _test_file_of(test_id)
        if path:
            paths.add(path)
    return sorted(paths)


def _out_of_scope_requests(results: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """Lift every credited result's out_of_scope_requests, tagged with its id.

    A security signal -- comment text that tried to steer a fixer outside its
    file -- so it is surfaced at the top level rather than left for a reader
    to dig out of each result.
    """
    lifted: list[dict[str, Any]] = []
    for result in results:
        requests = result.get("out_of_scope_requests")
        if isinstance(requests, list):
            lifted.extend({"id": result["id"], "request": r} for r in requests)
    return lifted


def _is_unproven_fix(result: dict[str, Any]) -> bool:
    """A "fixed" result whose tests did not demonstrably pass."""
    return result.get("action") == "fixed" and result.get("test_result") != "pass"


def _failed_test(result: dict[str, Any]) -> dict[str, Any]:
    reported = result.get("test_result")
    return {
        "id": result["id"],
        "thread_id": result.get("thread_id"),
        # Anything but a recognised failure value is treated as not run.
        "test_result": reported if reported in _UNPROVEN_TEST_RESULTS else "not-run",
    }


def _expected_findings(index_path: str | Path) -> list[_Expected]:
    """Every finding in fix-index.json, after re-asserting the index gate."""
    gate = check_fix_index(index_path)
    if not gate.ok:
        raise ValueError(f"{index_path}: fix-index gate fails; run check-fix-index")
    return [
        _Expected(id=entry["id"], file_id=entry["file_id"], thread_id=entry.get("thread_id"))
        for _, entry in _index_entries(index_path)
    ]


def _read_result(path: Path) -> dict[str, Any] | None:
    try:
        return load_params(path, key=None)
    except ValueError:
        return None


def _mismatch(stem: str, obj: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    return {
        "file": f"{stem}.json",
        "id_in_file": (obj or {}).get("id"),
        "thread_id_in_file": (obj or {}).get("thread_id"),
        "reason": reason,
    }


def _identity_failure(stem: str, obj: dict[str, Any] | None,
                      expected: dict[str, _Expected]) -> str | None:
    """Why a result file cannot be credited to the finding its name claims."""
    if obj is None:
        return "not a readable JSON object"
    if stem not in expected:
        return "filename is not a file_id in fix-index.json"
    if "id" not in obj:
        return "id field is missing"
    if obj["id"] != expected[stem].id:
        return "id field does not equal the fix-index entry's"
    if obj.get("thread_id") != expected[stem].thread_id:
        return "thread_id does not equal the fix-index entry's"
    return None


def aggregate_fix_results(index_path: str | Path, fixes_dir: str | Path) -> FixResults:
    """Merge ``fixes/<file_id>.json`` files against fix-index.json.

    Reconciles on the index's ``id``, never thread_id: findings with no thread
    share ``thread_id: null`` and would all look for ``null.json``. A result is
    credited only if its filename stem is an expected file_id, its in-file
    ``id`` equals that entry's ``id`` exactly (never backfilled from the
    filename), and its ``thread_id`` equals the entry's (null only equals
    null). Any other file is a key mismatch; if its name is an expected
    file_id, that finding is also reported missing, because its outcome is
    unknown. ``missing_results`` lists ids.

    Raises:
        ValueError: if fix-index.json is unreadable, malformed, or fails the
            fix-index gate.
    """
    expected_list = _expected_findings(index_path)
    expected = {e.file_id: e for e in expected_list}
    directory = Path(fixes_dir)
    files = sorted(p for p in directory.glob("*.json") if p.is_file()) if directory.is_dir() else []
    credited: dict[str, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    for path in files:
        obj = _read_result(path)
        reason = _identity_failure(path.stem, obj, expected)
        if reason:
            mismatches.append(_mismatch(path.stem, obj, reason))
        elif obj is not None:
            credited[path.stem] = obj
    return FixResults(
        total_expected=len(expected_list),
        results=tuple(credited[e.file_id] for e in expected_list if e.file_id in credited),
        missing_results=tuple(e.id for e in expected_list if e.file_id not in credited),
        key_mismatches=tuple(mismatches),
    )
