"""Built-in conditions. Each factory returns a zero-argument ``Condition``.

Conditions report PENDING while the thing being awaited has not happened yet,
and raise ``ConditionError`` only when evaluation is impossible (missing
binary, malformed input, ``gh`` failure). Transient trouble, such as a refused
connection, is PENDING: that is the normal state of a service that is starting.

Commands run as an argument vector, never through a shell, and every external
call carries a timeout.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from core.gh_cli import GhCLI, GhError
from core.github import client as gh_client
from core.github import pulls
from core.process import CompletedRun, run_binary
from core.secrets import mask_url

from .engine import Condition, ConditionError, Outcome, Probe

DEFAULT_ATTEMPT_TIMEOUT = 60.0
_MAX_DETAIL = 200
_MAX_BODY_BYTES = 1 << 20
_HTTP_SCHEMES = ("http", "https")

# ``gh pr checks`` bucket values.
_FAIL_BUCKETS = frozenset({"fail", "cancel"})
_PENDING_BUCKET = "pending"

Runner = Callable[..., CompletedRun]


def _clip(text: str) -> str:
    """One-line, length-capped detail string."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _MAX_DETAIL else flat[: _MAX_DETAIL - 3] + "..."


def _compile(pattern: str, option: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConditionError(f"invalid {option} regex: {exc}") from exc


def file_condition(path: str | Path, *, absent: bool = False) -> Condition:
    """Succeed once ``path`` exists (or, with ``absent``, no longer exists)."""
    target = Path(path)

    def check() -> Probe:
        present = target.exists()
        if present != absent:
            return Probe(Outcome.SUCCESS, f"{target} {'absent' if absent else 'exists'}")
        return Probe(Outcome.PENDING, f"{target} {'present' if absent else 'missing'}")

    return check


def _run_attempt(
    argv: Sequence[str], attempt_timeout: float, runner: Runner
) -> CompletedRun | None:
    """Run ``argv`` once; None when the attempt hit its timeout."""
    if not argv:
        raise ConditionError("no command given")
    result = runner(list(argv), timeout=attempt_timeout, errors="replace")
    if result.not_found:
        raise ConditionError(f"cannot execute {argv[0]}: {result.exec_error}")
    return None if result.timed_out else result


def command_condition(
    argv: Sequence[str],
    *,
    expect_rc: int = 0,
    attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
    runner: Runner = run_binary,
) -> Condition:
    """Succeed when the command exits with ``expect_rc``."""

    def check() -> Probe:
        result = _run_attempt(argv, attempt_timeout, runner)
        if result is None:
            return Probe(Outcome.PENDING, f"attempt timed out after {attempt_timeout:g}s")
        if result.returncode == expect_rc:
            return Probe(Outcome.SUCCESS, f"exit {result.returncode}")
        return Probe(Outcome.PENDING, f"exit {result.returncode}")

    return check


def output_condition(
    argv: Sequence[str],
    pattern: str,
    *,
    fail_pattern: str | None = None,
    attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
    runner: Runner = run_binary,
) -> Condition:
    """Succeed when the command's stdout matches ``pattern``.

    A match of ``fail_pattern`` (checked first) ends the poll as a failure,
    so a job that reports ``FAILED`` is not waited on until the timeout.
    """
    want = _compile(pattern, "--match")
    bad = _compile(fail_pattern, "--fail-match") if fail_pattern else None

    def check() -> Probe:
        result = _run_attempt(argv, attempt_timeout, runner)
        if result is None:
            return Probe(Outcome.PENDING, f"attempt timed out after {attempt_timeout:g}s")
        if bad is not None and (hit := bad.search(result.stdout)):
            return Probe(Outcome.FAILURE, f"fail pattern matched: {_clip(hit.group(0))}")
        if hit := want.search(result.stdout):
            return Probe(Outcome.SUCCESS, f"matched: {_clip(hit.group(0))}")
        return Probe(Outcome.PENDING, "no match")

    return check


def _fetch(url: str, timeout: float, opener: Callable[..., Any]) -> tuple[int, bytes]:
    """GET ``url``; return (status, body). Non-2xx statuses are results, not errors."""
    request = urllib.request.Request(url, headers={"User-Agent": "monitor-poll"})
    try:
        with opener(request, timeout=timeout) as resp:  # nosec B310 - callers restrict the scheme to http/https
            return int(resp.status), resp.read(_MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(_MAX_BODY_BYTES)


def http_condition(
    url: str,
    *,
    status: int = 200,
    match: str | None = None,
    attempt_timeout: float = 10.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Condition:
    """Succeed when GET ``url`` returns ``status`` (and the body matches ``match``).

    Only http and https URLs are accepted. Connection failures and timeouts
    are PENDING: the endpoint is expected to come up.
    """
    scheme = url.split(":", 1)[0].lower()
    if scheme not in _HTTP_SCHEMES:
        raise ConditionError(f"unsupported URL scheme {scheme!r}; use http or https")
    body_re = _compile(match, "--match") if match else None

    def check() -> Probe:
        try:
            code, body = _fetch(url, attempt_timeout, opener)
        except http.client.InvalidURL as exc:
            raise ConditionError(f"invalid URL {mask_url(url)!r}: {exc}") from exc
        except (http.client.HTTPException, OSError) as exc:  # URLError and timeouts are OSErrors
            # str(exc) for URLError/HTTPException contains the error reason, not the original URL.
            return Probe(Outcome.PENDING, f"unreachable: {_clip(str(exc))}")
        except ValueError as exc:
            raise ConditionError(f"invalid URL {mask_url(url)!r}: {exc}") from exc
        if code != status:
            return Probe(Outcome.PENDING, f"HTTP {code}")
        if body_re is not None and not body_re.search(body.decode("utf-8", "replace")):
            return Probe(Outcome.PENDING, f"HTTP {code}, body does not match")
        return Probe(Outcome.SUCCESS, f"HTTP {code}")

    return check


def gh_pr_condition(
    pr: int | str | None, *, repo: str | None = None, gh: GhCLI | None = None
) -> Condition:
    """Succeed when every check on the PR passed; fail on the first failed one.

    ``pr`` of None means the PR of the current branch (gh's default).
    """
    runner = gh or gh_client()

    def check() -> Probe:
        try:
            checks = pulls.pr_checks(runner, pr, repo=repo)
        except GhError as exc:
            raise ConditionError(f"gh pr checks failed: {_clip(str(exc))}") from exc
        if not checks:
            return Probe(Outcome.PENDING, "no checks reported yet")
        failed = [str(c.get("name", "?")) for c in checks if c.get("bucket") in _FAIL_BUCKETS]
        if failed:
            return Probe(Outcome.FAILURE, f"failed: {_clip(', '.join(failed))}")
        pending = sum(1 for c in checks if c.get("bucket") == _PENDING_BUCKET)
        if pending:
            return Probe(Outcome.PENDING, f"{pending}/{len(checks)} checks pending")
        return Probe(Outcome.SUCCESS, f"{len(checks)} checks passed")

    return check


def _run_payload(res: Any) -> dict[str, Any]:
    """Parse ``gh run view --json`` output; ConditionError when unusable."""
    if res.returncode != 0:
        raise ConditionError(f"gh run view failed: {_clip(res.stderr or res.stdout or '')}")
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ConditionError(f"gh run view returned non-JSON output: {exc}") from exc
    if not isinstance(data, dict):
        raise ConditionError("gh run view returned an unexpected payload")
    return data


def gh_run_condition(
    run_id: int | str, *, repo: str | None = None, gh: GhCLI | None = None
) -> Condition:
    """Succeed when the workflow run completed with conclusion ``success``."""
    runner = gh or gh_client()
    argv = ["run", "view", str(run_id), "--json", "status,conclusion"]
    if repo:
        argv += ["--repo", repo]

    def check() -> Probe:
        try:
            data = _run_payload(runner.run(argv))
        except GhError as exc:
            raise ConditionError(_clip(str(exc))) from exc
        status = str(data.get("status") or "unknown")
        if status != "completed":
            return Probe(Outcome.PENDING, f"run {status}")
        conclusion = str(data.get("conclusion") or "unknown")
        outcome = Outcome.SUCCESS if conclusion == "success" else Outcome.FAILURE
        return Probe(outcome, f"run {conclusion}")

    return check
