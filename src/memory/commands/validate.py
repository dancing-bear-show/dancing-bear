"""CLI subcommand: offline validation of memory stores.

Exit-code mapping (load-bearing — CI and hook consumers rely on exact values):
  0  no findings at all (clean)
  1  only warn/info-severity findings
  2  any error-severity finding present
"""

from __future__ import annotations

import argparse

from core.cli_output import emit_rows
from memory.commands._common import STORE_ARG, ArgSpec, format_arg, validation_error
from memory.discovery import discover_stores, load_store
from memory.validation import CHECK_REGISTRY, CheckResult, run_checks

_VALIDATE_HEADERS = ["check_id", "severity", "target", "message", "fixable"]


def _exit_code_from_findings(findings: list[CheckResult]) -> int:
    """Compute the load-bearing exit code from the finding list.

    Returns 0 (clean), 1 (warn/info only), or 2 (any error).
    """
    if not findings:
        return 0
    if any(f.severity == "error" for f in findings):
        return 2
    return 1


def _findings_to_rows(findings: list[CheckResult]) -> list[dict[str, str]]:
    return [
        {
            "check_id": f.check_id,
            "severity": f.severity,
            "target": f.target,
            "message": f.message,
            "fixable": str(f.fixable),
        }
        for f in findings
    ]


ARGUMENTS: list[ArgSpec] = [
    STORE_ARG,
    (("--check",), {"action": "append", "dest": "checks", "metavar": "ID", "choices": sorted(CHECK_REGISTRY), "help": "Check ID to run (repeatable; default: all offline checks)"}),
    format_arg(["json", "table"], "json"),
    (("--fix",), {"action": "store_true", "help": "Repair fixable findings (.bak backups first)"}),
    (("--claude-md",), {"action": "append", "dest": "claude_md_paths", "default": [], "help": "Extra CLAUDE.md path for overlap checks (repeatable)"}),
    (("--repo",), {"default": None, "help": "Repo root for path/CLI reference checks"}),
]


def run(args: argparse.Namespace) -> int:
    """Validate memory stores against the offline check catalog.

    Exit codes (load-bearing):
      0 — clean run, no findings
      1 — only warn/info-severity findings
      2 — any error-severity finding exists
    """
    # Validate check IDs upfront against the registry
    if args.checks:
        unknown = set(args.checks) - set(CHECK_REGISTRY.keys())
        if unknown:
            return validation_error("--check", f"unknown check ID(s): {', '.join(sorted(unknown))}")

    # Load stores
    if args.store:
        try:
            stores = [load_store(args.store)]
        except Exception as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback
            return validation_error("--store", str(exc))
    else:
        stores = list(discover_stores())

    all_findings: list[CheckResult] = []
    for store in stores:
        findings = run_checks(
            store,
            checks=tuple(args.checks) if args.checks else None,
            fix=args.fix,
            repo=args.repo,
            claude_md=tuple(args.claude_md_paths) if args.claude_md_paths else (),
        )
        all_findings.extend(findings)

    rows = _findings_to_rows(all_findings)
    emit_rows(
        rows,
        args.format,
        headers=_VALIDATE_HEADERS,
        empty_msg="No findings — all checks passed.",
        structured_empty=True,
    )

    return _exit_code_from_findings(all_findings)
