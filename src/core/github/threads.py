"""Fetch every review comment on a pull request, from all three surfaces.

GitHub spreads PR review feedback across three APIs, and each call site that
re-derived "get the threads" by hand got a different subset wrong:

1. GraphQL ``reviewThreads`` — inline threads, with resolution state and the
   only id ``resolveReviewThread`` accepts.
2. REST ``pulls/{n}/reviews`` — top-level review bodies. They belong to no
   thread, and Copilot puts its overview there.
3. REST ``issues/{n}/comments`` — PR-level conversation.

Pagination is enforced at every level. A truncated fetch looks identical to a
clean one, and what goes missing is always the tail: the newest reviews, and
the latest comments in a thread, which are the ones carrying a human's
correction or an "already fixed" note.

The output shape is the ``threads.json`` contract documented in
``workflows/shared/pr-review-threads.yaml``; ``core.copilot_overview`` and the
triage stages consume it.
"""

from __future__ import annotations

from typing import Any

from core.gh_cli import GhCLI, GhError

from .authors import classify_author

THREAD_PAGE = 100
COMMENT_PAGE = 50
#: Hard ceiling on pages per connection: a cursor bug must fail, not spin.
MAX_PAGES = 1000

_COMMENT_FIELDS = "databaseId author { login __typename } body createdAt url"

THREADS_QUERY = f"""
query($owner: String!, $name: String!, $pr: Int!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequest(number: $pr) {{
      reviewThreads(first: {THREAD_PAGE}, after: $after) {{
        totalCount
        pageInfo {{ hasNextPage endCursor }}
        nodes {{
          id isResolved isOutdated isCollapsed
          path line startLine diffSide
          comments(first: {COMMENT_PAGE}) {{
            totalCount
            pageInfo {{ hasNextPage endCursor }}
            nodes {{ {_COMMENT_FIELDS} }}
          }}
        }}
      }}
    }}
  }}
}}
"""

THREAD_STATE_QUERY = f"""
query($owner: String!, $name: String!, $pr: Int!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequest(number: $pr) {{
      reviewThreads(first: {THREAD_PAGE}, after: $after) {{
        totalCount
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ id isResolved }}
      }}
    }}
  }}
}}
"""

THREAD_COMMENTS_QUERY = f"""
query($id: ID!, $after: String) {{
  node(id: $id) {{
    ... on PullRequestReviewThread {{
      comments(first: {COMMENT_PAGE}, after: $after) {{
        totalCount
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_COMMENT_FIELDS} }}
      }}
    }}
  }}
}}
"""


def _next_cursor(page_info: Any, previous: str | None, what: str) -> str | None:
    """Return the cursor for the next page, or None when the connection is done.

    Raises when ``hasNextPage`` is true but the cursor is missing or unchanged:
    re-requesting the same page would either loop forever or silently stop
    short, and both read as a complete result.
    """
    if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
        return None
    cursor = page_info.get("endCursor")
    if not cursor or cursor == previous:
        raise GhError(f"{what}: hasNextPage is true but endCursor did not advance ({cursor!r})")
    return str(cursor)


def _dig(data: Any, *keys: str, what: str) -> Any:
    """Walk ``keys`` into ``data``, raising a GhError naming ``what`` on a gap."""
    cur = data
    for key in keys:
        if not isinstance(cur, dict) or cur.get(key) is None:
            raise GhError(f"{what}: response has no {'.'.join(keys)}")
        cur = cur[key]
    return cur


def _page_thread_comments(gh: GhCLI, thread_id: str, after: str | None) -> tuple[list[dict[str, Any]], int | None]:
    """Fetch the comments of one thread starting after ``after``.

    Returns (comment nodes, totalCount). totalCount is None when GitHub's
    response omitted it — callers must not treat that as "reported 0"; a
    missing count on an otherwise-empty page must not read as confirmed empty.
    """
    nodes: list[dict[str, Any]] = []
    total: int | None = None
    cursor = after
    for _ in range(MAX_PAGES):
        data = gh.graphql_checked(THREAD_COMMENTS_QUERY, {"id": thread_id, "after": cursor})
        conn = _dig(data, "node", "comments", what=f"thread {thread_id} comments")
        nodes.extend(conn.get("nodes") or [])
        raw_total = conn.get("totalCount")
        total = int(raw_total) if raw_total is not None else None
        cursor = _next_cursor(conn.get("pageInfo"), cursor, f"thread {thread_id} comments")
        if cursor is None:
            return nodes, total
    raise GhError(f"thread {thread_id} comments: exceeded {MAX_PAGES} pages")


def fetch_thread_comments(gh: GhCLI, thread_id: str) -> list[dict[str, Any]]:
    """Return every comment in one review thread, normalised.

    Used to check idempotency markers before replying: the whole chain, not the
    latest comment, because a reviewer may have replied after our last run.

    Raises when GitHub reports more comments than came back, or omits the
    count entirely. An incomplete chain can hide this run's earlier reply,
    and the caller would then post a duplicate — so a short or unreported
    chain must fail, not read as "no marker".
    """
    nodes, total = _page_thread_comments(gh, thread_id, None)
    if total is None or len(nodes) != total:
        raise GhError(f"thread {thread_id} comments: fetched {len(nodes)} of {total} reported")
    return [_comment(n, thread_id) for n in nodes]


def fetch_raw_threads(gh: GhCLI, owner: str, repo: str, pr: int) -> tuple[list[dict[str, Any]], bool]:
    """Return every GraphQL review-thread node, with every comment inlined.

    Pages the thread connection, then pages each thread's comments beyond the
    first ``COMMENT_PAGE``. Returns (nodes, truncated) where truncated means a
    count GitHub reported did not match what was collected.
    """
    threads: list[dict[str, Any]] = []
    truncated = False
    cursor: str | None = None
    reported_total: int | None = None
    for _ in range(MAX_PAGES):
        data = gh.graphql_checked(
            THREADS_QUERY, {"owner": owner, "name": repo, "pr": int(pr), "after": cursor},
        )
        conn = _dig(data, "repository", "pullRequest", "reviewThreads", what=f"PR #{pr} threads")
        threads.extend(conn.get("nodes") or [])
        raw_total = conn.get("totalCount")
        reported_total = int(raw_total) if raw_total is not None else None
        cursor = _next_cursor(conn.get("pageInfo"), cursor, f"PR #{pr} threads")
        if cursor is None:
            break
    else:
        raise GhError(f"PR #{pr} threads: exceeded {MAX_PAGES} pages")

    if reported_total is None or len(threads) != reported_total:
        truncated = True

    for node in threads:
        comments = node.get("comments") or {}
        nodes = list(comments.get("nodes") or [])
        more = _next_cursor(comments.get("pageInfo"), None, f"thread {node.get('id')} comments")
        if more is not None:
            extra, _ = _page_thread_comments(gh, str(node["id"]), more)
            nodes.extend(extra)
        # A missing totalCount is not "trust the nodes we got" — it is a
        # response GitHub did not fully describe, and must fail closed the
        # same as an explicit count that disagrees with what was collected.
        thread_total = comments.get("totalCount")
        if thread_total is None or len(nodes) != int(thread_total):
            truncated = True
        node["comments"] = {"totalCount": comments.get("totalCount"), "nodes": nodes}
    return threads, truncated


def fetch_thread_states(gh: GhCLI, owner: str, repo: str, pr: int) -> tuple[list[dict[str, Any]], bool]:
    """Return every thread's ``id``/``isResolved``, without fetching any comments.

    Same pagination and truncation contract as ``fetch_raw_threads`` (paginate
    the thread connection, flag ``truncated`` on a count mismatch), but the
    query never requests a thread's comment connection, so there is no
    per-thread comment pagination to perform. Callers that only need
    resolution state — ``threads state``'s post-mutation verification — get an
    O(pages-of-threads) fetch instead of an O(threads) one.
    """
    threads: list[dict[str, Any]] = []
    truncated = False
    cursor: str | None = None
    reported_total: int | None = None
    for _ in range(MAX_PAGES):
        data = gh.graphql_checked(
            THREAD_STATE_QUERY, {"owner": owner, "name": repo, "pr": int(pr), "after": cursor},
        )
        conn = _dig(data, "repository", "pullRequest", "reviewThreads", what=f"PR #{pr} thread states")
        threads.extend(conn.get("nodes") or [])
        raw_total = conn.get("totalCount")
        reported_total = int(raw_total) if raw_total is not None else None
        cursor = _next_cursor(conn.get("pageInfo"), cursor, f"PR #{pr} thread states")
        if cursor is None:
            break
    else:
        raise GhError(f"PR #{pr} thread states: exceeded {MAX_PAGES} pages")

    if reported_total is None or len(threads) != reported_total:
        truncated = True
    return threads, truncated


def _comment(node: dict[str, Any], thread_id: str | None = None) -> dict[str, Any]:
    # The threads.json contract promises every comment a database id, and
    # review-fix-threads matches comments by it; a null id from GraphQL
    # would serialize silently and break that matching downstream, so fail
    # the fetch now, the same as _rest_entry already does for REST items.
    database_id = node.get("databaseId")
    if database_id is None:
        raise GhError(f"thread {thread_id} comment has no databaseId; cannot give it a stable identity")
    author = node.get("author") or {}
    return {
        "author": author.get("login") or "",
        "author_kind": classify_author(author.get("login"), typename=author.get("__typename")),
        "body": node.get("body") or "",
        "created_at": node.get("createdAt"),
        "url": node.get("url"),
        "database_id": database_id,
    }


def _graphql_entry(node: dict[str, Any]) -> dict[str, Any]:
    thread_id = node.get("id")
    comments = [_comment(c, thread_id) for c in (node.get("comments") or {}).get("nodes") or []]
    opening = comments[0] if comments else {}
    latest = comments[-1] if comments else {}
    return {
        "thread_id": node.get("id"),
        "source": "graphql-thread",
        "author_kind": opening.get("author_kind", "human"),
        "author": opening.get("author", ""),
        "is_resolved": bool(node.get("isResolved")),
        "is_outdated": bool(node.get("isOutdated")),
        "path": node.get("path"),
        # GitHub returns line: null for outdated threads. Carry it through;
        # never invent one.
        "line": node.get("line"),
        "comments": comments,
        "opening_body": opening.get("body", ""),
        "latest_author_kind": latest.get("author_kind", "human"),
    }


def _rest_author(item: dict[str, Any]) -> tuple[str, str]:
    user = item.get("user") or {}
    login = user.get("login") or ""
    return login, classify_author(login, user_type=user.get("type"))


def _rest_entry(item: dict[str, Any], source: str) -> dict[str, Any]:
    # A REST entry has no thread_id, so its database_id is its only stable
    # identity: review-fix-threads looks it up by comments[0].database_id and
    # halts when it is missing. Fail the fetch rather than emit one silently.
    if item.get("id") is None:
        raise GhError(f"{source} item has no id; cannot give it a stable identity")
    login, kind = _rest_author(item)
    comment = {
        "author": login,
        "author_kind": kind,
        "body": item.get("body") or "",
        "created_at": item.get("submitted_at") or item.get("created_at"),
        "url": item.get("html_url"),
        "database_id": item.get("id"),
    }
    return {
        # REST items are not review threads: resolveReviewThread cannot act on
        # them, so they carry no thread_id and downstream stages must skip them.
        "thread_id": None,
        "source": source,
        "author_kind": kind,
        "author": login,
        "is_resolved": False,
        "is_outdated": False,
        "path": None,
        "line": None,
        "comments": [comment],
        "opening_body": comment["body"],
        "latest_author_kind": kind,
    }


def _review_body(item: dict[str, Any]) -> dict[str, Any]:
    login, kind = _rest_author(item)
    return {
        "review_id": item.get("id"),
        "author": login,
        "author_kind": kind,
        "state": item.get("state"),
        "submitted_at": item.get("submitted_at"),
        # Verbatim: core.copilot_overview parses this HTML. Never tidy it.
        "body": item.get("body") or "",
    }


def build_threads_doc(
    *,
    owner: str,
    repo: str,
    pr: int,
    raw_threads: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    truncated: bool = False,
) -> dict[str, Any]:
    """Normalise the three sources into the ``threads.json`` document."""
    with_body = [r for r in reviews if (r.get("body") or "").strip()]
    entries = [_graphql_entry(n) for n in raw_threads]
    entries += [_rest_entry(r, "review-body") for r in with_body]
    entries += [_rest_entry(c, "issue-comment") for c in issue_comments]

    resolvable = [e for e in entries if e["thread_id"]]
    counts = {
        "total": len(entries),
        # Resolution state only exists for real threads; REST entries would
        # otherwise inflate "unresolved" with things nobody can resolve.
        "unresolved": sum(1 for e in resolvable if not e["is_resolved"]),
        "resolved": sum(1 for e in resolvable if e["is_resolved"]),
        "outdated": sum(1 for e in resolvable if e["is_outdated"]),
        "bot": sum(1 for e in entries if e["author_kind"] == "bot"),
        "human": sum(1 for e in entries if e["author_kind"] == "human"),
    }
    return {
        "pr_number": str(pr),
        "repo": f"{owner}/{repo}",
        "counts": counts,
        "truncated": truncated,
        "threads": entries,
        "review_bodies": [_review_body(r) for r in with_body],
    }


def fetch_review_threads(gh: GhCLI, owner: str, repo: str, pr: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch and normalise every review comment on ``owner/repo#pr``.

    Returns (threads document, raw responses). The raw half is written to
    ``threads-raw.json`` so a surprising classification can be checked against
    what GitHub actually sent.
    """
    raw_threads, truncated = fetch_raw_threads(gh, owner, repo, pr)
    reviews = gh.api_paginated(f"repos/{owner}/{repo}/pulls/{int(pr)}/reviews")
    issue_comments = gh.api_paginated(f"repos/{owner}/{repo}/issues/{int(pr)}/comments")
    doc = build_threads_doc(
        owner=owner, repo=repo, pr=pr, raw_threads=raw_threads,
        reviews=reviews, issue_comments=issue_comments, truncated=truncated,
    )
    raw = {"review_threads": raw_threads, "reviews": reviews, "issue_comments": issue_comments}
    return doc, raw


def render_summary(doc: dict[str, Any]) -> str:
    """One line per entry: short id, author kind, state, location, opening text."""
    c = doc.get("counts") or {}
    lines = [
        f"# PR #{doc.get('pr_number')} review threads ({doc.get('repo')})",
        "",
        f"total {c.get('total', 0)} · unresolved {c.get('unresolved', 0)} · "
        f"resolved {c.get('resolved', 0)} · outdated {c.get('outdated', 0)} · "
        f"bot {c.get('bot', 0)} · human {c.get('human', 0)}"
        + (" · TRUNCATED" if doc.get("truncated") else ""),
        "",
    ]
    for t in doc.get("threads") or []:
        tid = (t.get("thread_id") or "-")[-8:]
        if not t.get("thread_id"):
            state = t.get("source", "")
        elif t.get("is_resolved"):
            state = "resolved"
        else:
            state = "open"
        if t.get("is_outdated"):
            state += ",outdated"
        loc = t.get("path") or "(PR)"
        if t.get("line") is not None:
            loc = f"{loc}:{t['line']}"
        text = " ".join((t.get("opening_body") or "").split())[:100]
        lines.append(f"- `{tid}` {t.get('author_kind')} {state} {loc} — {text}")
    return "\n".join(lines) + "\n"
