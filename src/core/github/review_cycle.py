"""One Copilot review round-trip: reply to and resolve its threads, then re-request.

Sequence:

1. Fetch every review thread (paginated, count-checked) and select the
   unresolved ones Copilot opened.
2. Reply to each with the caller's body, then resolve it — per thread, and only
   after that thread's reply verifiably landed.
3. Request a fresh Copilot review, only when every thread above succeeded.

Human-opened threads are never touched. Resolving a thread without its reply
is a silent closure, so a thread whose reply failed stays open, and any failure
skips the re-review: a new review over unresolved feedback breaks the round
trip.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.gh_cli import GhCLI, GhError

from .copilot import copilot_review_switch, copilot_threads, request_copilot_review
from .mutations import has_run_marker, mark_body, reply_to_thread, resolve_thread, viewer_login
from .threads import fetch_review_threads

SKIP_ERRORS = "errors present"
SKIP_DISABLED = "copilot review disabled"
SKIP_NOT_ASKED = "not requested"
SKIP_REQUEST_FAILED = "request failed"


@dataclass
class ThreadOutcome:
    """What happened to one Copilot thread."""

    thread_id: str
    path: str | None
    line: int | None
    status: str  # replied | already_replied | would_reply | failed
    resolved: bool = False
    error: str | None = None


@dataclass
class ReviewCycleResult:
    """Outcome of ``run_review_cycle``; ``to_dict`` is the CLI's JSON."""

    pr: int
    dry_run: bool
    threads: list[ThreadOutcome] = field(default_factory=list)
    re_review_requested: bool = False
    #: Why no re-review was requested; None when it was.
    re_review_skip_reason: str | None = None
    request_error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        errs = [f"{t.thread_id}: {t.error}" for t in self.threads if t.error]
        if self.request_error:
            errs.append(f"re-review: {self.request_error}")
        return errs

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["replied"] = sum(1 for t in self.threads if t.status == "replied")
        out["resolved"] = sum(1 for t in self.threads if t.resolved)
        out["errors"] = self.errors
        return out


def _outcome(entry: dict[str, Any], status: str) -> ThreadOutcome:
    return ThreadOutcome(
        thread_id=str(entry["thread_id"]),
        path=entry.get("path"),
        line=entry.get("line"),
        status=status,
    )


def _already_replied(entry: dict[str, Any], run_id: str | None, actor: str | None) -> bool:
    return bool(run_id and actor and has_run_marker(entry.get("comments") or [], run_id, actor=actor))


def _settle_thread(
    gh: GhCLI, entry: dict[str, Any], body: str, run_id: str | None, actor: str | None,
) -> ThreadOutcome:
    """Reply (unless this run already did), then resolve after a verified reply."""
    tid = str(entry["thread_id"])
    if _already_replied(entry, run_id, actor):
        out = _outcome(entry, "already_replied")
    else:
        try:
            reply_to_thread(gh, tid, body)
        except GhError as exc:
            out = _outcome(entry, "failed")
            out.error = str(exc)
            return out
        out = _outcome(entry, "replied")
    try:
        resolve_thread(gh, tid)
        out.resolved = True
    except GhError as exc:
        out.error = str(exc)
    return out


@dataclass(frozen=True)
class CycleOptions:
    """Caller choices for ``run_review_cycle``.

    ``body`` is posted to each thread, with ``run_id``'s marker appended when
    given so a retry skips threads this run already answered. ``request=False``
    skips the re-review; ``dry_run`` does the reads and posts nothing.
    """

    body: str
    run_id: str | None = None
    request: bool = True
    dry_run: bool = False


def _maybe_request(gh: GhCLI, owner: str, repo: str, result: ReviewCycleResult, request: bool) -> None:
    if not request:
        result.re_review_skip_reason = SKIP_NOT_ASKED
        return
    if result.errors:
        result.re_review_skip_reason = SKIP_ERRORS
        return
    switch = copilot_review_switch()
    if switch.warning:
        result.warnings.append(switch.warning)
    if not switch.enabled:
        result.re_review_skip_reason = SKIP_DISABLED
        return
    if result.dry_run:
        result.re_review_requested = True
        return
    try:
        request_copilot_review(gh, owner, repo, result.pr)
    except GhError as exc:
        result.re_review_skip_reason = SKIP_REQUEST_FAILED
        result.request_error = str(exc)
        return
    result.re_review_requested = True


def run_review_cycle(gh: GhCLI, owner: str, repo: str, pr: int, opts: CycleOptions) -> ReviewCycleResult:
    """Reply to and resolve every unresolved Copilot thread, then re-request review.

    Raises ``GhError`` only before any mutation (empty body, incomplete thread
    fetch, unknown actor); later failures are recorded in the result.
    """
    marked = mark_body(opts.body, opts.run_id)
    doc, _raw = fetch_review_threads(gh, owner, repo, int(pr))
    selected = copilot_threads(doc)
    result = ReviewCycleResult(pr=int(pr), dry_run=opts.dry_run)
    actor = viewer_login(gh) if opts.run_id else None
    for entry in selected:
        if opts.dry_run:
            status = "already_replied" if _already_replied(entry, opts.run_id, actor) else "would_reply"
            result.threads.append(_outcome(entry, status))
        else:
            result.threads.append(_settle_thread(gh, entry, marked, opts.run_id, actor))
    _maybe_request(gh, owner, repo, result, opts.request)
    return result
