"""PR-review-thread subcommand handlers for the workflow CLI.

Handles check-fix-index, thread-fingerprints, check-thread-ids,
aggregate-fix-results, check-paths, parse-overview, snapshot-dirty,
check-unlisted and review-rounds command handlers, plus their private helpers.
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


def _cmd_snapshot_dirty(args: argparse.Namespace) -> int:
    """Record the checkout's dirty paths and HEAD before any fixer runs.

    check-unlisted compares against this, so a file another session already
    had dirty is not blamed on the run -- unless its content changes. The
    recorded HEAD lets check-unlisted also catch a fixer that stages and
    commits an unlisted file before it runs, via ``committed_since``: ``git
    status`` alone reports a committed path clean.

    HEAD is captured *before* the status snapshot, not after. In the shared
    checkout, a commit from another session can land between the two calls;
    capturing HEAD first means that commit is always at or after the
    recorded baseline, so ``committed_since`` (which walks commits strictly
    after ``baseline_head``) is guaranteed to see it. Capturing HEAD second
    would instead record the post-commit sha as the baseline itself, making
    that same commit invisible to both the dirty-path comparison (the path
    was never dirty in this snapshot) and ``committed_since`` (it is not
    after its own baseline).
    """
    from core.fileutil import atomic_write_json
    from workflow.worktree_gate import head_commit, snapshot_dirty

    try:
        head = head_commit(Path.cwd())
        snapshot = snapshot_dirty(Path.cwd())
    except RuntimeError as exc:
        print(f"snapshot-dirty: {exc}", file=sys.stderr)
        return 1
    atomic_write_json(args.out, {"dirty": snapshot, "head": head})
    print(f"snapshot-dirty: {len(snapshot)} dirty path(s) recorded")
    return 0


def _load_json_object(path: str, what: str) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{what} unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{what} is not a JSON object")
    return doc


def _verify_baseline_provenance(baseline_path: str) -> dict:
    """Re-hash *baseline_path*, compare against pr-context.json's record, and
    return the exact bytes that were hashed, parsed as JSON.

    dirty-baseline.json is written into the same fixer-writable workspace
    directory that every later fix-threads agent (Bash, Write) can also
    write to, so an unverified read would let a fixer rewrite the baseline
    with post-edit hashes -- or drop its own unlisted entry -- to make this
    gate pass on a false baseline. init records the file's sha256, taken
    right after writing it and before any fixer ran, as
    "dirty_baseline_sha256" in pr-context.json -- a sibling file no later
    stage is ever instructed to modify. Re-hashing here and failing closed
    on any mismatch (or a missing/malformed record) makes a rewritten
    baseline rejected rather than trusted.

    The caller must use the returned object rather than re-reading
    baseline_path itself: a separate read would not be atomic with the
    hash check above, so a fixer-writable file replaced between the two
    reads could pass verification against its old content while the
    caller ends up parsing different, unverified bytes.

    Raises:
        ValueError: pr-context.json is missing/unreadable, its
            dirty_baseline_sha256 field is missing or not a string, the
            current hash of *baseline_path* no longer matches it, or the
            verified bytes are not a JSON object.
    """
    import hashlib

    context_path = Path(baseline_path).parent / "pr-context.json"
    if not context_path.is_file():
        raise ValueError(f"pr-context.json not found beside baseline at {context_path}")
    context = _load_json_object(str(context_path), "pr-context")
    expected = context.get("dirty_baseline_sha256")
    if not isinstance(expected, str) or not expected:
        raise ValueError("pr-context.json has no 'dirty_baseline_sha256' string")
    try:
        baseline_bytes = Path(baseline_path).read_bytes()
    except OSError as exc:
        raise ValueError(f"baseline unreadable: {exc}") from exc
    actual = hashlib.sha256(baseline_bytes).hexdigest()
    if actual != expected:
        raise ValueError(
            "dirty-baseline.json does not match dirty_baseline_sha256 recorded in "
            "pr-context.json -- baseline may have been rewritten after init"
        )
    try:
        doc = json.loads(baseline_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"baseline is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("baseline is not a JSON object")
    return doc


def _cmd_check_unlisted(args: argparse.Namespace) -> int:
    """Fail if the run changed a file fix-results.json does not list.

    commit-and-push stages exactly files_changed, so an unlisted edit would be
    left behind silently -- and it would also never pass through check-paths,
    which runs over the same list. Fails closed: an unreadable input, a
    tampered baseline (see ``_verify_baseline_provenance``), or a failed
    ``git status``/``git rev-parse``/``git diff`` is exit 1, never a pass.
    """
    from workflow.worktree_gate import committed_since, snapshot_dirty, unlisted_changes

    try:
        baseline_doc = _verify_baseline_provenance(args.baseline)
        baseline = baseline_doc.get("dirty")
        baseline_head = baseline_doc.get("head")
        listed = _load_json_object(args.fix_results, "fix-results").get("files_changed")
        if not isinstance(baseline, dict):
            raise ValueError("baseline has no 'dirty' object")
        # snapshot-dirty always records it; without it a committed unlisted
        # file is invisible, so its absence fails closed rather than skipping.
        if not isinstance(baseline_head, str) or not baseline_head:
            raise ValueError("baseline has no 'head' commit")
        if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
            raise ValueError("fix-results files_changed is not a list of strings")
        current = snapshot_dirty(Path.cwd())
        committed = committed_since(Path.cwd(), baseline_head)
    except (ValueError, RuntimeError) as exc:
        print(f"check-unlisted: {exc}", file=sys.stderr)
        return 1
    unlisted = unlisted_changes(baseline, current, listed, committed=committed)
    for path in unlisted:
        print(f"UNLISTED: {path}")
    if unlisted:
        print(f"{len(unlisted)} changed path(s) missing from files_changed", file=sys.stderr)
        return 1
    return 0


def _parse_pr_list(raw: str) -> list[int]:
    """Parse a comma-separated PR list; dedupe, keeping first-seen order.

    Raises ValueError naming the bad token, or when no number is given.
    """
    numbers: list[int] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if not token.isdigit() or int(token) < 1:
            raise ValueError(f"invalid --prs value {token!r}: expected positive PR numbers")
        numbers.append(int(token))
    if not numbers:
        raise ValueError("--prs names no PR numbers")
    return list(dict.fromkeys(numbers))


def _review_rounds_arg_error(args: argparse.Namespace) -> str | None:
    """Return the usage error for review-rounds' selector flags, or None."""
    from workflow.review_rounds import RECENT_MAX

    if (args.prs is None) == (args.recent is None):
        return "give exactly one of --prs or --recent"
    if args.recent is not None and not 1 <= args.recent <= RECENT_MAX:
        return f"--recent must be 1..{RECENT_MAX}, got {args.recent}"
    if args.min_threads is not None and args.min_threads < 0:
        return f"--min-threads must be >= 0, got {args.min_threads}"
    return None


def _cmd_review_rounds(args: argparse.Namespace) -> int:
    """Fetch PR review-round data and write per-PR JSON + summary.

    Accepts exactly one of --prs (explicit list) or --recent (the N most
    recent PRs, any state). --min-threads defaults to DEFAULT_MIN_THREADS for
    --recent and to 0 for --prs: a named PR is never filtered out unless the
    caller asks. Exit 1 on bad arguments, API failure or truncated pagination.
    """
    from core.gh_cli import GhError
    from core.github import client
    from core.github.repo import resolve_owner_repo
    from workflow.review_rounds import DEFAULT_MIN_THREADS, fetch_recent_prs, run_review_rounds

    error = _review_rounds_arg_error(args)
    if error:
        print(f"review-rounds: {error}", file=sys.stderr)
        return 1
    if args.prs is not None:
        try:
            pr_numbers = _parse_pr_list(args.prs)
        except ValueError as exc:
            print(f"review-rounds: {exc}", file=sys.stderr)
            return 1
    default_floor = 0 if args.prs is not None else DEFAULT_MIN_THREADS
    min_threads: int = default_floor if args.min_threads is None else args.min_threads

    gh = client()
    if args.prs is None:
        try:
            owner, repo = resolve_owner_repo(gh)
            pr_numbers = fetch_recent_prs(gh, owner, repo, args.recent)
        except GhError as exc:
            print(f"review-rounds: {exc}", file=sys.stderr)
            return 1

    if not pr_numbers:
        print("review-rounds: no PRs to process", file=sys.stderr)
        return 1

    return run_review_rounds(
        pr_numbers=pr_numbers,
        out_dir=Path(args.out_dir),
        min_threads=min_threads,
        gh=gh,
    )
