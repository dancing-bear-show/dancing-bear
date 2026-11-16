"""Direct tests for core.github.threads.paginate_connection."""

from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import Any, cast

from core.gh_cli import GhCLI, GhError
from core.github import threads
from core.github.threads import paginate_connection


class _ScriptedGh:
    """Answers graphql_checked from a fixed list of responses, recording variables."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def graphql_checked(self, query: str, variables: dict[str, Any]) -> Any:
        self.calls.append(dict(variables))
        return self._responses.pop(0)


def _as_gh(stub: _ScriptedGh) -> GhCLI:
    """paginate_connection only calls graphql_checked; the stub stands in for GhCLI."""
    return cast(GhCLI, stub)


def _page(nodes: list[Any], *, total: Any = None, cursor: str | None = None) -> dict[str, Any]:
    conn: dict[str, Any] = {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
    }
    if total is not None:
        conn["totalCount"] = total
    return {"repo": {"pr": {"items": conn}}}


PATH = ("repo", "pr", "items")


class TestPaginateConnection(unittest.TestCase):
    def test_collects_every_page_and_returns_last_total(self) -> None:
        gh = _ScriptedGh([_page([{"n": 1}], total=3, cursor="c1"),
                          _page([{"n": 2}, {"n": 3}], total="3")])
        nodes, total = paginate_connection(_as_gh(gh), "q", {"id": "X"}, PATH, what="items")
        self.assertEqual(nodes, [{"n": 1}, {"n": 2}, {"n": 3}])
        self.assertEqual(total, "3")  # raw, uncoerced: callers own coercion
        self.assertEqual(gh.calls, [{"id": "X", "after": None}, {"id": "X", "after": "c1"}])

    def test_after_seeds_the_first_request(self) -> None:
        gh = _ScriptedGh([_page([{"n": 1}])])
        paginate_connection(_as_gh(gh), "q", {}, PATH, what="items", after="start")
        self.assertEqual(gh.calls, [{"after": "start"}])

    def test_missing_total_is_none_not_zero(self) -> None:
        gh = _ScriptedGh([_page([])])
        self.assertEqual(paginate_connection(_as_gh(gh), "q", {}, PATH, what="items"), ([], None))

    def test_missing_connection_names_what(self) -> None:
        gh = _ScriptedGh([{"repo": {"pr": None}}])
        with self.assertRaisesRegex(GhError, r"^items: response has no repo\.pr\.items"):
            paginate_connection(_as_gh(gh), "q", {}, PATH, what="items")

    def test_on_page_receives_parent_for_every_page(self) -> None:
        gh = _ScriptedGh([_page([{"n": 1}], cursor="c1"), _page([{"n": 2}])])
        seen: list[Any] = []
        nodes, _ = paginate_connection(_as_gh(gh), "q", {}, PATH, what="items",
                                       parent_what="pull", on_page=seen.append)
        self.assertEqual([p["items"]["nodes"] for p in seen], [[{"n": 1}], [{"n": 2}]])
        self.assertEqual(nodes, [{"n": 1}, {"n": 2}])

    def test_on_page_missing_parent_names_parent_what(self) -> None:
        gh = _ScriptedGh([{"repo": None}])
        on_page = mock.Mock()
        with self.assertRaisesRegex(GhError, r"^pull: response has no repo\.pr"):
            paginate_connection(_as_gh(gh), "q", {}, PATH, what="items",
                                parent_what="pull", on_page=on_page)
        on_page.assert_not_called()

    def test_on_page_missing_connection_names_what(self) -> None:
        gh = _ScriptedGh([{"repo": {"pr": {"title": "t"}}}])
        with self.assertRaisesRegex(GhError, r"^items: response has no items"):
            paginate_connection(_as_gh(gh), "q", {}, PATH, what="items",
                                parent_what="pull", on_page=lambda _p: None)

    def test_stalled_cursor_raises(self) -> None:
        gh = _ScriptedGh([_page([], cursor="c1"), _page([], cursor="c1")])
        with self.assertRaisesRegex(GhError, r"^items: hasNextPage is true but endCursor did not advance"):
            paginate_connection(_as_gh(gh), "q", {}, PATH, what="items")

    def test_exceeding_max_pages_raises(self) -> None:
        gh = _ScriptedGh([_page([], cursor="c1"), _page([], cursor="c2")])
        with mock.patch.object(threads, "MAX_PAGES", 2), \
                self.assertRaisesRegex(GhError, r"^items: exceeded 2 pages$"):
            paginate_connection(_as_gh(gh), "q", {}, PATH, what="items")
        self.assertEqual(len(gh.calls), 2)


if __name__ == "__main__":
    unittest.main()
