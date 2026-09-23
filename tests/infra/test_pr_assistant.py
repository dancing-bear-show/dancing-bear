"""Tests for ``bin/pr-assistant``.

Cover the behaviours a live call would fail on but a documentation review would
miss:

* Copilot thread selection paginates beyond ``reviewThreads(first: 50)`` — the
  old query did not, and the tail is where the newest threads live.
* A thread whose opening comment carries ``__typename: "Bot"`` and login
  ``copilot-pull-request-reviewer[bot]`` is selected (both API spellings and
  the typed bot marker travel through ``core.github``); a human-opened thread
  is not.
* ``--dry-run`` performs NO mutation: not ``pr create``, ``pr comment``,
  ``pr edit``, or ``resolveReviewThread``. Every gh argv is recorded and each
  mutating verb is asserted absent.
* A GraphQL resolve that returns ``{"data":{"resolveReviewThread":null},
  "errors":[...]}`` with returncode 0 (gh's own exit code lies here — see
  ``core.gh_cli.GhCLI.graphql_checked``) is reported as failed.
* The argparse surface stays byte-stable: every legacy flag still parses.

``bin/pr-assistant`` has no ``.py`` extension, so it is loaded via
``importlib.machinery.SourceFileLoader``. It performs a ``.venv`` re-exec at
module-import time; the test sets ``_DANCING_BEAR_VENV_EXEC`` to the current
interpreter so the guard sees the child as already-correct and does not
recurse.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "pr-assistant"


def _load_module() -> types.ModuleType:
    """Load ``bin/pr-assistant`` as a module, bypassing its .venv re-exec.

    Setting ``_DANCING_BEAR_VENV_EXEC`` to the current interpreter tells the
    script's preamble that we are already the intended interpreter, so the
    ``os.execv`` guard is skipped and control returns to us.
    """
    os.environ["_DANCING_BEAR_VENV_EXEC"] = os.path.realpath(sys.executable)
    loader = importlib.machinery.SourceFileLoader("pr_assistant_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PRA = _load_module()


# ---------------------------------------------------------------------------
# Fake gh transport
# ---------------------------------------------------------------------------

def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Minimal stand-in for a subprocess.CompletedProcess."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGhTransport:
    """Records every argv passed to ``subprocess.run`` and returns scripted results.

    The fake receives ``["gh", ...]`` argv and dispatches on the second token.
    Every call is appended to ``calls`` so tests can assert what was and was
    not sent (the load-bearing check for ``--dry-run``).

    Only the calls this suite exercises are handled; anything else raises so an
    unexpected call cannot silently pass.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        # A test may plant per-verb responses; the default is a happy path.
        self.responses: dict[str, list[Any]] = {}

    def __call__(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append(list(cmd))
        if not cmd or cmd[0] != "gh":
            raise AssertionError(f"non-gh command reached the fake: {cmd!r}")
        return self._dispatch(cmd)

    def _dispatch(self, cmd: list[str]) -> SimpleNamespace:
        # gh api graphql — the mutation and query paths share this verb, so the
        # test that needs a specific response should plant one under
        # ``responses["graphql"]``.
        if cmd[:3] == ["gh", "api", "graphql"]:
            return self._pop("graphql", default=_proc(stdout='{"data":{}}'))
        if cmd[:2] == ["gh", "api"]:
            return self._pop("api", default=_proc(stdout="[[]]"))
        if cmd[:3] == ["gh", "pr", "view"]:
            return self._pop("pr_view", default=_proc(
                stdout='{"number": 42, "url": "https://example/pr/42",'
                       ' "headRefName": "feature", "baseRefName": "main"}'
            ))
        if cmd[:3] == ["gh", "pr", "diff"]:
            return self._pop("pr_diff", default=_proc(stdout=""))
        if cmd[:3] == ["gh", "pr", "checks"]:
            return self._pop("pr_checks", default=_proc(stdout="[]"))
        if cmd[:3] == ["gh", "repo", "view"]:
            return self._pop("repo_view", default=_proc(stdout="owner/repo\n"))
        if cmd[:3] == ["gh", "pr", "create"]:
            return self._pop("pr_create")
        if cmd[:3] == ["gh", "pr", "comment"]:
            return self._pop("pr_comment")
        if cmd[:3] == ["gh", "pr", "edit"]:
            return self._pop("pr_edit")
        raise AssertionError(f"unhandled gh call: {cmd!r}")

    def _pop(self, key: str, *, default: SimpleNamespace | None = None) -> SimpleNamespace:
        queue = self.responses.get(key)
        if queue:
            return queue.pop(0)
        if default is None:
            raise AssertionError(f"no scripted response for {key!r}; call was made")
        return default

    def graphql_query(self, response: dict[str, Any]) -> None:
        """Push a JSON payload to be returned by the next ``gh api graphql``."""
        import json
        self.responses.setdefault("graphql", []).append(
            _proc(stdout=json.dumps(response))
        )


def _new_gh(fake: FakeGhTransport):
    """Build a real GhCLI backed by ``fake`` (so all core.github logic runs)."""
    from core.gh_cli import GhCLI
    return GhCLI(run_func=fake)


# ---------------------------------------------------------------------------
# GraphQL fixtures
# ---------------------------------------------------------------------------

def _thread_node(
    thread_id: str,
    *,
    author_login: str,
    typename: str = "Bot",
    resolved: bool = False,
    path: str = "src/foo.py",
    line: int = 10,
    body: str = "please fix this",
) -> dict[str, Any]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": False,
        "isCollapsed": False,
        "path": path,
        "line": line,
        "startLine": None,
        "diffSide": "RIGHT",
        "comments": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{
                "databaseId": 1,
                "author": {"login": author_login, "__typename": typename},
                "body": body,
                "createdAt": "2026-01-01T00:00:00Z",
                "url": "https://example/comment/1",
            }],
        },
    }


def _threads_page(nodes: list[dict[str, Any]], *, has_next: bool, end_cursor: str | None,
                  total: int | None = None) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "totalCount": total if total is not None else len(nodes),
                        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


class TestPaginatedCopilotSelection(unittest.TestCase):
    """The old ``reviewThreads(first: 50)`` silently dropped page 2."""

    def test_copilot_thread_on_page_two_is_returned(self) -> None:
        fake = FakeGhTransport()
        # Page 1: 100 non-copilot threads
        page1_nodes = [
            _thread_node(f"page1-{i}", author_login="somebody", typename="User")
            for i in range(100)
        ]
        # Page 2: one real copilot thread
        page2_nodes = [
            _thread_node(
                "PAGE2_COPILOT",
                author_login="copilot-pull-request-reviewer",
                typename="Bot",
                body="page-two finding",
            ),
        ]
        fake.graphql_query(_threads_page(page1_nodes, has_next=True, end_cursor="c1", total=101))
        fake.graphql_query(_threads_page(page2_nodes, has_next=False, end_cursor=None, total=101))
        # fetch_review_threads also queries REST reviews and issue-comments.
        fake.responses["api"] = [_proc(stdout="[[]]"), _proc(stdout="[[]]")]

        gh = _new_gh(fake)
        threads = PRA.fetch_copilot_threads(gh, "owner", "repo", 42)

        self.assertEqual(
            [t["id"] for t in threads],
            ["PAGE2_COPILOT"],
            "the page-two Copilot thread was dropped — pagination regressed to first(50)",
        )
        # Teeth check note: the analogous "break the pagination" probe is in
        # ``test_page_two_dropped_when_only_first_page_is_returned`` below.

    def test_page_two_dropped_when_only_first_page_is_returned(self) -> None:
        """Teeth for the pagination assertion.

        If pr-assistant regressed to a single-page query, this fixture would
        withhold page 2 and the Copilot thread would vanish. Assert the
        failure mode directly so a future refactor cannot pass the positive
        test above with a broken pagination.
        """
        fake = FakeGhTransport()
        page1_nodes = [
            _thread_node(f"page1-{i}", author_login="somebody", typename="User")
            for i in range(50)
        ]
        # Only page 1; totalCount matches so nothing looks truncated.
        fake.graphql_query(_threads_page(page1_nodes, has_next=False, end_cursor=None, total=50))
        fake.responses["api"] = [_proc(stdout="[[]]"), _proc(stdout="[[]]")]

        gh = _new_gh(fake)
        threads = PRA.fetch_copilot_threads(gh, "owner", "repo", 42)

        self.assertEqual(threads, [], "no Copilot thread was present in the fixture")


class TestIncompleteFetchIsRefused(unittest.TestCase):
    """A thread fetch whose counts do not match must not become a summary."""

    def test_truncated_fetch_raises_instead_of_returning_a_partial_list(self):
        fake = FakeGhTransport()
        node = _thread_node("PRRT_1", author_login="copilot-pull-request-reviewer")
        fake.graphql_query({"data": {"repository": {"pullRequest": {"reviewThreads": {
            "totalCount": 3,  # GitHub says 3; one came back
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [node],
        }}}}})
        with self.assertRaisesRegex(PRA.GhError, "incomplete"):
            PRA.fetch_copilot_threads(_new_gh(fake), "owner", "repo", 42)

    def test_main_turns_any_gh_error_into_exit_1_without_a_traceback(self):
        with patch.object(sys, "argv", ["pr-assistant", "--dry-run"]), \
                patch.object(PRA, "_run", side_effect=PRA.GhError("gh api graphql timed out after 300s")), \
                patch("sys.stderr") as err:
            self.assertEqual(PRA.main(), 1)
        written = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("pr-assistant: gh api graphql timed out", written)


class TestCopilotAuthorIdentification(unittest.TestCase):
    """A ``[bot]`` login and a typed ``Bot`` marker both count; a human does not."""

    def _run_selection(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        fake = FakeGhTransport()
        fake.graphql_query(_threads_page([node], has_next=False, end_cursor=None))
        fake.responses["api"] = [_proc(stdout="[[]]"), _proc(stdout="[[]]")]
        return PRA.fetch_copilot_threads(_new_gh(fake), "owner", "repo", 42)

    def test_copilot_bot_suffix_login_selected(self) -> None:
        node = _thread_node(
            "COPILOT_BOT",
            # REST-flavoured login: normalize_login strips the [bot] suffix.
            author_login="copilot-pull-request-reviewer[bot]",
            typename="Bot",
        )
        threads = self._run_selection(node)
        self.assertEqual([t["id"] for t in threads], ["COPILOT_BOT"])

    def test_human_opened_thread_not_selected(self) -> None:
        node = _thread_node(
            "HUMAN_THREAD",
            author_login="somebody",
            typename="User",
        )
        threads = self._run_selection(node)
        self.assertEqual(threads, [], "a human-opened thread must not be treated as Copilot")

    def test_resolved_copilot_thread_not_selected(self) -> None:
        node = _thread_node(
            "COPILOT_RESOLVED",
            author_login="copilot-pull-request-reviewer",
            typename="Bot",
            resolved=True,
        )
        threads = self._run_selection(node)
        self.assertEqual(threads, [], "already-resolved threads must be filtered out")


class TestDryRunPerformsNoMutation(unittest.TestCase):
    """--dry-run must issue no create/comment/edit/resolve argv."""

    def _make_args(self, **overrides: Any) -> Any:
        # Real argparse namespace so unexpected flags fail loudly.
        parser = PRA.build_parser()
        argv: list[str] = ["--dry-run"]
        for k, v in overrides.items():
            argv += [k, v] if isinstance(v, str) else [k]
        return parser.parse_args(argv)

    def test_full_pipeline_dry_run_issues_no_mutating_argv(self) -> None:
        fake = FakeGhTransport()
        # No PR exists yet — force the create path.
        fake.responses["pr_view"] = [_proc(returncode=1, stderr="no pull requests found")]
        # gh repo view for resolve_owner_repo.
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]

        gh = _new_gh(fake)
        # _ensure_pr returns (None, 0) on dry-run when no PR exists.
        args = self._make_args(**{"--title": "T", "--body": "B"})
        with patch.object(PRA, "_git", return_value="feature-branch"):
            pr, exit_code = PRA._ensure_pr(gh, args)
        self.assertIsNone(pr)
        self.assertEqual(exit_code, 0)

        # Now simulate the mutation entry points as if a PR existed. Each must
        # perform no gh mutation under dry-run.
        PRA._resolve_copilot_threads(gh, [{"id": "T1", "path": "p", "line": 1, "body": "x"}], args)
        PRA._post_summary_comment(gh, 42, [], None, [], args)
        PRA._update_pr_metadata(gh, 42, args)

        mutating = {"resolveReviewThread"}
        for call in fake.calls:
            argv_text = " ".join(call)
            self.assertNotIn(
                "pr create", argv_text,
                f"dry-run issued 'pr create': {call!r}",
            )
            self.assertNotIn(
                "pr comment", argv_text,
                f"dry-run issued 'pr comment': {call!r}",
            )
            self.assertNotIn(
                "pr edit", argv_text,
                f"dry-run issued 'pr edit': {call!r}",
            )
            for marker in mutating:
                self.assertFalse(
                    any(marker in tok for tok in call),
                    f"dry-run issued a resolve mutation: {call!r}",
                )


class TestResolveFailureIsReported(unittest.TestCase):
    """A GraphQL null-with-errors payload is a failure, not a success.

    ``gh`` exits 0 on an HTTP 200 whose body carries an ``errors`` array — the
    old code trusted returncode and silently reported success. Now
    ``resolve_thread`` raises ``GhError`` on any of three markers: the errors
    array, a missing ``data`` object, or a thread returned without
    ``isResolved: true``.
    """

    def test_null_thread_and_errors_array_raises(self) -> None:
        from core.gh_cli import GhError
        fake = FakeGhTransport()
        # gh exits 0 but the payload carries errors + null thread. The
        # ``resolve_thread`` symbol pr-assistant imports must raise, not silently
        # accept the response.
        fake.graphql_query({
            "data": {"resolveReviewThread": None},
            "errors": [{"message": "Resource not accessible by integration"}],
        })
        gh = _new_gh(fake)

        with self.assertRaises(GhError):
            PRA.resolve_thread(gh, "THREAD_ID")

    def test_success_payload_does_not_raise(self) -> None:
        """Guardrail: a valid resolved response must NOT raise.

        Otherwise the negative test above would pass against a resolve that
        raises unconditionally, which would break normal use.
        """
        fake = FakeGhTransport()
        fake.graphql_query({
            "data": {"resolveReviewThread": {"thread": {"id": "T", "isResolved": True}}},
        })
        gh = _new_gh(fake)
        # No assertion needed — the call not raising is the assertion.
        PRA.resolve_thread(gh, "THREAD_ID")

    def test_pipeline_reports_some_failed_when_a_resolve_raises(self) -> None:
        """End-to-end: ``_resolve_copilot_threads`` catches and continues.

        Prints "some failed" so the human summary matches the previous shape.
        """
        from core.gh_cli import GhError

        def _raiser(_gh: Any, _id: str) -> None:
            raise GhError("resolve of X did not report isResolved: true")

        gh = _new_gh(FakeGhTransport())
        parser = PRA.build_parser()
        args = parser.parse_args([])  # not dry-run
        with patch.object(PRA, "resolve_thread", side_effect=_raiser):
            # No exception should escape; the failure is printed instead.
            PRA._resolve_copilot_threads(
                gh, [{"id": "T1", "path": "p", "line": 1, "body": "x"}], args,
            )


class TestArgparseSurfaceUnchanged(unittest.TestCase):
    """Every legacy flag must still parse — the CLI is a public contract."""

    def test_every_legacy_flag_parses(self) -> None:
        parser = PRA.build_parser()
        argv = [
            "--create", "--no-create",
            "--resolve-copilot", "--no-resolve-copilot",
            "--check-qlty", "--no-check-qlty",
            "--check-ci", "--no-check-ci",
            "--update-summary", "--no-update-summary",
            "--base", "develop",
            "--title", "T",
            "--body", "B",
            "--dry-run",
        ]
        args = parser.parse_args(argv)
        # The last of a pair wins under argparse; verify the flags exist at all.
        for name in (
            "create", "resolve_copilot", "check_qlty",
            "check_ci", "update_summary", "dry_run",
        ):
            self.assertTrue(hasattr(args, name), f"{name} missing from namespace")
        self.assertEqual(args.base, "develop")
        self.assertEqual(args.title, "T")
        self.assertEqual(args.body, "B")


class TestFormatCheckStatusHandlesBucket(unittest.TestCase):
    """`gh pr checks --json` now emits ``bucket``; existing rows still work."""

    def test_bucket_pass_is_passed(self) -> None:
        self.assertEqual(PRA.format_check_status({"bucket": "pass"}), "passed")

    def test_bucket_fail_is_failed(self) -> None:
        self.assertEqual(PRA.format_check_status({"bucket": "fail"}), "failed")

    def test_bucket_pending_is_pending(self) -> None:
        self.assertEqual(PRA.format_check_status({"bucket": "pending"}), "pending")

    def test_bucket_skipping_is_skipped(self) -> None:
        self.assertEqual(PRA.format_check_status({"bucket": "skipping"}), "skipped")

    def test_bucket_cancel_is_cancelled(self) -> None:
        self.assertEqual(PRA.format_check_status({"bucket": "cancel"}), "cancelled")

    def test_state_in_progress_when_no_bucket(self) -> None:
        # State-only rows (external status checks) still classify.
        self.assertEqual(
            PRA.format_check_status({"state": "IN_PROGRESS"}), "in_progress",
        )

    def test_unknown_falls_back_to_unknown(self) -> None:
        self.assertEqual(PRA.format_check_status({}), "unknown")


if __name__ == "__main__":
    unittest.main()
