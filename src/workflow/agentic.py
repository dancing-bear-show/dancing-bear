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
        "  - check-finding-keys: ./bin/workflow check-finding-keys <workspace>/outputs/fix-index.json"
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
        "  - check-finding-keys / check-thread-ids are review-fix-threads gates (exit 0 pass, "
        "1 fail); failures go to stderr naming entries by position, never echoing a value; "
        "check-thread-ids --repair rewrites triage.json coordinates from the fetch and records "
        "_id_repairs, every other mismatch halts"
    )
    lines.append(
        "  - thread-fingerprints prints JSON [{index, thread_id, database_id, body_fingerprint}]; "
        "the fingerprint is the one tested sha256 every stage must use"
    )
    lines.append(
        "  - aggregate-fix-results credits a result only if its filename, in-file finding_key and "
        "thread_id all match fix-index.json; anything else is a key_mismatch and its finding is "
        "missing. Exit 0 once written, 1 (nothing written) on a bad index"
    )
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
