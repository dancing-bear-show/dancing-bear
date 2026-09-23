"""PR-review-thread subcommand handlers for the workflow CLI.

Handles check-fix-index, thread-fingerprints, check-thread-ids,
aggregate-fix-results, check-paths, and parse-overview command handlers,
plus their private helpers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.cli_errors import CLIError, ExitCode


# ---------------------------------------------------------------------------
# parse-overview helpers
# ---------------------------------------------------------------------------


def _require_object_list(path: Path, data: dict, key: str) -> None:
    """Raise unless ``data[key]`` exists and is a list of objects."""
    if key not in data:
        raise CLIError(
            f"{path} has no '{key}' key: it was produced by a fetch that "
            "does not preserve it. Re-run the pr-review-threads fragment "
            "before parsing the overview.",
            ExitCode.USAGE,
        )
    if not isinstance(data[key], list):
        raise CLIError(
            f"{path} has a malformed '{key}': expected a list, got "
            f"{type(data[key]).__name__}.",
            ExitCode.USAGE,
        )
    for index, element in enumerate(data[key]):
        if not isinstance(element, dict):
            raise CLIError(
                f"{path} has a malformed '{key}[{index}]': expected an "
                f"object, got {type(element).__name__}.",
                ExitCode.USAGE,
            )


def _load_threads_json(path: Path) -> dict:
    """Read and shape-check a threads.json before any parsing.

    Every defect caught here would otherwise degrade to present:false /
    status:ok — indistinguishable from a PR that genuinely has no Copilot
    overview — so a broken input would read as a clean pass and triage would
    silently skip every overview rule.
    """
    if not path.is_file():
        raise CLIError(f"threads file not found: {path}", ExitCode.USAGE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CLIError(f"threads file is not valid JSON: {exc}", ExitCode.USAGE) from exc
    if not isinstance(data, dict):
        raise CLIError(
            f"{path} is not a JSON object (got {type(data).__name__}).",
            ExitCode.USAGE,
        )
    for key in ("review_bodies", "threads"):
        _require_object_list(path, data, key)
    return data


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_check_fix_index(args: argparse.Namespace) -> int:
    """Fail unless every fix-index.json entry has a unique ``id`` and a unique,
    filename-safe ``file_id``. Exit 0 pass, 1 fail. Offending entries are named
    by position only -- a rejected value is untrusted text and is never echoed.
    """
    from workflow.review_ids import check_fix_index

    try:
        result = check_fix_index(args.file)
    except ValueError as exc:
        print(f"check-fix-index: {exc}", file=sys.stderr)
        return 1
    for failure in result.failures:
        print(f"check-fix-index: {failure}", file=sys.stderr)
    status = "ok" if result.ok else "FAILED"
    print(f"check-fix-index: {status} checked={result.checked} failed={len(result.failures)}")
    return 0 if result.ok else 1


def _cmd_thread_fingerprints(args: argparse.Namespace) -> int:
    """Write each threads.json entry's discriminators as a JSON list to stdout."""
    from dataclasses import asdict

    from workflow.review_ids import thread_fingerprints

    try:
        rows = thread_fingerprints(args.file)
    except ValueError as exc:
        print(f"thread-fingerprints: {exc}", file=sys.stderr)
        return 1
    print(json.dumps([asdict(row) for row in rows], indent=2))
    return 0


def _cmd_check_thread_ids(args: argparse.Namespace) -> int:
    """Id-coherence gate: triage.json thread ids against threads.json.

    Exit 0 pass, 1 halt. A coordinate-only difference is a halt unless
    ``--repair`` is given, in which case triage.json is rewritten with the
    fetch's coordinates. Every other issue halts regardless, and nothing is
    written when anything halts.
    """
    from workflow.review_ids import apply_relabels, check_thread_ids

    try:
        result = check_thread_ids(args.threads, args.triage)
    except ValueError as exc:
        print(f"check-thread-ids: {exc}", file=sys.stderr)
        return 1
    halts = result.halts(repair=args.repair)
    for halt in halts:
        print(f"check-thread-ids: {halt}", file=sys.stderr)
    repaired = 0
    if not halts and result.relabels:
        apply_relabels(args.triage, result.relabels)
        repaired = len(result.relabels)
    print(
        f"check-thread-ids: {'HALT' if halts else 'ok'} checked={result.checked} "
        f"repaired={repaired} skipped_null={result.skipped_null} halted={len(halts)}"
    )
    return 1 if halts else 0


def _cmd_aggregate_fix_results(args: argparse.Namespace) -> int:
    """Merge per-finding fixer results into fix-results.json.

    Exit 0 once the aggregate is written -- missing results and key mismatches
    are recorded IN it for downstream stages, not treated as a failure here.
    Exit 1, writing nothing, if fix-index.json is unreadable or fails the
    fix-index gate. The summary names counts only.
    """
    from core.fileutil import atomic_write_json
    from workflow.review_ids import aggregate_fix_results

    try:
        merged = aggregate_fix_results(args.index, args.fixes_dir)
    except ValueError as exc:
        print(f"aggregate-fix-results: {exc}", file=sys.stderr)
        return 1
    doc = merged.to_json()
    atomic_write_json(args.out, doc)
    print(
        f"aggregate-fix-results: expected={doc['total_expected']} "
        f"results={doc['total_results']} missing={len(doc['missing_results'])} "
        f"failed_tests={len(doc['failed_tests'])} key_mismatches={len(doc['key_mismatches'])} "
        f"out_of_scope_requests={len(doc['out_of_scope_requests'])}"
    )
    return 0


def _cmd_check_paths(args: argparse.Namespace) -> int:
    """Refuse paths an unattended fixer must never edit or push.

    The deterministic backstop for commit-and-push: its agent runs this over
    the files it is about to stage, so a fixer steered into ``.git/hooks`` or
    ``.claude/settings.json`` is stopped by tested code rather than by prose.
    Prints one line per refused path; exits 0 only when every path is safe.
    """
    from core.copilot_overview import classify_repo_path

    refused = 0
    for raw in args.paths:
        _, reason = classify_repo_path(raw)
        if reason is not None:
            refused += 1
            print(f"REFUSED {reason}: {raw}")
    if refused:
        print(f"{refused} of {len(args.paths)} path(s) refused", file=sys.stderr)
        return int(ExitCode.ERROR)
    return 0


def _cmd_parse_overview(args: argparse.Namespace) -> int:
    """Parse Copilot overview bodies out of a fetched threads.json.

    The parser lives in core.copilot_overview so it is unit-testable; this
    handler only does I/O. Workflow stages call it rather than reimplementing
    the scan inline, which is how the documented rules and the executed ones
    stay the same thing.
    """
    from core.copilot_overview import parse_overview

    data = _load_threads_json(Path(args.threads_json))

    result = parse_overview(
        review_bodies=data["review_bodies"],
        threads=data["threads"],
        pr_number=args.pr_number or str(data.get("pr_number") or ""),
    )

    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out_path:
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(rendered)
    return 0
