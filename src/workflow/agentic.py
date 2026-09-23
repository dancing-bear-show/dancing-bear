"""Agentic capsule for the workflow CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for workflow."""
    lines: list[str] = []
    lines.append("agentic: workflow")
    lines.append("purpose: YAML DAG workflow engine — parse, compile, run, lint, and manage workflows")
    lines.append("commands:")
    lines.append("  - run: ./bin/workflow run <file.yaml> --params k=v")
    lines.append("  - list: ./bin/workflow list")
    lines.append("  - lint: ./bin/workflow lint <file.yaml>")
    lines.append("  - parse: ./bin/workflow parse <file.yaml>")
    lines.append("  - compile: ./bin/workflow compile <file.yaml>")
    lines.append("  - status: ./bin/workflow status <workspace-dir>")
    lines.append("  - init-workspace: ./bin/workflow init-workspace <file.yaml>")
    lines.append("  - resume: ./bin/workflow resume <workspace-dir>")
    lines.append("  - validate-fragment: ./bin/workflow validate-fragment <fragment.yaml>")
    lines.append(
        "  - check-params: ./bin/workflow check-params <workspace>/manifest.json "
        "--check 'name=regex' [--top-level] [--print name]"
    )
    lines.append(
        "  - parse-overview: ./bin/workflow parse-overview <workspace>/outputs/threads.json "
        "[--pr N] [--out <workspace>/outputs/review-overview.json]"
    )
    lines.append("  - check-paths: ./bin/workflow check-paths <path> [<path> ...]")
    lines.append(
        "  - check-fix-index: ./bin/workflow check-fix-index <workspace>/outputs/fix-index.json"
    )
    lines.append(
        "  - thread-fingerprints: ./bin/workflow thread-fingerprints <workspace>/outputs/threads.json"
    )
    lines.append(
        "  - check-thread-ids: ./bin/workflow check-thread-ids <workspace>/outputs/threads.json "
        "<workspace>/outputs/triage.json [--repair]"
    )
    lines.append(
        "  - aggregate-fix-results: ./bin/workflow aggregate-fix-results "
        "<workspace>/outputs/fix-index.json <workspace>/outputs/fixes <workspace>/outputs/fix-results.json"
    )
    lines.append("  - snapshot-dirty: ./bin/workflow snapshot-dirty <workspace>/outputs/dirty-baseline.json")
    lines.append(
        "  - check-unlisted: ./bin/workflow check-unlisted <workspace>/outputs/dirty-baseline.json "
        "<workspace>/outputs/fix-results.json"
    )
    lines.append("notes:")
    lines.append("  - ./bin/workflow list is the authoritative live catalog of available workflows")
    lines.append("  - file arguments are positional (./bin/workflow run <file>), not --input")
    lines.append("  - --params accepts k=v pairs; repeat for multiple params")
    lines.append("  - resume exits 0 if all stages done, exits 2 if stages remain")
    lines.append(
        "  - check-params validates trigger params as JSON data (exit 0 pass, 1 fail); "
        "--print writes one value to stdout only if every --check passed, so a stage "
        "can capture it with HOST=$(...) instead of interpolating the raw param; "
        "--top-level reads fields from the document root, for stage outputs such as "
        "handler.json rather than the manifest's trigger_params"
    )
    lines.append(
        "  - check-fix-index / check-thread-ids are review-fix-threads gates (exit 0 pass, "
        "1 fail); failures go to stderr naming entries by position, never echoing a value; "
        "check-thread-ids --repair rewrites triage.json coordinates from the fetch and records "
        "_id_repairs, every other mismatch halts"
    )
    lines.append(
        "  - thread-fingerprints prints JSON [{index, thread_id, database_id, body_fingerprint}]; "
        "the fingerprint is the one tested sha256 every stage must use"
    )
    lines.append(
        "  - check-fix-index requires every fix-index entry's id unique and file_id unique and "
        "matching [A-Za-z0-9][A-Za-z0-9._-]{0,199}"
    )
    lines.append(
        "  - aggregate-fix-results credits fixes/<file_id>.json only if the stem is an expected "
        "file_id and its in-file id and thread_id equal that entry's; anything else is a "
        "key_mismatch and its finding is missing (missing_results lists ids). Exit 0 once "
        "written, 1 (nothing written) on a bad index"
    )
    lines.append(
        "  - parse-overview emits Copilot overview findings (linked and unlinked, each with id "
        "and file_id); check-paths exits 1 printing REFUSED for any path that escapes the repo "
        "or is protected"
    )
    lines.append(
        "  - check-unlisted exits 1 printing UNLISTED for every path changed since the "
        "snapshot-dirty baseline (new, content-changed, reverted, or committed since the "
        "baseline HEAD) that fix-results files_changed omits; fails closed on unreadable "
        "input, a failed git call, a baseline with no head, or a baseline whose sha256 "
        "differs from dirty_baseline_sha256 in the sibling pr-context.json"
    )
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
