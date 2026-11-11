"""Agentic capsule builders for the monitor-poll CLI."""

from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    tree_and_flow_sections as _tree_and_flow_sections,
)

from .meta import META


def _load_parser():
    # Import inside the function so a broken parser cannot poison module import;
    # cached_parser_loader turns that into a swallowed None the shared contract
    # tests catch by asserting the capsule is substantial (>= 200B).
    from .cli import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def build_agentic_capsule() -> str:
    commands = [
        "wait for a file: ./bin/monitor-poll file /tmp/ready --timeout 60",
        "wait for a command: ./bin/monitor-poll cmd --timeout 120 --interval 5 nc -z localhost 5432",
        "wait for output: ./bin/monitor-poll output --match 'READY' --fail-match 'FAILED' ./status.sh",
        "wait for a URL: ./bin/monitor-poll http http://localhost:8080/health --status 200",
        "wait for PR checks: ./bin/monitor-poll gh-pr --pr 123 --timeout 900 --interval 30",
        "wait for a run: ./bin/monitor-poll gh-run --run 1234567 --timeout 900",
        "list polls: ./bin/monitor-poll status",
        "cancel a poll: ./bin/monitor-poll cancel --poll-id ID",
    ]
    notes_body = "\n".join(
        [
            "- One blocking call replaces repeated status turns. Exit 0 = passed, 1 = failed",
            "  or timed out, 2 = condition could not be evaluated (bad input, gh/tool missing).",
            "- Stdout is one JSON record: condition, verdict (passed|failed|timed_out|error),",
            "  polls, elapsed_s, detail, poll_id. --ticks prints an NDJSON line per check first.",
            "- cmd/output take the command as an argument vector (no shell). Put options before",
            "  the command; everything after it belongs to the command. Wrap in `sh -c` yourself",
            "  if you need pipes.",
            "- Connection failures and per-attempt timeouts are retried until --timeout.",
            "- --timeout 0 checks once. --interval must be > 0.",
        ]
    )
    return _build_capsule(
        META.app_id,
        META.purpose,
        commands,
        [("Notes", notes_body)] + _tree_and_flow_sections(_cli_tree(), None),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n"
        "- bin/monitor-poll — CLI wrapper (routed through _router.py)\n"
        "- monitor_poll/cli.py — CLIApp commands (cmd, output, file, http, gh-pr, gh-run, status, cancel)\n"
        "- monitor_poll/engine.py — poll loop with injectable clock/sleep; Verdict -> exit code\n"
        "- monitor_poll/conditions.py — condition factories (argv-only subprocess, urllib, core.github)\n"
        "- monitor_poll/state.py — per-poll state files under the data home (status/cancel)",
        _cli_tree(),
        None,
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
