"""monitor-poll: poll a condition until it resolves or times out.

Subcommands:
  cmd      Poll until a command exits with an expected code
  output   Poll until a command's stdout matches a regex
  file     Poll until a path exists (or is gone)
  http     Poll until a URL returns a status (and optionally a body match)
  gh-pr    Poll until every check on a GitHub PR passes
  gh-run   Poll until a GitHub Actions run succeeds
  status   List active and recent polls
  cancel   SIGTERM a running poll by poll_id or pid

Poll subcommands print one final record: ``{condition, verdict, polls,
elapsed_s, detail, poll_id}``. With ``--ticks`` each evaluation is printed
first as an NDJSON line (flushed), and the final record is the last line.

Exit codes:
  0  condition resolved successfully (verdict passed)
  1  condition failed or the timeout elapsed (verdict failed, timed_out)
  2  condition could not be evaluated (verdict error), or bad usage
  6  cancel: no matching poll
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Callable

from core.assistant import BaseAssistant
from core.cli_errors import CLIError, ExitCode, NotFoundError
from core.cli_framework import CLIApp
from core.cli_output import emit_one, emit_rows
from core.secrets import mask_url

from . import conditions, state
from .engine import Condition, Probe, Verdict, run_poll
from .meta import META

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "monitor-poll",
    "Poll a condition until it resolves or times out",
    add_common_args=False,  # own flag set; --format means something specific here
)

_VERDICT_STATUS = {
    Verdict.PASSED: state.STATUS_DONE,
    Verdict.FAILED: state.STATUS_FAILED,
    Verdict.TIMED_OUT: state.STATUS_TIMEOUT,
    Verdict.ERROR: state.STATUS_ERROR,
}

DEFAULT_TIMEOUT = 300.0
DEFAULT_INTERVAL = 5.0


@lru_cache(maxsize=1)
def _lazy_agentic() -> Callable[[str, bool], int]:
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


# ---- argument types ---------------------------------------------------------


def _non_negative(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {raw!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _positive(raw: str) -> float:
    value = _non_negative(raw)
    if value == 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return value


_POLL_ARGS: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (("--timeout",), {"type": _non_negative, "default": DEFAULT_TIMEOUT,
                      "help": f"Max seconds to wait; 0 = check once (default: {DEFAULT_TIMEOUT:g})"}),
    (("--interval",), {"type": _positive, "default": DEFAULT_INTERVAL,
                       "help": f"Seconds between checks (default: {DEFAULT_INTERVAL:g})"}),
    (("--ticks",), {"action": "store_true", "help": "Print one NDJSON line per check"}),
    (("--format",), {"choices": ("json", "text"), "default": "json", "help": "Output format"}),
)


def _poll_command(name: str, help_text: str) -> Callable[[Callable[..., int]], Callable[..., int]]:
    """Register a poll subcommand carrying the shared --timeout/--interval/... flags."""

    def decorator(func: Callable[..., int]) -> Callable[..., int]:
        app.add_arguments(_POLL_ARGS)
        return app.command(name, help=help_text)(func)

    return decorator


# ---- poll execution ---------------------------------------------------------


@dataclass(frozen=True)
class PollSpec:
    """A configured poll: what to call it, what to record, what to evaluate."""

    name: str
    summary: dict[str, Any]
    condition: Condition


@dataclass(frozen=True)
class PollRecord:
    """The final record printed by every poll subcommand."""

    condition: str
    verdict: str
    polls: int
    elapsed_s: float
    detail: str
    poll_id: str


def _emit(record: dict[str, Any], fmt: str) -> None:
    """Print one record; text mode is ``key=value`` pairs on one line."""
    if fmt == "json":
        print(json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str), flush=True)
    else:
        print(" ".join(f"{k}={v}" for k, v in record.items() if v != ""), flush=True)


def _run_spec(args: argparse.Namespace, spec: PollSpec) -> int:
    fmt: str = args.format

    def on_tick(polls: int, probe: Probe, elapsed: float) -> None:
        if args.ticks:
            _emit({"poll": polls, "outcome": probe.outcome.value,
                   "elapsed_s": round(elapsed, 1), "detail": probe.detail}, fmt)

    with state.tracked_poll(spec.name, spec.summary) as poll_state:
        result = run_poll(spec.condition, timeout=args.timeout, interval=args.interval,
                          on_tick=on_tick)
        poll_state.status = _VERDICT_STATUS[result.verdict]
    record = PollRecord(spec.name, result.verdict.value, result.polls,
                        round(result.elapsed_s, 1), result.detail, poll_state.poll_id)
    _emit(asdict(record), fmt)
    if result.verdict is Verdict.ERROR:
        print(f"error: {result.detail}", file=sys.stderr)
    return result.exit_code


# ---- poll subcommands -------------------------------------------------------


@_poll_command("cmd", "Poll until COMMAND exits with --expect-rc")
@app.argument("--expect-rc", type=int, default=0, help="Exit code that means done (default: 0)")
@app.argument("--attempt-timeout", type=_positive, default=conditions.DEFAULT_ATTEMPT_TIMEOUT,
              help="Per-attempt command timeout, seconds")
@app.argument("argv", nargs=argparse.REMAINDER, help="Command and args (options go before it)")
def cmd_cmd(args: argparse.Namespace) -> int:
    condition = conditions.command_condition(
        args.argv, expect_rc=args.expect_rc, attempt_timeout=args.attempt_timeout)
    summary = {"command": args.argv[0] if args.argv else "", "expect_rc": args.expect_rc}
    return _run_spec(args, PollSpec("cmd", summary, condition))


@_poll_command("output", "Poll until COMMAND stdout matches --match")
@app.argument("--match", required=True, help="Regex that means done (re.search)")
@app.argument("--fail-match", help="Regex that means failed (checked first)")
@app.argument("--attempt-timeout", type=_positive, default=conditions.DEFAULT_ATTEMPT_TIMEOUT,
              help="Per-attempt command timeout, seconds")
@app.argument("argv", nargs=argparse.REMAINDER, help="Command and args (options go before it)")
def cmd_output(args: argparse.Namespace) -> int:
    condition = conditions.output_condition(
        args.argv, args.match, fail_pattern=args.fail_match,
        attempt_timeout=args.attempt_timeout)
    summary = {"command": args.argv[0] if args.argv else "", "match": args.match}
    return _run_spec(args, PollSpec("output", summary, condition))


@_poll_command("file", "Poll until PATH exists (or, with --absent, is gone)")
@app.argument("--absent", action="store_true", help="Wait for the path to disappear")
@app.argument("path", help="File or directory path")
def cmd_file(args: argparse.Namespace) -> int:
    condition = conditions.file_condition(args.path, absent=args.absent)
    summary = {"path": args.path, "absent": args.absent}
    return _run_spec(args, PollSpec("file", summary, condition))


@_poll_command("http", "Poll until GET URL returns --status")
@app.argument("--status", type=int, default=200, help="Expected HTTP status (default: 200)")
@app.argument("--match", help="Regex the response body must also match")
@app.argument("--attempt-timeout", type=_positive, default=10.0,
              help="Per-request timeout, seconds (default: 10)")
@app.argument("url", help="http or https URL")
def cmd_http(args: argparse.Namespace) -> int:
    condition = conditions.http_condition(
        args.url, status=args.status, match=args.match, attempt_timeout=args.attempt_timeout)
    summary = {"url": mask_url(args.url), "status": args.status}
    return _run_spec(args, PollSpec("http", summary, condition))


@_poll_command("gh-pr", "Poll until all checks on a GitHub PR pass")
@app.argument("--pr", type=int, help="PR number (default: current branch's PR)")
@app.argument("--repo", help="OWNER/NAME (default: current checkout)")
def cmd_gh_pr(args: argparse.Namespace) -> int:
    condition = conditions.gh_pr_condition(args.pr, repo=args.repo)
    summary = {"pr": args.pr, "repo": args.repo}
    return _run_spec(args, PollSpec("gh-pr", summary, condition))


@_poll_command("gh-run", "Poll until a GitHub Actions run succeeds")
@app.argument("--run", required=True, dest="run_id", help="Workflow run id")
@app.argument("--repo", help="OWNER/NAME (default: current checkout)")
def cmd_gh_run(args: argparse.Namespace) -> int:
    condition = conditions.gh_run_condition(args.run_id, repo=args.repo)
    summary = {"run": args.run_id, "repo": args.repo}
    return _run_spec(args, PollSpec("gh-run", summary, condition))


# ---- status / cancel --------------------------------------------------------


_STATUS_COLUMNS = ["poll_id", "condition", "pid", "status", "started_at", "args"]


@app.command("status", help="List active and recent polls")
@app.argument("--format", choices=("json", "table", "csv"), default="json", help="Output format")
def cmd_status(args: argparse.Namespace) -> int:
    root = state.state_dir()
    state.prune_stale(root)
    rows: list[dict[str, object]] = []
    for entry in state.load_states(root):
        alive = state.is_pid_alive(entry.pid)
        effective = "stale" if entry.status == state.STATUS_RUNNING and not alive else entry.status
        rows.append({
            "poll_id": entry.poll_id,
            "condition": entry.condition,
            "pid": entry.pid,
            "status": effective,
            "started_at": entry.started_at,
            "args": ", ".join(f"{k}={v}" for k, v in entry.args.items()),
        })
    if not rows and args.format == "json":
        print("[]")
        return int(ExitCode.SUCCESS)
    return emit_rows(rows, args.format, headers=_STATUS_COLUMNS, empty_msg="No polls found.")


@app.command("cancel", help="SIGTERM a running poll by --poll-id or --pid")
@app.argument("--poll-id", help="poll_id from `status`")
@app.argument("--pid", type=int, help="OS process id of the polling process")
def cmd_cancel(args: argparse.Namespace) -> int:
    if bool(args.poll_id) == (args.pid is not None):
        raise CLIError("give exactly one of --poll-id or --pid", ExitCode.USAGE)
    root = state.state_dir()
    entry = state.find_state(state.load_states(root), args.poll_id, args.pid)
    if entry is None:
        raise NotFoundError(f"no poll found for {'poll_id=' + args.poll_id if args.poll_id else f'pid={args.pid}'}")
    reason = state.skip_signal_reason(entry)
    error = None if reason else state.send_sigterm(entry.pid)
    cancelled = reason is None and error is None
    if cancelled:
        entry.status = state.STATUS_CANCELLED
        state.write_state(entry, root)
    detail = reason or error or "SIGTERM sent"
    emit_one({"poll_id": entry.poll_id, "pid": entry.pid, "cancelled": cancelled, "detail": detail},
             "jsonl")
    return int(ExitCode.ERROR) if error else int(ExitCode.SUCCESS)


# ---- entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the monitor-poll CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
