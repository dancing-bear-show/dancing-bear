#!/usr/bin/env python3
"""Reconstruct missing code-review findings-log records from posted PR comments.

The findings log (~/.cache/claude/code-review-findings.ndjson) can lose records
when the write in code-review-swarm Step 5 fails — see
bin/code-review-log-findings.py for the two defects that made that failure
silent. The records are derived data: code-review-swarm consolidates findings,
posts them to the PR as a summary comment, and logs the same set. The comment
survives on GitHub even when the log write failed, so a lost record can be
rebuilt from it.

Scope note: this recovers records for PRs the swarm actually reviewed. A PR the
swarm never ran on has no summary comment and therefore nothing to recover —
that is reported as "no summary comment" rather than treated as an error. When
run against dancing-bear PRs #158-#270 it found zero recoverable records,
because the swarm had not been run on any of them; the log's sparseness there
reflects how often the workflow was invoked, not a failed write.

The posted comment format is fixed by code-review-swarm.yaml Step 2:

    ## Code Review Findings (18 total: 1 critical, 4 major, 13 minor)
    ### Critical
    **`path/to/file.py:85-95`** — `concern-id`
    Finding sentence.

Both the header totals and the per-finding file/line/concern_id are parseable,
so a reconstructed record matches the live-logged shape field for field.

Two fields cannot be recovered and are marked rather than guessed:
  ts       — the comment's created_at is used (close to, but not identical to,
             the original run timestamp)
  posted   — always 1, since a parsed comment is by definition one that posted
  backfilled — added as true, so reconstructed records are distinguishable from
             live ones. Consumers that must not mix the two can filter on it.

Idempotent: PRs already present in the log are skipped unless --force is given.
Dry-run by default; pass --apply to write.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_LOG_PATH = Path.home() / ".cache" / "claude" / "code-review-findings.ndjson"

# "## Code Review Findings (18 total: 1 critical, 4 major, 13 minor)"
HEADER_RE = re.compile(
    r"##\s*Code Review Findings\s*\((?P<total>\d+)\s+total:"
    r"\s*(?P<critical>\d+)\s+critical,"
    r"\s*(?P<major>\d+)\s+major,"
    r"\s*(?P<minor>\d+)\s+minor\)",
)

# "**`path/to/file.py:85-95`** — `concern-id`"   (line may be "85" or "85-95")
FINDING_RE = re.compile(
    r"\*\*`(?P<file>[^`:]+):(?P<line>\d+)(?:-\d+)?`\*\*\s*[—-]\s*`(?P<concern_id>[^`]+)`",
)

SEVERITY_HEADING_RE = re.compile(r"^###\s*(Critical|Major|Minor)\s*$", re.IGNORECASE)


def _gh_json(args: list[str]) -> list | dict:
    """Run a gh command returning JSON, or raise with the stderr attached."""
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh CLI not found on PATH")
    # nosec B603 - fixed argv (no shell), absolute path resolved via which();
    # args are built from CLI flags and PR numbers, never from remote content.
    proc = subprocess.run(  # nosec B603
        [gh, *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "[]")


def parse_comment(body: str) -> dict | None:
    """Extract totals and findings from a swarm summary comment body.

    Returns None when the body is not a code-review summary comment.
    """
    header = HEADER_RE.search(body)
    if not header:
        return None

    findings: list[dict] = []
    severity = None
    for raw in body.splitlines():
        heading = SEVERITY_HEADING_RE.match(raw.strip())
        if heading:
            severity = heading.group(1).lower()
            continue
        match = FINDING_RE.search(raw)
        if match:
            findings.append(
                {
                    "file": match.group("file"),
                    "concern_id": match.group("concern_id"),
                    "severity": severity or "",
                    "line": int(match.group("line")),
                }
            )

    return {
        "total": int(header.group("total")),
        "critical": int(header.group("critical")),
        "major": int(header.group("major")),
        "minor": int(header.group("minor")),
        "findings": findings,
    }


def find_summary_comment(owner_repo: str, pr: int) -> dict | None:
    """Return the swarm summary comment for a PR, checking both comment APIs."""
    for endpoint in (f"repos/{owner_repo}/pulls/{pr}/comments",
                     f"repos/{owner_repo}/issues/{pr}/comments"):
        try:
            comments = _gh_json(["api", endpoint, "--paginate"])
        except RuntimeError:
            continue
        for comment in comments:
            body = comment.get("body") or ""
            if HEADER_RE.search(body):
                return comment
    return None


def build_record(owner_repo: str, pr: int, comment: dict, parsed: dict) -> dict:
    return {
        "ts": comment.get("created_at", ""),
        "pr_number": pr,
        "repo": owner_repo,
        "total": parsed["total"],
        "critical": parsed["critical"],
        "major": parsed["major"],
        "minor": parsed["minor"],
        "posted": 1,
        "findings": parsed["findings"],
        "worktree": "",
        "backfilled": True,
    }


def existing_pr_numbers(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    seen = set()
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            seen.add(str(json.loads(line).get("pr_number")))
        except json.JSONDecodeError:
            continue
    return seen


def scan_prs(owner_repo: str, numbers: list[int], already: set[str]) -> dict:
    """Fetch and parse each PR's summary comment into a record.

    Returns buckets rather than a flat list because the caller reports on each
    separately: a PR with no summary comment is not an error (the swarm may
    never have run on it), and a header/body count mismatch is worth surfacing
    without discarding the record.
    """
    records, skipped, no_comment, mismatched = [], [], [], []
    for pr in numbers:
        if str(pr) in already:
            skipped.append(pr)
            continue
        comment = find_summary_comment(owner_repo, pr)
        parsed = parse_comment(comment.get("body") or "") if comment else None
        if not parsed:
            no_comment.append(pr)
            continue

        record = build_record(owner_repo, pr, comment, parsed)
        records.append(record)

        note = ""
        if len(record["findings"]) != record["total"]:
            # Seen on PR #145: a file-level finding (e.g. file-too-large,
            # anchored at line 1) appears in the posted comment but not in the
            # consolidated set the log recorded. The header total is the
            # authoritative count, so keep it and flag the difference rather
            # than silently reporting a larger number than the original run.
            mismatched.append(pr)
            note = (
                f"  [!] comment lists {len(record['findings'])} findings vs "
                f"header total {record['total']}"
            )
        print(
            f"PR #{pr}: {record['total']} findings "
            f"({record['critical']}c/{record['major']}j/{record['minor']}m), "
            f"{len(record['findings'])} parsed{note}"
        )

    return {
        "records": records,
        "skipped": skipped,
        "no_comment": no_comment,
        "mismatched": mismatched,
    }


def report_scan(scan: dict, preview_limit: int = 15) -> None:
    """Print the scan summary, naming the PRs behind each non-obvious bucket."""
    records, skipped = scan["records"], scan["skipped"]
    no_comment, mismatched = scan["no_comment"], scan["mismatched"]

    print(
        f"\nrecoverable: {len(records)}  already-logged: {len(skipped)}  "
        f"no-summary-comment: {len(no_comment)}"
    )

    def _preview(prs: list[int]) -> str:
        head = ", ".join(f"#{n}" for n in prs[:preview_limit])
        rest = len(prs) - preview_limit
        return head + (f" (+{rest} more)" if rest > 0 else "")

    if no_comment:
        print(f"no summary comment found for: {_preview(no_comment)}")
    if mismatched:
        print(
            f"header/body count differs on {len(mismatched)} PR(s): "
            f"{_preview(mismatched)}  (header total kept; see --help)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/repo (default: current checkout)")
    parser.add_argument("--since-pr", type=int, required=True, help="lowest PR number to scan")
    parser.add_argument("--until-pr", type=int, help="highest PR number to scan")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--apply", action="store_true", help="write records (default: dry run)")
    parser.add_argument("--force", action="store_true", help="re-add PRs already in the log")
    args = parser.parse_args(argv)

    owner_repo = args.repo
    if not owner_repo:
        owner_repo = _gh_json(["repo", "view", "--json", "nameWithOwner"])["nameWithOwner"]

    log_path = Path(args.log_path).expanduser()
    already = set() if args.force else existing_pr_numbers(log_path)

    prs = _gh_json(
        ["pr", "list", "--state", "merged", "--limit", "300", "--json", "number"]
    )
    numbers = sorted(
        p["number"]
        for p in prs
        if p["number"] >= args.since_pr
        and (args.until_pr is None or p["number"] <= args.until_pr)
    )

    scan = scan_prs(owner_repo, numbers, already)
    records = scan["records"]

    report_scan(scan)

    # Exit 1 when a scan that was asked to recover something recovered nothing,
    # so a caller can tell "backfilled N records" from "found nothing to
    # backfill" without parsing stdout. Not an error condition in itself — a
    # PR the swarm never reviewed has nothing to recover — but the caller
    # should have to opt into ignoring it.
    nothing_found = not records and bool(numbers)

    if not args.apply:
        print("\ndry run — pass --apply to append these records")
        return 1 if nothing_found else 0

    if not records:
        print("nothing to write")
        return 1 if nothing_found else 0

    # Append in PR order, then leave the file sorted by ts on the caller's side
    # if they care; the consumer filters by ts window, not file order.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    print(f"\nappended {len(records)} records to {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
