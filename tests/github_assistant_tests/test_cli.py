"""End-to-end CLI wiring for ``./bin/github``.

Every test patches ``core.github.client`` (which cli.py's ``_gh()`` calls) to
return a ``GhCLI`` built on a recording fake run function. Then it drives
``github_assistant.cli.main`` with real argv and asserts on:

* the exact ``gh`` argv it produced (so bodies never leak to ``-F``, and no
  resolve mutation fires when a reply reported failure);
* stdout / exit code (the caller-visible surface).

Contract tests (``tests/agentic_cli_contract.py``,
``tests/cli_separator_contract.py``, ``tests/cli_no_subcommand_contract.py``)
cover the ``--agentic`` surface, ``--`` separator behaviour, and the bare-
invocation contract; they live in ``test_agentic.py`` and ``test_contracts.py``
in this directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.gh_cli import GhCLI


# ---------------------------------------------------------------------------
# Fake gh runner
# ---------------------------------------------------------------------------


@dataclass
class RecordedCall:
    """One gh subprocess invocation captured by the fake runner.

    ``argv`` is the full command list (starts with 'gh'). ``input_text`` is
    the raw stdin payload — a body-file's contents for a REST POST/PATCH, or
    the ``{"query": ..., "variables": {...}}`` JSON for a GraphQL call. A
    passing test asserts on both, because "reply body arrived at gh" is not
    the same claim as "reply body arrived off the process argv".

    ``query_text`` is the GraphQL query string, pulled out of the stdin JSON
    for a ``gh api graphql --input -`` call. Assertions about which mutation
    ran use this field instead of scanning argv, since the query (and every
    variable, including a reply body) never appears there.
    """

    argv: list[str]
    input_text: str | None
    query_text: str
    returncode: int
    stdout: str
    stderr: str

    def all_text(self) -> str:
        """Everything a keyword match should see: argv + captured query body."""
        return "\n".join([*self.argv, self.query_text])


def _query_text_of(cmd: list[str], kwargs: dict[str, Any]) -> str:
    """Read the GraphQL query out of a ``gh api graphql --input -`` call's stdin JSON."""
    if cmd[:3] != ["gh", "api", "graphql"] or "--input" not in cmd:
        return ""
    try:
        payload = json.loads(kwargs.get("input") or "{}")
    except json.JSONDecodeError:
        return ""
    return str(payload.get("query", ""))


def graphql_variables_of(cmd: list[str], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Read the GraphQL variables dict out of a ``gh api graphql --input -`` call's stdin JSON."""
    if cmd[:3] != ["gh", "api", "graphql"] or "--input" not in cmd:
        return {}
    try:
        payload = json.loads(kwargs.get("input") or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(payload.get("variables") or {})


@dataclass
class FakeGhRunner:
    """Records every gh invocation and replays a scripted response for each.

    Responses are matched by an ``all-of`` list of substrings that must appear
    in the call's *text*, where text is the joined argv plus any GraphQL query
    body pulled in from a ``query=@tempfile`` reference. First registered match
    wins. A missing match raises: a silent success would look identical to a
    correctly stubbed call, which is exactly the bug this fake exists to catch.
    """

    responses: list[tuple[list[str], SimpleNamespace]] = field(default_factory=list)
    calls: list[RecordedCall] = field(default_factory=list)

    def add(self, keywords: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((keywords, SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr,
        )))

    def __call__(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        query_text = _query_text_of(cmd, kwargs)
        text = "\n".join([*cmd, query_text])
        for keywords, resp in self.responses:
            if all(kw in text for kw in keywords):
                self.calls.append(RecordedCall(
                    argv=list(cmd),
                    input_text=kwargs.get("input"),
                    query_text=query_text,
                    returncode=resp.returncode,
                    stdout=resp.stdout,
                    stderr=resp.stderr,
                ))
                return resp
        raise AssertionError(f"no fake response registered for gh call: {cmd!r}")


def _install_client(fake: FakeGhRunner):
    """Patch ``client()`` where cli.py imported it, so every _gh() call uses ours."""
    gh = GhCLI(run_func=fake, scrub_github_token=False)
    return patch("github_assistant.cli.client", return_value=gh)


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main(argv) and capture (rc, stdout, stderr)."""
    from github_assistant import cli as cli_module

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli_module.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# repo
# ---------------------------------------------------------------------------


class TestRepo(unittest.TestCase):
    def test_repo_text(self):
        fake = FakeGhRunner()
        fake.add(["repo", "view"], stdout="acme/widgets\n")
        with _install_client(fake):
            rc, out, _ = _run_cli(["repo"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "acme/widgets")

    def test_repo_explicit_and_json(self):
        # An explicit --repo avoids the gh call entirely.
        fake = FakeGhRunner()
        with _install_client(fake):
            rc, out, _ = _run_cli(["repo", "--repo", "acme/widgets", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {
            "owner": "acme", "name": "widgets", "nameWithOwner": "acme/widgets",
        })
        self.assertEqual(fake.calls, [])


# ---------------------------------------------------------------------------
# threads reply — the load-bearing invariants
# ---------------------------------------------------------------------------


#: The account gh is authenticated as in these tests. A run marker counts as
#: prior work only when this account wrote it.
ACTOR = "dancing-bot"


def _viewer_response(login: str = ACTOR) -> SimpleNamespace:
    payload = {"data": {"viewer": {"login": login}}}
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def _thread_chain_response(comments: list[str | tuple[str, str]]) -> SimpleNamespace:
    """Shape the graphql thread-comments query returns.

    Each entry is a body (authored by a reviewer, "someone") or an
    ``(author, body)`` pair.
    """
    pairs = [c if isinstance(c, tuple) else ("someone", c) for c in comments]
    data = {
        "data": {
            "node": {
                "comments": {
                    "totalCount": len(pairs),
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {"databaseId": i, "author": {"login": a, "__typename": "User"},
                         "body": b, "createdAt": "2026-01-01T00:00:00Z", "url": "https://x/y"}
                        for i, (a, b) in enumerate(pairs)
                    ],
                }
            }
        }
    }
    return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="")


def _posted_body(fake) -> str:
    """The body string the reply mutation sent, via its stdin JSON variables."""
    call = next(c for c in fake.calls if "addPullRequestReviewThreadReply" in c.all_text())
    payload = json.loads(call.input_text or "{}")
    return str((payload.get("variables") or {})["body"])


def _reply_success_response(comment_id: str = "IC_kwABC", url: str = "https://x/c/1") -> SimpleNamespace:
    payload = {"data": {"addPullRequestReviewThreadReply": {"comment": {"id": comment_id, "url": url}}}}
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def _resolve_success_response(thread_id: str = "PRT_kwABC") -> SimpleNamespace:
    payload = {"data": {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}}
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


class TestThreadsReplyBodyFilePassthrough(unittest.TestCase):
    """The reply body must never touch gh's process argv, even for ``@/…`` text.

    ``graphql_checked`` sends the GraphQL request body — query and variables,
    including ``body`` — as JSON on stdin (``gh api graphql --input -``), not
    through ``-f``/``-F`` field flags. A value starting ``@/path`` fed through
    ``-F`` would be read as a local file and its contents posted; stdin JSON
    has no such special-casing at all, so this test pins that the body
    reaches gh only via stdin and appears in no argv token whatsoever.
    """

    def test_body_file_with_at_path_travels_on_stdin_never_in_argv(self):
        # A body that a `-F` reader would treat as a file path, plus a shell
        # command-substitution snippet -- both are the traps this test exists
        # to pin: neither hazard exists once the body travels as JSON on
        # stdin instead of a gh argv token.
        body = "@/etc/passwd $(x)"
        # Fake the reply mutation returning a valid comment. Only one gh call
        # is expected (the reply), and it must not be a resolve.
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text(body, encoding="utf-8")
            with _install_client(fake):
                rc, _out, _err = _run_cli([
                    "threads", "reply",
                    "--thread", "PRT_kwABC",
                    "--body-file", str(body_path),
                ])

        self.assertEqual(rc, 0, _err)
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        # Body reaches gh via stdin JSON variables, verbatim ...
        variables = graphql_variables_of(call.argv, {"input": call.input_text})
        self.assertEqual(variables.get("body"), body)
        # ... and appears nowhere in argv, under any flag or token.
        self.assertFalse(
            any(body in tok or "@/etc/passwd" in tok or "$(x)" in tok for tok in call.argv),
            f"body must never appear in argv: got {call.argv!r}",
        )


class TestThreadsReplyErrorsPayloadBlocksResolve(unittest.TestCase):
    """gh exits 0 on an HTTP 200 with a GraphQL ``errors`` array.

    The reply must be reported as failed and no resolve mutation may fire.
    """

    def test_reply_failure_does_not_call_resolve(self):
        # Payload the spec asks us to handle: HTTP 200, returncode 0, but the
        # response includes a GraphQL errors array. GhCLI.graphql_checked
        # raises GhError on this, which our handler must translate into
        # status: failed, exit 1, and MUST NOT proceed to resolve.
        failure = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "data": {"addPullRequestReviewThreadReply": {"comment": None}},
                "errors": [{"message": "x"}],
            }),
            stderr="",
        )
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **failure.__dict__)
        # A resolve response is registered for completeness, but the assertion
        # is that it is never called; a spurious call would still succeed and
        # a weaker assertion would miss it.
        fake.add(["resolveReviewThread"], **_resolve_success_response().__dict__)

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("please look again", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply",
                    "--thread", "PRT_kwABC",
                    "--body-file", str(body_path),
                    "--resolve",
                ])

        self.assertEqual(rc, 1, "reply failure must exit 1")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["resolved"])

        # Prove teeth: NO resolveReviewThread was called. Mutation name lives
        # in the GraphQL tempfile, so match on the call's captured all_text().
        for call in fake.calls:
            self.assertNotIn(
                "resolveReviewThread", call.all_text(),
                f"resolve mutation must not fire on failed reply: {call.argv!r}",
            )


class TestThreadsReplyIdempotencyMarker(unittest.TestCase):
    """A run marker already in the chain must short-circuit; nothing is posted."""

    def test_already_replied_posts_nothing(self):
        # Chain already carries the marker for run R.
        fake = FakeGhRunner()
        chain = _thread_chain_response([
            "old comment",
            (ACTOR, "<!-- dancing-bear-run: R -->\nreply from a prior run"),
        ])
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(["node"], **chain.__dict__)
        # If the code errantly proceeds to post, this stub would be picked up.
        # But it should NOT be called; we assert on that.
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("should not be posted", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply",
                    "--thread", "PRT_kwABC",
                    "--body-file", str(body_path),
                    "--run-id", "R",
                ])

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "already_replied")
        self.assertIsNone(payload["comment_id"])
        # Prove teeth: NO reply mutation was called. Mutation name lives in
        # the GraphQL tempfile, so match on the call's captured all_text().
        for call in fake.calls:
            self.assertNotIn(
                "addPullRequestReviewThreadReply", call.all_text(),
                f"reply mutation must not fire when marker already present: {call.argv!r}",
            )


class TestThreadsReplyMarkerFetchFailure(unittest.TestCase):
    """The marker re-fetch failed: posting blind could duplicate a reply."""

    def test_failed_refetch_reports_failed_json_and_posts_nothing(self):
        fake = FakeGhRunner()
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(["node"], stdout=json.dumps({"errors": [{"message": "rate limited"}]}))
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)
        fake.add(["resolveReviewThread"], **_resolve_success_response().__dict__)

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("fixed", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply", "--thread", "PRT_kwABC",
                    "--body-file", str(body_path), "--run-id", "R", "--resolve",
                ])

        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("rate limited", payload["error"])
        self.assertFalse(payload["resolved"])
        for call in fake.calls:
            self.assertNotIn("addPullRequestReviewThreadReply", call.all_text())
            self.assertNotIn("resolveReviewThread", call.all_text())


class TestThreadsReplyAlreadyRepliedWithResolve(unittest.TestCase):
    """Retry after a run died between reply and resolve.

    The marker check says the reply already landed, so we must NOT post a
    duplicate. But when the caller asked to --resolve too, we must still
    resolve now -- otherwise a run that crashed mid-way leaves the thread open
    forever, and every subsequent retry silently short-circuits without ever
    resolving it.
    """

    def test_already_replied_with_resolve_still_resolves(self):
        fake = FakeGhRunner()
        # Chain already carries the marker, written by us on the run that died.
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(
            ["node"],
            **_thread_chain_response([
                "prior comment",
                (ACTOR, "<!-- dancing-bear-run: R3 -->\nposted on the run that died"),
            ]).__dict__,
        )
        # A resolve response is registered; the test asserts exactly one call.
        fake.add(["resolveReviewThread"], **_resolve_success_response("PRT_1").__dict__)
        # No reply response registered on purpose: any reply call would raise
        # "no fake response registered", making a regression fail loudly.

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("would-be duplicate", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply",
                    "--thread", "PRT_1",
                    "--body-file", str(body_path),
                    "--run-id", "R3",
                    "--resolve",
                ])

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "already_replied")
        self.assertTrue(payload["resolved"])

        # Exactly one resolve, zero reply mutations.
        reply_calls = [c for c in fake.calls if "addPullRequestReviewThreadReply" in c.all_text()]
        resolve_calls = [c for c in fake.calls if "resolveReviewThread" in c.all_text()]
        self.assertEqual(len(reply_calls), 0, "must NOT post a duplicate reply")
        self.assertEqual(len(resolve_calls), 1, "must still resolve once")


def _reply(fake, body: str, *extra: str):
    with TemporaryDirectory() as td:
        body_path = Path(td) / "reply.md"
        body_path.write_text(body, encoding="utf-8")
        with _install_client(fake):
            return _run_cli(["threads", "reply", "--thread", "PRT_kwABC",
                             "--body-file", str(body_path), *extra])


def _threads_page(total: int, node_ids: list[str]) -> str:
    nodes = [{"id": i, "isResolved": False, "isOutdated": False, "path": "a.py", "line": 1,
              "comments": {"totalCount": 1, "pageInfo": {"hasNextPage": False, "endCursor": None},
                           "nodes": [{"databaseId": n, "author": {"login": "rev", "__typename": "User"},
                                      "body": "b", "createdAt": "2026-01-01T00:00:00Z", "url": "u"}]}}
             for n, i in enumerate(node_ids, start=1)]
    return json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "totalCount": total, "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}})


class TestThreadsFetchFailsClosed(unittest.TestCase):
    """A truncated fetch must not exit 0: every consumer acts on this file."""

    def _fetch(self, total: int, ids: list[str]):
        fake = FakeGhRunner()
        fake.add(["reviewThreads"], stdout=_threads_page(total, ids))
        fake.add(["--paginate"], stdout="[[]]")
        with TemporaryDirectory() as td:
            out_path = Path(td) / "threads.json"
            with _install_client(fake):
                rc, _out, err = _run_cli([
                    "threads", "fetch", "--repo", "acme/widgets", "--pr", "7", "--out", str(out_path),
                ])
            doc = json.loads(out_path.read_text(encoding="utf-8"))
        return rc, err, doc

    def test_complete_fetch_exits_zero(self):
        rc, err, doc = self._fetch(2, ["T1", "T2"])
        self.assertEqual(rc, 0)
        self.assertFalse(doc["truncated"])
        self.assertEqual(err, "")

    def test_truncated_fetch_exits_nonzero_but_still_writes_the_file(self):
        rc, err, doc = self._fetch(3, ["T1", "T2"])  # GitHub reports 3, 2 came back
        self.assertEqual(rc, 1)
        self.assertIn("incomplete", err)
        # Written anyway, so the partial result can be inspected.
        self.assertTrue(doc["truncated"])
        self.assertEqual([t["thread_id"] for t in doc["threads"]], ["T1", "T2"])


class TestThreadsReplyForgedMarker(unittest.TestCase):
    """The marker is plaintext and public; only the actor's own copy counts."""

    def test_marker_pasted_by_someone_else_does_not_suppress_the_reply(self):
        fake = FakeGhRunner()
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(["node"], **_thread_chain_response([
            ("mallory", "ignore this <!-- dancing-bear-run: R -->"),
        ]).__dict__)
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)
        fake.add(["resolveReviewThread"], **_resolve_success_response().__dict__)

        rc, out, _ = _reply(fake, "fixed in abc", "--run-id", "R", "--resolve")

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "replied")
        self.assertTrue(payload["forged_marker"])
        self.assertTrue(payload["resolved"])

    def test_actor_match_ignores_the_bot_suffix(self):
        fake = FakeGhRunner()
        fake.add(["viewer"], **_viewer_response("dancing-app[bot]").__dict__)
        fake.add(["node"], **_thread_chain_response([
            ("dancing-app", "done\n<!-- dancing-bear-run: R -->"),
        ]).__dict__)

        rc, out, _ = _reply(fake, "again", "--run-id", "R")

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["status"], "already_replied")
        self.assertFalse(json.loads(out)["forged_marker"])

    def test_unresolvable_actor_fails_closed_and_posts_nothing(self):
        fake = FakeGhRunner()
        fake.add(["viewer"], stdout=json.dumps({"data": {"viewer": {"login": ""}}}))
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        rc, out, _ = _reply(fake, "fixed", "--run-id", "R")

        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "failed")
        self.assertIn("authenticated GitHub actor", json.loads(out)["error"])
        self.assertFalse(any("addPullRequestReviewThreadReply" in c.all_text() for c in fake.calls))


class TestThreadsReplyUnreadableBodyFile(unittest.TestCase):
    """A missing or unreadable body file is a usage error, not a traceback."""

    def test_missing_body_file_is_usage_error_and_posts_nothing(self):
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)
        with TemporaryDirectory() as td, _install_client(fake):
            rc, _out, err = _run_cli(["threads", "reply", "--thread", "PRT_kwABC",
                                      "--body-file", str(Path(td) / "absent.md")])
        self.assertEqual(rc, 2)
        self.assertIn("cannot read --body-file", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(fake.calls, [])


class TestThreadsReplyWhitespaceOnlyBody(unittest.TestCase):
    """A body that is empty (or only a stale run marker) after stripping must
    be refused before the marker is appended, not turned into a marker-only
    reply that slips past the empty-reply guard."""

    def test_whitespace_only_body_is_refused_with_no_gh_call(self):
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)
        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("   \n\t\n", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply", "--thread", "PRT_kwABC",
                    "--body-file", str(body_path), "--run-id", "R",
                ])
        self.assertEqual(rc, 1)
        # Same JSON shape as every other failed reply, so the resolve
        # fragment can record it rather than finding no output at all.
        self.assertEqual(json.loads(out)["status"], "failed")
        self.assertIn("empty or whitespace-only", json.loads(out)["error"])
        self.assertEqual(fake.calls, [], "no gh call must fire for a body that is empty after stripping")

    def test_marker_only_body_is_refused_with_no_gh_call(self):
        # Only a stale run marker, no reviewer-visible content at all.
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)
        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("<!-- dancing-bear-run: stale -->", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply", "--thread", "PRT_kwABC",
                    "--body-file", str(body_path), "--run-id", "R2",
                ])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "failed")
        self.assertIn("empty or whitespace-only", json.loads(out)["error"])
        self.assertEqual(fake.calls, [])


class TestThreadsReplyStripsQuotedMarkers(unittest.TestCase):
    """A marker quoted in the reply text must never be posted under our account."""

    def test_quoted_marker_is_replaced_by_this_runs_own(self):
        fake = FakeGhRunner()
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(["node"], **_thread_chain_response(["note"]).__dict__)
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        quoted = "> you said <!--dancing-bear-run: OTHER-RUN-->\nfixed"
        rc, _, _ = _reply(fake, quoted, "--run-id", "R")

        self.assertEqual(rc, 0)
        body = _posted_body(fake)
        self.assertNotIn("OTHER-RUN", body)
        self.assertEqual(body.count("dancing-bear-run"), 1)
        self.assertTrue(body.endswith("<!-- dancing-bear-run: R -->"))

    def test_quoted_marker_is_stripped_without_run_id_too(self):
        fake = FakeGhRunner()
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        rc, _, _ = _reply(fake, "fixed <!-- dancing-bear-run: OTHER-RUN -->")

        self.assertEqual(rc, 0)
        self.assertNotIn("dancing-bear-run", _posted_body(fake))


class TestThreadsReplyMarkerAppendedOnFirstRun(unittest.TestCase):
    """When the marker is absent, the reply body is augmented with it."""

    def test_body_carries_marker_on_post(self):
        fake = FakeGhRunner()
        # Chain response with no marker.
        fake.add(["viewer"], **_viewer_response().__dict__)
        fake.add(["node"], **_thread_chain_response(["earlier note"]).__dict__)
        fake.add(["addPullRequestReviewThreadReply"], **_reply_success_response().__dict__)

        with TemporaryDirectory() as td:
            body_path = Path(td) / "reply.md"
            body_path.write_text("fixed in commit abc", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "threads", "reply",
                    "--thread", "PRT_kwABC",
                    "--body-file", str(body_path),
                    "--run-id", "R2",
                ])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["status"], "replied")

        # The last gh call is the reply; its stdin JSON body variable carries the marker.
        reply_call = fake.calls[-1]
        variables = graphql_variables_of(reply_call.argv, {"input": reply_call.input_text})
        body_var = variables.get("body")
        self.assertIsNotNone(body_var, f"no body variable in stdin JSON {reply_call.input_text!r}")
        self.assertIn("<!-- dancing-bear-run: R2 -->", body_var)


# ---------------------------------------------------------------------------
# pr view
# ---------------------------------------------------------------------------


class TestPrView(unittest.TestCase):
    def test_value_prints_bare_scalar(self):
        # --value returns one field as a bare scalar suitable for $(...).
        fake = FakeGhRunner()
        fake.add(
            ["pr", "view"],
            stdout=json.dumps({"headRefOid": "abc123def"}),
        )
        with _install_client(fake):
            rc, out, _err = _run_cli(["pr", "view", "--pr", "123", "--value", "headRefOid"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "abc123def")

    def test_fields_prints_json(self):
        fake = FakeGhRunner()
        fake.add(
            ["pr", "view"],
            stdout=json.dumps({"number": 123, "title": "hi"}),
        )
        with _install_client(fake):
            rc, out, _err = _run_cli([
                "pr", "view", "--pr", "123", "--fields", "number,title",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"number": 123, "title": "hi"})

    def test_value_prints_object_as_compact_json(self):
        # `--value author` must yield valid JSON that a downstream `jq .login`
        # can consume; Python's dict repr is not valid JSON, and pretty JSON on
        # multiple lines would break shell $(...) usage.
        fake = FakeGhRunner()
        fake.add(
            ["pr", "view"],
            stdout=json.dumps({"author": {"login": "octocat", "id": 1}}),
        )
        with _install_client(fake):
            rc, out, _err = _run_cli(["pr", "view", "--pr", "42", "--value", "author"])
        self.assertEqual(rc, 0)
        text = out.rstrip("\n")
        # Exactly one line (compact); parses back to the object.
        self.assertNotIn("\n", text)
        self.assertEqual(json.loads(text), {"login": "octocat", "id": 1})

    def test_value_prints_number_bare(self):
        fake = FakeGhRunner()
        fake.add(["pr", "view"], stdout=json.dumps({"number": 42}))
        with _install_client(fake):
            rc, out, _err = _run_cli(["pr", "view", "--pr", "42", "--value", "number"])
        self.assertEqual(rc, 0)
        # No JSON quoting, no brackets.
        self.assertEqual(out.strip(), "42")

    def test_value_prints_booleans_as_json_literals(self):
        # Python would print `True`; JSON and shell tests expect `true`.
        for raw, expected in ((True, "true"), (False, "false")):
            fake = FakeGhRunner()
            fake.add(["pr", "view"], stdout=json.dumps({"isDraft": raw}))
            with self.subTest(raw=raw), _install_client(fake):
                rc, out, _err = _run_cli(["pr", "view", "--pr", "4", "--value", "isDraft"])
                self.assertEqual(rc, 0)
                self.assertEqual(out.strip(), expected)

    def test_value_prints_strings_bare_not_json_quoted(self):
        fake = FakeGhRunner()
        fake.add(["pr", "view"], stdout=json.dumps({"headRefOid": "abc123"}))
        with _install_client(fake):
            _rc, out, _err = _run_cli(["pr", "view", "--pr", "4", "--value", "headRefOid"])
        self.assertEqual(out.strip(), "abc123")

    def test_no_fields_or_value_is_a_usage_error(self):
        fake = FakeGhRunner()
        with _install_client(fake):
            rc, _out, err = _run_cli(["pr", "view", "--pr", "123"])
        self.assertNotEqual(rc, 0)
        self.assertIn("needs --fields or --value", err)


# ---------------------------------------------------------------------------
# pr edit
# ---------------------------------------------------------------------------


class TestPrEditVerifiesReadback(unittest.TestCase):
    """``pr edit`` reads the PR back and exits 1 when GitHub did not accept it.

    Prevents the failure mode where ``gh pr edit`` exits 0 but the body on the
    server is different (rate-limited, formatting stripped, or partial write).
    """

    def test_edit_readback_mismatch_exits_one(self):
        # Edit succeeds at the gh level, but the read-back returns a different body.
        fake = FakeGhRunner()
        # gh pr edit
        fake.add(["pr", "edit"], returncode=0, stdout="")
        # gh pr view -- returns the WRONG body
        fake.add(["pr", "view"], stdout=json.dumps({"title": None, "body": "not what we sent"}))

        with TemporaryDirectory() as td:
            body_path = Path(td) / "body.md"
            body_path.write_text("what we sent", encoding="utf-8")
            with _install_client(fake):
                rc, _out, err = _run_cli([
                    "pr", "edit", "--pr", "123", "--body-file", str(body_path),
                ])

        self.assertEqual(rc, 1)
        self.assertIn("body did not update", err.lower() + err)

    def test_edit_readback_match_exits_zero(self):
        fake = FakeGhRunner()
        fake.add(["pr", "edit"], returncode=0, stdout="")
        fake.add(["pr", "view"], stdout=json.dumps({"title": None, "body": "what we sent"}))

        with TemporaryDirectory() as td:
            body_path = Path(td) / "body.md"
            body_path.write_text("what we sent", encoding="utf-8")
            with _install_client(fake):
                rc, _out, _err = _run_cli([
                    "pr", "edit", "--pr", "123", "--body-file", str(body_path),
                ])

        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# pr create / list / comments / diff (thin sanity coverage)
# ---------------------------------------------------------------------------


class TestPrTitleFile(unittest.TestCase):
    """--title-file keeps a composed title out of the shell command that sends it."""

    HOSTILE = 'fix: "$(touch /tmp/pwned)" `id` title'

    def _create(self, *title_args: str, title_text: str | None = None):
        fake = FakeGhRunner()
        fake.add(["pr", "create"], stdout="https://github.com/acme/widgets/pull/9\n")
        fake.add(["pr", "view"], stdout=json.dumps({"number": 9, "url": "u"}))
        with TemporaryDirectory() as td:
            body_path = Path(td) / "pr.md"
            body_path.write_text("body", encoding="utf-8")
            title_path = Path(td) / "title.txt"
            if title_text is not None:
                title_path.write_text(title_text, encoding="utf-8")
            args = [a.replace("TITLE_FILE", str(title_path)) for a in title_args]
            with _install_client(fake):
                rc, _out, err = _run_cli(["pr", "create", "--base", "main",
                                          "--body-file", str(body_path), *args])
        return rc, err, fake

    def test_title_file_is_passed_verbatim_as_one_argv_element(self):
        rc, _err, fake = self._create("--title-file", "TITLE_FILE", title_text=self.HOSTILE + "\n")
        self.assertEqual(rc, 0)
        argv = fake.calls[0].argv
        self.assertEqual(argv[argv.index("--title") + 1], self.HOSTILE)

    def test_exactly_one_trailing_line_ending_is_accepted(self):
        for text in ("t\n", "t\r\n", "t\r", "t"):
            rc, _err, fake = self._create("--title-file", "TITLE_FILE", title_text=text)
            with self.subTest(text=repr(text)):
                self.assertEqual(rc, 0)
                argv = fake.calls[0].argv
                self.assertEqual(argv[argv.index("--title") + 1], "t")

    def test_title_and_title_file_together_are_refused(self):
        rc, err, fake = self._create("--title", "t", "--title-file", "TITLE_FILE", title_text="t")
        self.assertEqual(rc, 2)
        self.assertIn("not both", err)
        self.assertEqual(fake.calls, [])

    def test_missing_title_is_refused(self):
        rc, err, fake = self._create()
        self.assertEqual(rc, 2)
        self.assertIn("--title or --title-file", err)
        self.assertEqual(fake.calls, [])

    def test_empty_or_multiline_title_file_is_refused(self):
        for text, needle in (("  \n", "is empty"), ("line one\nline two\n", "more than one line"),
                             ("title\n\n", "more than one line"), ("title\r\n\r\n", "more than one line")):
            rc, err, fake = self._create("--title-file", "TITLE_FILE", title_text=text)
            with self.subTest(text=text):
                self.assertEqual(rc, 2)
                self.assertIn(needle, err)
                self.assertEqual(fake.calls, [])

    def test_edit_accepts_title_file(self):
        fake = FakeGhRunner()
        fake.add(["pr", "edit"], stdout="")
        fake.add(["pr", "view"], stdout=json.dumps({"title": self.HOSTILE, "body": ""}))
        with TemporaryDirectory() as td:
            title_path = Path(td) / "title.txt"
            title_path.write_text(self.HOSTILE, encoding="utf-8")
            with _install_client(fake):
                rc, _out, _err = _run_cli(["pr", "edit", "--pr", "3", "--title-file", str(title_path)])
        self.assertEqual(rc, 0)
        argv = fake.calls[0].argv
        self.assertEqual(argv[argv.index("--title") + 1], self.HOSTILE)


class TestPrCreate(unittest.TestCase):
    def test_create_returns_number_and_url(self):
        fake = FakeGhRunner()
        # gh pr create prints the URL of the new PR on stdout.
        fake.add(["pr", "create"], returncode=0, stdout="https://github.com/acme/widgets/pull/9\n")
        # gh pr view read-back returns {number, url}.
        fake.add(["pr", "view"], stdout=json.dumps({"number": 9, "url": "https://github.com/acme/widgets/pull/9"}))

        with TemporaryDirectory() as td:
            body_path = Path(td) / "pr.md"
            body_path.write_text("PR body", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "pr", "create",
                    "--base", "main",
                    "--title", "Add feature X",
                    "--body-file", str(body_path),
                    "--draft",
                ])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {
            "number": 9,
            "url": "https://github.com/acme/widgets/pull/9",
        })
        # Draft flag reached gh; body went on stdin, not argv.
        create_call = fake.calls[0]
        self.assertIn("--draft", create_call.argv)
        self.assertEqual(create_call.input_text, "PR body")


class TestPrList(unittest.TestCase):
    def test_list_prints_json_rows(self):
        fake = FakeGhRunner()
        rows = [{"number": 1, "title": "one"}, {"number": 2, "title": "two"}]
        fake.add(["pr", "list"], stdout=json.dumps(rows))
        with _install_client(fake):
            rc, out, _err = _run_cli([
                "pr", "list", "--fields", "number,title", "--limit", "5", "--state", "open",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), rows)


class TestPrDiff(unittest.TestCase):
    def test_name_only_flag_forwards(self):
        fake = FakeGhRunner()
        fake.add(["pr", "diff"], stdout="src/a.py\nsrc/b.py\n")
        with _install_client(fake):
            rc, out, _err = _run_cli(["pr", "diff", "--pr", "10", "--name-only"])
        self.assertEqual(rc, 0)
        self.assertIn("src/a.py", out)
        self.assertIn("--name-only", fake.calls[0].argv)


class TestPrChecks(unittest.TestCase):
    def test_checks_prints_bucket_json(self):
        fake = FakeGhRunner()
        rows = [{"name": "test", "state": "SUCCESS", "bucket": "pass"}]
        fake.add(["pr", "checks"], stdout=json.dumps(rows))
        with _install_client(fake):
            rc, out, _err = _run_cli(["pr", "checks", "--pr", "5"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), rows)


class TestPrComment(unittest.TestCase):
    def test_comment_reads_body_and_prints_url(self):
        fake = FakeGhRunner()
        fake.add(["pr", "comment"], stdout="https://github.com/acme/widgets/pull/1#issuecomment-5\n")
        with TemporaryDirectory() as td:
            body_path = Path(td) / "note.md"
            body_path.write_text("thanks!", encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "pr", "comment", "--pr", "1", "--body-file", str(body_path),
                ])
        self.assertEqual(rc, 0)
        self.assertIn("#issuecomment-5", out.strip())
        # Body went on stdin, not argv.
        self.assertEqual(fake.calls[0].input_text, "thanks!")


class TestPrReviewComment(unittest.TestCase):
    def test_posts_anchored_comment_from_body_file(self):
        fake = FakeGhRunner()
        fake.add(["pr", "view"], stdout=json.dumps({"headRefOid": "headsha"}))
        fake.add(["--method", "POST"], stdout=json.dumps({"id": 5, "html_url": "https://x/r5"}))
        body_text = "`$(rm -rf /)` finding summary"
        with TemporaryDirectory() as td:
            body_path = Path(td) / "summary.md"
            body_path.write_text(body_text, encoding="utf-8")
            with _install_client(fake):
                rc, out, _err = _run_cli([
                    "pr", "review-comment", "--repo", "acme/widgets", "--pr", "3",
                    "--path", "src/a.py", "--line", "10", "--body-file", str(body_path),
                ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"id": "5", "url": "https://x/r5"})
        post = fake.calls[-1]
        self.assertIn("repos/acme/widgets/pulls/3/comments", post.argv)
        self.assertIn("--input", post.argv)
        # The body (and its shell metacharacters) never touch argv.
        for tok in post.argv:
            self.assertNotIn(body_text, tok)
            self.assertNotIn("$(rm -rf /)", tok)
        payload = json.loads(post.input_text)
        self.assertEqual(payload["body"], body_text)
        self.assertEqual(payload["line"], 10)
        self.assertIsInstance(payload["line"], int)
        self.assertEqual(payload["commit_id"], "headsha")


class TestPrComments(unittest.TestCase):
    def test_review_kind_paginated_call(self):
        fake = FakeGhRunner()
        # explicit --repo skips repo resolve; only the paginated api call runs.
        fake.add(["api", "--paginate"], stdout=json.dumps([[{"id": 1}]]))
        with _install_client(fake):
            rc, out, _err = _run_cli([
                "pr", "comments", "--repo", "acme/widgets", "--pr", "3", "--kind", "review",
            ])
        self.assertEqual(rc, 0)
        # Flattened across pages.
        self.assertEqual(json.loads(out), [{"id": 1}])


# ---------------------------------------------------------------------------
# threads resolve / state
# ---------------------------------------------------------------------------


class TestThreadsResolveStandalone(unittest.TestCase):
    def test_resolve_verifies_and_prints_json(self):
        fake = FakeGhRunner()
        fake.add(["resolveReviewThread"], **_resolve_success_response("PRT_1").__dict__)
        with _install_client(fake):
            rc, out, _err = _run_cli(["threads", "resolve", "--thread", "PRT_1"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"thread_id": "PRT_1", "resolved": True})


class TestThreadsState(unittest.TestCase):
    def test_state_summarises_unresolved(self):
        fake = FakeGhRunner()
        threads_payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "totalCount": 2,
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {"id": "T1", "isResolved": False, "isOutdated": False,
                                 "isCollapsed": False, "path": "a.py", "line": 1,
                                 "startLine": None, "diffSide": "RIGHT",
                                 "comments": {"totalCount": 0,
                                              "pageInfo": {"hasNextPage": False, "endCursor": None},
                                              "nodes": []}},
                                {"id": "T2", "isResolved": True, "isOutdated": False,
                                 "isCollapsed": False, "path": "b.py", "line": 2,
                                 "startLine": None, "diffSide": "RIGHT",
                                 "comments": {"totalCount": 0,
                                              "pageInfo": {"hasNextPage": False, "endCursor": None},
                                              "nodes": []}},
                            ],
                        }
                    }
                }
            }
        }
        fake.add(["reviewThreads"], returncode=0, stdout=json.dumps(threads_payload))
        with _install_client(fake):
            rc, out, _err = _run_cli(["threads", "state", "--repo", "acme/widgets", "--pr", "10"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {
            "total": 2,
            "unresolved": 1,
            "unresolved_ids": ["T1"],
            "truncated": False,
        })

    def test_truncated_refetch_reports_null_not_a_partial_count(self):
        # GitHub reports 3 threads, 1 comes back: any count would be unverified.
        fake = FakeGhRunner()
        payload = {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "totalCount": 3,
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"id": "T1", "isResolved": False, "comments": {
                "totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []}}],
        }}}}}
        fake.add(["reviewThreads"], stdout=json.dumps(payload))
        with _install_client(fake):
            rc, out, _err = _run_cli(["threads", "state", "--repo", "acme/widgets", "--pr", "10"])
        self.assertEqual(rc, 1)
        got = json.loads(out)
        self.assertTrue(got["truncated"])
        self.assertIsNone(got["unresolved"])
        self.assertIsNone(got["total"])


# ---------------------------------------------------------------------------
# run log
# ---------------------------------------------------------------------------


class TestRunLog(unittest.TestCase):
    def test_failed_only_by_default(self):
        fake = FakeGhRunner()
        fake.add(["run", "view"], stdout="log text")
        with _install_client(fake):
            rc, out, _err = _run_cli(["run", "log", "--run", "12345"])
        self.assertEqual(rc, 0)
        self.assertIn("log text", out)
        self.assertIn("--log-failed", fake.calls[0].argv)

    def test_all_flag_switches_flag(self):
        fake = FakeGhRunner()
        fake.add(["run", "view"], stdout="full log")
        with _install_client(fake):
            rc, _out, _err = _run_cli(["run", "log", "--run", "12345", "--all"])
        self.assertEqual(rc, 0)
        self.assertIn("--log", fake.calls[0].argv)
        self.assertNotIn("--log-failed", fake.calls[0].argv)


if __name__ == "__main__":
    unittest.main()
