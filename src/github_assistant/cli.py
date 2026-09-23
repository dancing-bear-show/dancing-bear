"""GitHub CLI over ``core.github``.

Handlers are thin: parse args, read body files, call ``core.github``, print
JSON. The interesting invariants (pagination, response verification, run-marker
idempotency) live in ``core.github`` and are tested there; this module tests
the wiring (argv shape, exit codes, body-file routing).

Every subcommand shares:

* ``--repo OWNER/NAME`` — defaults to the current checkout, resolved with
  ``gh repo view`` inside ``core.github.repo.resolve_owner_repo``. The
  exceptions are ``threads comments|reply|resolve``: they address a thread by
  its GraphQL node id, which is global, so they take no ``--repo`` rather than
  accept one they would ignore;
* ``client()`` from ``core.github`` — scrubs ``GITHUB_TOKEN`` so a stale export
  cannot silently override gh's keyring credentials.

Bodies (replies, PR bodies, comments) are always taken from a file path
(``--body-file PATH``, ``-`` for stdin), never from an argv string. That is the
whole point of the CLI: review-derived text never passes through a shell.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.assistant import BaseAssistant
from core.cli_errors import CLIError, ExitCode
from core.cli_framework import CLIApp
from core.github import (
    GhCLI,
    GhError,
    client,
    fetch_review_threads,
    fetch_thread_comments,
    has_run_marker,
    render_summary,
    reply_to_thread,
    resolve_owner_repo,
    resolve_thread,
    run_marker,
)
from core.github import pulls as _pulls
from core.github import threads as _threads_mod

from .meta import META

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "github",
    "GitHub porcelain over core.github",
    add_common_args=False,  # own flag set; --output would collide with --out
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


# ---- helpers ----------------------------------------------------------------


def _print_json(obj: Any) -> None:
    """Emit compact-but-readable JSON. Consumers pipe this into jq."""
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _read_body(path: str) -> str:
    """Read a body file. ``-`` means stdin.

    The whole point of ``--body-file`` is that review-derived text never
    reaches an argv, so this helper deliberately reads the *literal* file
    content: no shell expansion, no stripping of a leading ``@``, no
    interpretation whatsoever.
    """
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_or_print(path: str | None, text: str) -> None:
    """Write to a caller-named path (creating parent dirs) or stdout."""
    if not path:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def _gh() -> GhCLI:
    """Every subcommand uses the token-scrubbed client."""
    return client()


def _repo(args) -> str | None:
    """Common ``--repo`` argument, threaded through unchanged."""
    return getattr(args, "repo", None) or None


# ---- top-level: repo --------------------------------------------------------


@app.command("repo", help="Print owner/name for --repo or the current checkout")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--format", choices=("text", "json"), default="text", help="Output format")
def cmd_repo(args) -> int:
    owner, name = resolve_owner_repo(_gh(), _repo(args))
    if args.format == "json":
        _print_json({"owner": owner, "name": name, "nameWithOwner": f"{owner}/{name}"})
    else:
        print(f"{owner}/{name}")
    return ExitCode.SUCCESS


# ---- threads group ----------------------------------------------------------


threads_group = app.group("threads", help="PR review threads: fetch, reply, resolve, state")


@threads_group.command("fetch", help="Fetch every review thread on a PR (all three surfaces)")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
@app.argument("--out", help="Write threads.json to this path (default: stdout)")
@app.argument("--raw", help="Write the raw response bundle to this path")
@app.argument("--summary", help="Write a Markdown summary to this path")
def cmd_threads_fetch(args) -> int:
    gh = _gh()
    owner, name = resolve_owner_repo(gh, _repo(args))
    doc, raw = fetch_review_threads(gh, owner, name, int(args.pr))
    if args.raw:
        _write_or_print(args.raw, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if args.summary:
        _write_or_print(args.summary, render_summary(doc))
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.out:
        _write_or_print(args.out, text + "\n")
    else:
        print(text)
    return ExitCode.SUCCESS


@threads_group.command("comments", help="List every comment in one review thread")
@app.argument("--thread", required=True, help="Review thread node id")
def cmd_threads_comments(args) -> int:
    comments = fetch_thread_comments(_gh(), args.thread)
    _print_json(comments)
    return ExitCode.SUCCESS


def _try_resolve(gh: GhCLI, thread_id: str) -> tuple[bool, str | None]:
    """Attempt to resolve; return (ok, error_message).

    The reply flow needs to record BOTH the outcome and any error rather than
    raising, because the reply is already public and we still need to emit the
    result JSON before returning the exit code.
    """
    try:
        resolve_thread(gh, thread_id)
    except GhError as exc:
        return False, str(exc)
    return True, None


def _reply_result_exit(resolved_asked: bool, resolved: bool) -> int:
    """Same rule for both the reply-and-resolve and already-replied paths."""
    return ExitCode.ERROR if (resolved_asked and not resolved) else ExitCode.SUCCESS


def _handle_already_replied(
    gh: GhCLI, thread_id: str, resolve_asked: bool,
) -> int:
    """The marker check found the reply already landed on a prior run.

    Do not post a duplicate. When --resolve was asked, still try to resolve
    now: this is exactly the retry-after-a-run-died-between-reply-and-resolve
    case the marker exists for, and skipping the resolve here would leave that
    thread open forever.
    """
    resolved = False
    err: str | None = None
    if resolve_asked:
        resolved, err = _try_resolve(gh, thread_id)
    _print_json({
        "thread_id": thread_id,
        "status": "already_replied",
        "comment_id": None,
        "url": None,
        "resolved": resolved,
        "error": err,
    })
    return _reply_result_exit(resolve_asked, resolved)


def _handle_reply_failure(thread_id: str, exc: GhError) -> int:
    """A failed reply MUST NEVER trigger a resolve.

    The resolve would dismiss the reviewer's concern silently with no
    explanation. Emit the failure JSON and exit non-zero without touching the
    resolve path at all.
    """
    _print_json({
        "thread_id": thread_id,
        "status": "failed",
        "comment_id": None,
        "url": None,
        "resolved": False,
        "error": str(exc),
    })
    return ExitCode.ERROR


def _append_marker(body: str, marker: str) -> str:
    """Marker on its own line, preserving whatever trailing whitespace body had."""
    return f"{body}\n{marker}" if body.endswith("\n") else f"{body}\n\n{marker}"


@threads_group.command("reply", help="Reply into a thread; optionally resolve after verifying")
@app.argument("--thread", required=True, help="Review thread node id")
@app.argument("--body-file", required=True, dest="body_file", help="Body path (- for stdin)")
@app.argument("--run-id", dest="run_id", help="Append a run marker and skip if already present")
@app.argument("--resolve", action="store_true", help="Resolve after a verified reply")
def cmd_threads_reply(args) -> int:
    """Post ``--body-file`` into ``--thread``.

    ``--run-id`` re-fetches the whole chain first: any comment already carrying
    ``<!-- dancing-bear-run: RUN -->`` wins. Nothing is posted; if --resolve
    was asked, we still resolve.

    ``--resolve`` runs *only* after the reply verifiably landed. gh exits 0 on
    a GraphQL ``errors`` payload, so a resolve gated on gh's exit status alone
    would fire even when the reply never made it — dismissing the reviewer's
    concern silently.
    """
    gh = _gh()
    body = _read_body(args.body_file)
    thread_id = str(args.thread)

    if args.run_id:
        # Whole chain, not the latest comment: a reviewer may have replied
        # since our last run, and "is the latest ours?" misses exactly that.
        # A failed re-fetch is a failed reply: posting blind could duplicate.
        try:
            existing = fetch_thread_comments(gh, thread_id)
        except GhError as exc:
            return _handle_reply_failure(thread_id, exc)
        if has_run_marker(existing, args.run_id):
            return _handle_already_replied(gh, thread_id, bool(args.resolve))
        body = _append_marker(body, run_marker(args.run_id))

    try:
        reply = reply_to_thread(gh, thread_id, body)
    except GhError as exc:
        return _handle_reply_failure(thread_id, exc)

    resolved, resolve_error = (False, None)
    if args.resolve:
        resolved, resolve_error = _try_resolve(gh, thread_id)

    _print_json({
        "thread_id": thread_id,
        "status": "replied",
        "comment_id": reply["comment_id"],
        "url": reply.get("url") or "",
        "resolved": resolved,
        "error": resolve_error,
    })
    return _reply_result_exit(bool(args.resolve), resolved)


@threads_group.command("resolve", help="Resolve a thread (no reply)")
@app.argument("--thread", required=True, help="Review thread node id")
def cmd_threads_resolve(args) -> int:
    resolve_thread(_gh(), args.thread)
    _print_json({"thread_id": args.thread, "resolved": True})
    return ExitCode.SUCCESS


@threads_group.command("state", help="Re-fetch resolution state for every thread on a PR")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
def cmd_threads_state(args) -> int:
    gh = _gh()
    owner, name = resolve_owner_repo(gh, _repo(args))
    # A dedicated GraphQL query would be faster, but a re-fetch is the same
    # code path callers already trust and re-uses its verified pagination.
    raw_threads, _ = _threads_mod.fetch_raw_threads(gh, owner, name, int(args.pr))
    total = len(raw_threads)
    unresolved_ids = [str(n["id"]) for n in raw_threads if not n.get("isResolved") and n.get("id")]
    _print_json({
        "total": total,
        "unresolved": len(unresolved_ids),
        "unresolved_ids": unresolved_ids,
    })
    return ExitCode.SUCCESS


# ---- pr group ---------------------------------------------------------------


pr_group = app.group("pr", help="Pull request porcelain: view, diff, create, edit, checks, list")


def _pr_arg(args) -> int | None:
    """``--pr`` is optional across the group: None means "current branch's PR"."""
    pr = getattr(args, "pr", None)
    return int(pr) if pr is not None else None


@pr_group.command("view", help="Read PR fields; --value prints one bare scalar for $(...)")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", type=int, help="PR number (default: current branch's PR)")
@app.argument("--fields", help="Comma-separated JSON fields to return")
@app.argument("--value", help="Return this ONE field as a bare scalar")
def cmd_pr_view(args) -> int:
    if not args.fields and not args.value:
        raise CLIError("pr view needs --fields or --value", ExitCode.USAGE)
    if args.fields and args.value:
        raise CLIError("--fields and --value are mutually exclusive", ExitCode.USAGE)
    gh = _gh()
    if args.value:
        data = _pulls.pr_view(gh, _pr_arg(args), [args.value], repo=_repo(args))
        value = data.get(args.value)
        # Strings and numbers print bare so `$(./bin/github pr view --value X)`
        # yields a usable scalar. Non-scalars (object, list) print as compact
        # JSON on one line -- a workflow that then pipes into `jq .login` needs
        # a valid JSON literal, and Python's repr of a dict is not one.
        if value is None:
            print("")
        elif isinstance(value, (dict, list)):
            print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        else:
            print(value)
        return ExitCode.SUCCESS
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    _print_json(_pulls.pr_view(gh, _pr_arg(args), fields, repo=_repo(args)))
    return ExitCode.SUCCESS


@pr_group.command("diff", help="Print the PR's unified diff, or its changed paths")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", type=int, help="PR number (default: current branch's PR)")
@app.argument("--name-only", action="store_true", dest="name_only", help="One changed path per line")
def cmd_pr_diff(args) -> int:
    if args.name_only:
        # pr_files strips blank lines and returns a clean list, which is what
        # callers piping into xargs actually want; a raw diff --name-only can
        # emit a trailing empty line under some gh versions.
        for path in _pulls.pr_files(_gh(), _pr_arg(args), repo=_repo(args)):
            print(path)
        return ExitCode.SUCCESS
    text = _pulls.pr_diff(_gh(), _pr_arg(args), repo=_repo(args))
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return ExitCode.SUCCESS


@pr_group.command("create", help="Open a PR from a body file; return {number,url}")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--base", required=True, help="Base branch")
@app.argument("--title", required=True, help="PR title")
@app.argument("--body-file", required=True, dest="body_file", help="Body path (- for stdin)")
@app.argument("--head", help="Head branch (default: current)")
@app.argument("--draft", action="store_true", help="Open as draft")
def cmd_pr_create(args) -> int:
    body = _read_body(args.body_file)
    data = _pulls.pr_create(
        _gh(),
        base=args.base,
        title=args.title,
        body=body,
        head=args.head,
        draft=bool(args.draft),
        repo=_repo(args),
    )
    _print_json({"number": data.get("number"), "url": data.get("url")})
    return ExitCode.SUCCESS


@pr_group.command("edit", help="Edit PR title/body; exit 1 if GitHub does not hold what was sent")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
@app.argument("--title", help="New title")
@app.argument("--body-file", dest="body_file", help="Body path (- for stdin)")
def cmd_pr_edit(args) -> int:
    if args.title is None and args.body_file is None:
        raise CLIError("pr edit needs --title or --body-file", ExitCode.USAGE)
    body = _read_body(args.body_file) if args.body_file else None
    got = _pulls.pr_edit(
        _gh(),
        int(args.pr),
        title=args.title,
        body=body,
        repo=_repo(args),
    )
    _print_json(got)
    return ExitCode.SUCCESS


@pr_group.command("ready", help="Mark a draft PR ready for review")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
def cmd_pr_ready(args) -> int:
    _pulls.pr_ready(_gh(), int(args.pr), repo=_repo(args))
    return ExitCode.SUCCESS


@pr_group.command("checks", help="List PR checks; --watch blocks until they finish")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", type=int, help="PR number (default: current branch's PR)")
@app.argument("--watch", action="store_true", help="Block until checks finish; exit code is gh's")
@app.argument("--interval", type=int, default=60, help="--watch poll interval (seconds)")
def cmd_pr_checks(args) -> int:
    if args.watch:
        # Watch mode surfaces gh's own exit code (0 = all passed). Same
        # bucket-vs-exit-code trap as unwatched checks: gh exits nonzero while
        # pending, so the caller must interpret the code — never a stdout body.
        return _pulls.pr_checks_watch(_gh(), _pr_arg(args), interval=int(args.interval), repo=_repo(args))
    _print_json(_pulls.pr_checks(_gh(), _pr_arg(args), repo=_repo(args)))
    return ExitCode.SUCCESS


@pr_group.command("list", help="List PRs matching filters as JSON rows")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--state", choices=("open", "closed", "merged", "all"), default="open")
@app.argument("--limit", type=int, default=30)
@app.argument("--author", help="Filter by author login")
@app.argument("--head", help="Filter by head branch")
@app.argument("--search", help="gh search expression")
@app.argument("--fields", required=True, help="Comma-separated JSON fields to return")
def cmd_pr_list(args) -> int:
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not fields:
        raise CLIError("--fields must name at least one field", ExitCode.USAGE)
    rows = _pulls.pr_list(
        _gh(),
        fields=fields,
        state=args.state,
        limit=int(args.limit),
        author=args.author,
        head=args.head,
        search=args.search,
        repo=_repo(args),
    )
    _print_json(rows)
    return ExitCode.SUCCESS


@pr_group.command("comment", help="Post a PR-level comment from a body file; print its URL")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
@app.argument("--body-file", required=True, dest="body_file", help="Body path (- for stdin)")
def cmd_pr_comment(args) -> int:
    url = _pulls.pr_comment(_gh(), int(args.pr), _read_body(args.body_file), repo=_repo(args))
    print(url)
    return ExitCode.SUCCESS


@pr_group.command("comments", help="List every review or issue comment on a PR")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--pr", required=True, type=int, help="PR number")
@app.argument("--kind", choices=("review", "issue"), default="review",
              help="review = inline pulls/N/comments; issue = issues/N/comments")
def cmd_pr_comments(args) -> int:
    gh = _gh()
    owner, name = resolve_owner_repo(gh, _repo(args))
    _print_json(_pulls.pr_comments(gh, owner, name, int(args.pr), kind=args.kind))
    return ExitCode.SUCCESS


# ---- run group --------------------------------------------------------------


run_group = app.group("run", help="Workflow run helpers")


@run_group.command("log", help="Print a workflow run's failed-step log (or --all)")
@app.argument("--repo", help="OWNER/NAME (defaults to current checkout)")
@app.argument("--run", required=True, help="Workflow run id")
@app.argument("--all", action="store_true", dest="all_steps", help="Print the whole log")
def cmd_run_log(args) -> int:
    text = _pulls.run_log(_gh(), args.run, failed_only=not args.all_steps, repo=_repo(args))
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return ExitCode.SUCCESS


# ---- entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the GitHub CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
