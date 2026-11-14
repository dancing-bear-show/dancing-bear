"""Per-PR change summaries: size, branches, touched files, top directories.

Files are paged through the ``files`` connection and count-checked against
the connection's ``totalCount``: a PR summarised from its first page alone
reports the wrong top directories with nothing to show it was cut short.
"""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from core.gh_cli import GhCLI, GhError

from .threads import MAX_PAGES, dig, next_cursor

FILE_PAGE = 100
PATH_MODES = ("prefix", "glob", "regex")

PR_DETAIL_QUERY = f"""
query($owner: String!, $name: String!, $pr: Int!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequest(number: $pr) {{
      number title state url mergedAt closedAt
      baseRefName headRefName additions deletions changedFiles
      author {{ login }}
      files(first: {FILE_PAGE}, after: $after) {{
        totalCount
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ path additions deletions }}
      }}
    }}
  }}
}}
"""


@dataclass(frozen=True)
class FileChange:
    path: str
    additions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class PRSummary:
    """One PR's change summary; ``to_dict`` is the CLI's JSON row."""

    number: int
    title: str
    state: str
    url: str
    author: str
    base: str
    head: str
    additions: int
    deletions: int
    changed_files: int
    merged_at: str | None = None
    closed_at: str | None = None
    files: list[FileChange] = field(default_factory=list)

    def top_dirs(self, limit: int = 5) -> list[tuple[str, int]]:
        """Most-touched top-level path segments, by file count."""
        counter: Counter[str] = Counter()
        for f in self.files:
            head = f.path.split("/", 1)[0]
            if head:
                counter[head] += 1
        return counter.most_common(limit)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["top_dirs"] = [{"dir": d, "files": n} for d, n in self.top_dirs()]
        return out


def _summary_from(node: dict[str, Any], files: list[FileChange]) -> PRSummary:
    return PRSummary(
        number=int(node.get("number") or 0),
        title=node.get("title") or "",
        state=node.get("state") or "",
        url=node.get("url") or "",
        author=(node.get("author") or {}).get("login") or "",
        base=node.get("baseRefName") or "",
        head=node.get("headRefName") or "",
        additions=int(node.get("additions") or 0),
        deletions=int(node.get("deletions") or 0),
        changed_files=int(node.get("changedFiles") or 0),
        merged_at=node.get("mergedAt"),
        closed_at=node.get("closedAt"),
        files=files,
    )


def fetch_pr_summary(gh: GhCLI, owner: str, repo: str, pr: int) -> PRSummary:
    """Fetch one PR's summary with every changed file; raise if files come back short."""
    files: list[FileChange] = []
    node: dict[str, Any] = {}
    reported: Any = None
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        data = gh.graphql_checked(PR_DETAIL_QUERY, {"owner": owner, "name": repo, "pr": int(pr), "after": cursor})
        node = dig(data, "repository", "pullRequest", what=f"PR #{pr}")
        conn = dig(node, "files", what=f"PR #{pr} files")
        for f in conn.get("nodes") or []:
            files.append(FileChange(
                path=str(f.get("path") or ""),
                additions=int(f.get("additions") or 0),
                deletions=int(f.get("deletions") or 0),
            ))
        reported = conn.get("totalCount")
        cursor = next_cursor(conn.get("pageInfo"), cursor, f"PR #{pr} files")
        if cursor is None:
            break
    else:
        raise GhError(f"PR #{pr} files: exceeded {MAX_PAGES} pages")
    if reported is None or len(files) != int(reported):
        raise GhError(f"PR #{pr} files: fetched {len(files)} of {reported} reported")
    return _summary_from(node, files)


def _path_matches(path: str, pattern: str, mode: str) -> bool:
    if mode == "prefix":
        return path.startswith(pattern)
    if mode == "glob":
        return fnmatch.fnmatchcase(path, pattern)
    if mode == "regex":
        try:
            return re.search(pattern, path) is not None
        except re.error as exc:
            raise GhError(f"invalid path regex {pattern!r}: {exc}") from exc
    raise GhError(f"unknown path mode {mode!r}; expected one of {', '.join(PATH_MODES)}")


def matches_paths(
    paths: Iterable[str], *, include: Iterable[str] = (), exclude: Iterable[str] = (), mode: str = "prefix",
) -> bool:
    """True when any path hits ``include`` (or include is empty) and none hits ``exclude``."""
    paths = list(paths)
    inc, exc = list(include), list(exclude)
    if inc and not any(_path_matches(p, pat, mode) for p in paths for pat in inc):
        return False
    return not any(_path_matches(p, pat, mode) for p in paths for pat in exc)


def render_summary_text(s: PRSummary, *, max_files: int = 10) -> str:
    """Human-readable block for one PR."""
    dirs = ", ".join(f"{d}:{n}" for d, n in s.top_dirs()) or "(none)"
    lines = [
        f"PR #{s.number} - {s.title}",
        f"  state: {s.state} | author: {s.author} | merged: {s.merged_at or '-'} | closed: {s.closed_at or '-'}",
        f"  branch: {s.head} -> {s.base}",
        f"  changes: +{s.additions} / -{s.deletions} across {s.changed_files} files",
        f"  top dirs: {dirs}",
    ]
    lines += [f"    - {f.path} (+{f.additions} / -{f.deletions})" for f in s.files[:max_files]]
    if len(s.files) > max_files:
        lines.append(f"    ... {len(s.files) - max_files} more")
    return "\n".join(lines) + "\n"
