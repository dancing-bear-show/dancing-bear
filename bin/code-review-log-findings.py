#!/usr/bin/env python3
"""Append one NDJSON record per code-review run to the global findings log.

This exists as a script rather than an inline `python3 -c` heredoc in
workflows/shared/code-review-swarm.yaml because the inline form was broken and
failed silently for an unknown period:

1. The snippet lived inside a YAML folded scalar (`description: >`), indented to
   match the surrounding prose. `python3 -c` rejects leading indentation with
   `IndentationError: unexpected indent` on the first import, so an agent that
   copied the block verbatim wrote nothing at all.

2. The stage instruction said to print a warning and continue on failure, the
   log path was absent from `writes_to`, and the stage had no validation block.
   The workflow engine only tracks `writes_to` paths, so a failed write left the
   stage reporting success. The update-review-concerns workflow, which mines this
   log as one of its two data sources, silently ran on one source instead of two.

The log is consumed by workflows/code/update-review-concerns.yaml to mine
recurring defect patterns, so a gap in it degrades that workflow's output
rather than erroring.

Exit 0 on a successful append, 1 on any failure — the caller is expected to
surface a non-zero exit rather than swallow it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_PATH = Path.home() / ".cache" / "claude" / "code-review-findings.ndjson"


def _load(path: Path) -> dict:
    """Read a JSON object, raising a message that names the offending file."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"error: required input not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON: {exc}")


def build_record(pr: dict, cons: dict, post: dict) -> dict:
    """Assemble the NDJSON record from the three upstream stage outputs."""
    by_severity = cons.get("by_severity") or {}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pr_number": pr.get("number") or pr.get("pr_number") or "",
        "repo": pr.get("owner_repo", ""),
        "total": cons.get("total_findings", 0),
        "critical": by_severity.get("critical", 0),
        "major": by_severity.get("major", 0),
        "minor": by_severity.get("minor", 0),
        "posted": post.get("posted", 0),
        "findings": [
            {
                "file": f.get("file"),
                "concern_id": f.get("concern_id"),
                "severity": f.get("severity"),
                "line": f.get("line"),
            }
            for f in cons.get("findings", [])
        ],
        "worktree": os.path.basename(os.getcwd()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, help="workflow workspace dir")
    parser.add_argument(
        "--log-path",
        default=str(DEFAULT_LOG_PATH),
        help=f"NDJSON log to append to (default: {DEFAULT_LOG_PATH})",
    )
    args = parser.parse_args(argv)

    outputs = Path(args.workspace) / "outputs"
    pr = _load(outputs / "pr-context.json")
    cons = _load(outputs / "consolidated.json")

    # post-results.json is absent when the review was discarded at the human
    # gate. The run still happened and is still worth logging, so default the
    # posted count rather than failing.
    post_path = outputs / "post-results.json"
    post = _load(post_path) if post_path.exists() else {"posted": 0}

    record = build_record(pr, cons, post)

    log_path = Path(args.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as fh:
        fh.write(json.dumps(record) + "\n")

    print(
        f"[code-review] logged {record['total']} findings "
        f"for PR #{record['pr_number']} to {log_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
