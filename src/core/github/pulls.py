"""Pull-request porcelain: view, diff, create, edit, ready, checks, list, comment.

Thin over ``gh`` on purpose — gh already implements these correctly. What this
layer adds is the part hand-written invocations kept getting wrong:

* bodies always travel by file or stdin, never interpolated into argv text a
  shell will re-read;
* ``GITHUB_TOKEN`` is scrubbed by the ``client()`` GhCLI;
* list endpoints are paginated;
* an edit is read back, because a ``gh pr edit`` that exits 0 is not proof the
  body GitHub now holds is the one that was sent.
"""

from __future__ import annotations

import json
from typing import Any

from core.gh_cli import GhCLI, GhError

#: Fields ``gh pr checks --json`` accepts that the callers here use.
CHECK_FIELDS = "name,state,bucket,link,workflow,startedAt,completedAt"


def _repo_args(repo: str | None) -> list[str]:
    return ["--repo", repo] if repo else []


def _pr_args(pr: int | str | None) -> list[str]:
    """``[]`` means "the PR for the current branch", which gh resolves itself."""
    return [str(pr)] if pr not in (None, "") else []


def _checked(res: Any, what: str) -> str:
    if res.returncode != 0:
        raise GhError(res.stderr or res.stdout or f"{what} failed")
    return str(res.stdout or "")


def _json(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GhError(f"{what} returned non-JSON output: {exc}") from exc


def pr_view(gh: GhCLI, pr: int | str | None, fields: list[str], *, repo: str | None = None) -> dict[str, Any]:
    """Return the requested ``gh pr view --json`` fields as a dict."""
    if not fields:
        raise GhError("pr view needs at least one field")
    res = gh.run(["pr", "view", *_pr_args(pr), *_repo_args(repo), "--json", ",".join(fields)])
    data = _json(_checked(res, "gh pr view"), "gh pr view")
    if not isinstance(data, dict):
        raise GhError(f"gh pr view returned {type(data).__name__}, expected an object")
    return data


def pr_diff(gh: GhCLI, pr: int | str | None, *, name_only: bool = False, repo: str | None = None) -> str:
    """Return the PR's unified diff, or its changed paths one per line."""
    args = ["pr", "diff", *_pr_args(pr), *_repo_args(repo)]
    if name_only:
        args.append("--name-only")
    return _checked(gh.run(args), "gh pr diff")


def pr_files(gh: GhCLI, pr: int | str | None, *, repo: str | None = None) -> list[str]:
    """Changed paths in the PR."""
    return [line for line in pr_diff(gh, pr, name_only=True, repo=repo).splitlines() if line.strip()]


def pr_create(
    gh: GhCLI,
    *,
    base: str,
    title: str,
    body: str,
    head: str | None = None,
    draft: bool = False,
    repo: str | None = None,
) -> dict[str, Any]:
    """Open a PR; return ``{"number", "url"}`` read back from GitHub.

    The body goes on stdin (``--body-file -``) so no shell ever parses it.
    """
    args = ["pr", "create", "--base", base, "--title", title, "--body-file", "-", *_repo_args(repo)]
    if head:
        args += ["--head", head]
    if draft:
        args.append("--draft")
    url = _checked(gh.run(args, input_text=body), "gh pr create").strip().splitlines()
    if not url:
        raise GhError("gh pr create printed no URL")
    return pr_view(gh, url[-1], ["number", "url"], repo=repo)


def pr_edit(
    gh: GhCLI,
    pr: int | str,
    *,
    title: str | None = None,
    body: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Set the PR title and/or body, then read them back and verify.

    Raises when GitHub does not hold what was sent. Trailing whitespace is
    ignored in the comparison: GitHub strips it.
    """
    if title is None and body is None:
        raise GhError("pr edit needs --title or a body")
    args = ["pr", "edit", str(pr), *_repo_args(repo)]
    if title is not None:
        args += ["--title", title]
    if body is not None:
        args += ["--body-file", "-"]
    _checked(gh.run(args, input_text=body), "gh pr edit")
    got = pr_view(gh, pr, ["title", "body"], repo=repo)
    if title is not None and (got.get("title") or "") != title:
        raise GhError(f"PR #{pr} title did not update")
    if body is not None and (got.get("body") or "").rstrip() != body.rstrip():
        raise GhError(f"PR #{pr} body did not update")
    return got


def pr_ready(gh: GhCLI, pr: int | str, *, repo: str | None = None) -> None:
    """Mark a draft PR ready for review."""
    _checked(gh.run(["pr", "ready", str(pr), *_repo_args(repo)]), "gh pr ready")


def pr_checks(gh: GhCLI, pr: int | str | None, *, repo: str | None = None) -> list[dict[str, Any]]:
    """Return the PR's checks as a list.

    ``gh pr checks`` exits non-zero while checks are pending (8) or failing
    (1) yet still prints valid JSON, so the exit code is not an error signal
    here: an unparseable body is.
    """
    res = gh.run(["pr", "checks", *_pr_args(pr), *_repo_args(repo), "--json", CHECK_FIELDS])
    text = (res.stdout or "").strip()
    if not text:
        if "no checks reported" in (res.stderr or "").lower():
            return []
        raise GhError(res.stderr or "gh pr checks printed nothing")
    data = _json(text, "gh pr checks")
    if not isinstance(data, list):
        raise GhError(f"gh pr checks returned {type(data).__name__}, expected a list")
    return data


def pr_checks_watch(
    gh: GhCLI, pr: int | str | None, *, interval: int = 60, repo: str | None = None,
) -> int:
    """Block until checks finish; return gh's exit code (0 means all passed).

    Exempt from the client timeout: blocking until CI finishes is the point.
    A caller that needs a ceiling wraps it (e.g. ``timeout 1200 ...``).
    """
    res = gh.run(
        ["pr", "checks", *_pr_args(pr), *_repo_args(repo), "--watch", "--interval", str(interval)],
        timeout=None,
    )
    return int(res.returncode)


def pr_list(
    gh: GhCLI,
    *,
    fields: list[str],
    state: str = "open",
    limit: int = 30,
    author: str | None = None,
    head: str | None = None,
    search: str | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """Return ``gh pr list --json`` rows."""
    args = ["pr", "list", "--state", state, "--limit", str(limit), "--json", ",".join(fields), *_repo_args(repo)]
    if author:
        args += ["--author", author]
    if head:
        args += ["--head", head]
    if search:
        args += ["--search", search]
    data = _json(_checked(gh.run(args), "gh pr list"), "gh pr list")
    if not isinstance(data, list):
        raise GhError(f"gh pr list returned {type(data).__name__}, expected a list")
    return data


def pr_comment(gh: GhCLI, pr: int | str, body: str, *, repo: str | None = None) -> str:
    """Post a PR-level comment; return its URL. The body goes on stdin."""
    if not body.strip():
        raise GhError("refusing to post an empty comment")
    res = gh.run(["pr", "comment", str(pr), "--body-file", "-", *_repo_args(repo)], input_text=body)
    return _checked(res, "gh pr comment").strip()


def pr_review_comment(
    gh: GhCLI,
    owner: str,
    repo: str,
    pr: int,
    *,
    path: str,
    line: int,
    body: str,
    side: str = "RIGHT",
    commit_id: str | None = None,
) -> dict[str, str]:
    """Post an inline review comment anchored to ``path:line``; return id and url.

    ``commit_id`` defaults to the PR's head SHA as GitHub reports it — never
    ``git rev-parse HEAD``, which in CI is a synthetic merge commit GitHub
    rejects with HTTP 422. The response is checked for an id, so a comment
    that did not land is an error rather than a silent success.
    """
    if not body.strip():
        raise GhError("refusing to post an empty review comment")
    if int(line) < 1:
        raise GhError(f"line must be a positive integer, got {line!r}")
    if side not in ("RIGHT", "LEFT"):
        raise GhError(f"side must be RIGHT or LEFT, got {side!r}")
    sha = commit_id or pr_view(gh, pr, ["headRefOid"], repo=f"{owner}/{repo}").get("headRefOid")
    if not sha:
        raise GhError(f"could not determine the head SHA of PR #{pr}")
    data = gh.api_post(
        f"repos/{owner}/{repo}/pulls/{int(pr)}/comments",
        {"body": body, "path": path, "line": int(line), "side": side, "commit_id": str(sha)},
    )
    if not data.get("id"):
        raise GhError(f"review comment on {path}:{line} returned no id")
    return {"id": str(data["id"]), "url": str(data.get("html_url") or "")}


def pr_comments(gh: GhCLI, owner: str, repo: str, pr: int, *, kind: str = "review") -> list[Any]:
    """Every inline review comment (``review``) or PR conversation comment (``issue``)."""
    if kind == "review":
        return gh.api_paginated(f"repos/{owner}/{repo}/pulls/{int(pr)}/comments")
    if kind == "issue":
        return gh.api_paginated(f"repos/{owner}/{repo}/issues/{int(pr)}/comments")
    raise GhError(f"unknown comment kind {kind!r}; expected review or issue")


def run_log(gh: GhCLI, run_id: int | str, *, failed_only: bool = True, repo: str | None = None) -> str:
    """Return a workflow run's log, by default only the failed steps."""
    args = ["run", "view", str(run_id), *_repo_args(repo), "--log-failed" if failed_only else "--log"]
    return _checked(gh.run(args), "gh run view")
