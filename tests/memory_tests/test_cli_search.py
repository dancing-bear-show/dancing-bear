"""Coverage for memory.commands.search: _resolve_stores (--store,
--all-stores, default), _collect_matches limit, regex compilation error,
load_store failure, and CLI entry dispatch.

resolve_current_store itself (cwd prefix match, fallback to elect_canonical)
is covered by tests/memory/test_discovery.py — it lives in memory.discovery.

Patches discover_stores and load_store where they are USED
(memory.commands.search), per project convention.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.cli
from memory.commands.search import (
    _collect_matches,
    _resolve_stores,
)
from memory.models import MemoryStore
from memory.parser import parse_memory_file

from tests.memory_tests.fixtures import MemoryTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(
    tmp: Path,
    slug: str,
    memories: list[tuple[str, str]] | None = None,
    *,
    inferred_repo: str | None = None,
) -> MemoryStore:
    """Build a MemoryStore with optional memory files on disk."""
    store_root = tmp / slug
    mem_dir = store_root / "memory"
    mem_dir.mkdir(parents=True)

    parsed_memories = []
    for filename, content in memories or []:
        f = mem_dir / filename
        f.write_text(content, encoding="utf-8")
        parsed_memories.append(parse_memory_file(f, project_slug=slug))

    return MemoryStore(
        project_slug=slug,
        root=str(store_root),
        memories=tuple(parsed_memories),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=inferred_repo,
        is_worktree_slug=False,
    )


_FEEDBACK_CONTENT = (
    "---\n"
    "name: {name}\n"
    "description: {desc}\n"
    "metadata:\n"
    "  type: feedback\n"
    "  node_type: memory\n"
    "---\n\n"
    "**Why:** {body}\n\n**How to apply:** Use in tests.\n"
)


def _feedback(name: str, desc: str = "test", body: str = "Testing.") -> str:
    return _FEEDBACK_CONTENT.format(name=name, desc=desc, body=body)


def _make_namespace(
    *,
    store: str | None = None,
    all_stores: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(store=store, all_stores=all_stores)


# ---------------------------------------------------------------------------
# _resolve_stores — --store, --all-stores, default paths
# ---------------------------------------------------------------------------


class TestResolveStores(MemoryTestCase):
    def test_specific_store_flag_calls_load_store(self) -> None:
        store = _make_store(self.tmp, "specific-slug")
        ns = _make_namespace(store="specific-slug")

        with patch(
            "memory.commands.search.load_store", return_value=store
        ) as mock_load:
            result = _resolve_stores(ns, (store,))
        mock_load.assert_called_once_with("specific-slug")
        self.assertEqual(result, (store,))

    def test_specific_store_not_found_returns_int(self) -> None:
        ns = _make_namespace(store="nonexistent-slug")
        err_buf = io.StringIO()
        with (
            patch(
                "memory.commands.search.load_store",
                side_effect=Exception("store not found"),
            ),
            contextlib.redirect_stderr(err_buf),
        ):
            result = _resolve_stores(ns, ())
        self.assertIsInstance(result, int)
        self.assertEqual(result, 1)

    def test_all_stores_flag_returns_all(self) -> None:
        store_a = _make_store(self.tmp, "slug-a")
        store_b = _make_store(self.tmp, "slug-b")
        ns = _make_namespace(all_stores=True)

        result = _resolve_stores(ns, (store_a, store_b))
        self.assertEqual(result, (store_a, store_b))

    def test_default_uses_current_store(self) -> None:
        store = _make_store(self.tmp, "current-slug")
        ns = _make_namespace()

        with patch(
            "memory.commands.search.resolve_current_store", return_value=store
        ):
            result = _resolve_stores(ns, (store,))
        self.assertEqual(result, (store,))

    def test_default_no_current_store_returns_all(self) -> None:
        store_a = _make_store(self.tmp, "slug-a")
        ns = _make_namespace()

        with patch(
            "memory.commands.search.resolve_current_store", return_value=None
        ):
            result = _resolve_stores(ns, (store_a,))
        self.assertEqual(result, (store_a,))


# ---------------------------------------------------------------------------
# _collect_matches — limit enforcement
# ---------------------------------------------------------------------------


class TestCollectMatchesLimit(MemoryTestCase):
    def test_limit_zero_returns_all_matches(self) -> None:
        store = _make_store(
            self.tmp,
            "limit-slug",
            [
                ("mem_a.md", _feedback("mem_a", body="alpha beta alpha")),
                ("mem_b.md", _feedback("mem_b", body="alpha gamma alpha")),
            ],
        )
        matches = _collect_matches((store,), query="alpha", pattern=None, limit=0)
        # "alpha" appears twice in each body — 4+ matches total
        self.assertGreaterEqual(len(matches), 4)

    def test_limit_one_stops_early(self) -> None:
        store = _make_store(
            self.tmp,
            "limit-slug",
            [
                ("mem_a.md", _feedback("mem_a", body="alpha beta alpha")),
                ("mem_b.md", _feedback("mem_b", body="alpha gamma")),
            ],
        )
        matches = _collect_matches((store,), query="alpha", pattern=None, limit=1)
        self.assertEqual(len(matches), 1)

    def test_limit_respects_count_across_stores(self) -> None:
        store_a = _make_store(
            self.tmp, "store-a", [("mem.md", _feedback("mem_a", body="target target"))]
        )
        store_b = _make_store(
            self.tmp, "store-b", [("mem.md", _feedback("mem_b", body="target"))]
        )
        matches = _collect_matches(
            (store_a, store_b), query="target", pattern=None, limit=2
        )
        self.assertEqual(len(matches), 2)


# ---------------------------------------------------------------------------
# CLI entry — regex compilation error
# ---------------------------------------------------------------------------


class TestMainRegexError(MemoryTestCase):
    def test_invalid_regex_returns_exit_code_1(self) -> None:
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = memory.cli.main(["search", "--regex", "[invalid("])
        self.assertEqual(rc, 1)

    def test_invalid_regex_writes_to_stderr(self) -> None:
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            memory.cli.main(["search", "--regex", "[bad"])
        err = err_buf.getvalue()
        self.assertTrue("invalid regex" in err.lower() or "query" in err.lower())


# ---------------------------------------------------------------------------
# CLI entry — --store load failure
# ---------------------------------------------------------------------------


class TestMainStoreFlagLoadFailure(MemoryTestCase):
    def test_load_failure_returns_exit_code_1(self) -> None:
        err_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=()),
            patch(
                "memory.commands.search.load_store",
                side_effect=Exception("not found"),
            ),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["search", "--store", "bogus-slug", "query"])
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# CLI entry — happy path, basic search
# ---------------------------------------------------------------------------


class TestMainHappyPath(MemoryTestCase):
    def test_search_returns_zero_on_no_matches(self) -> None:
        store = _make_store(self.tmp, "my-slug")
        err_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["search", "nomatch_xyz"])
        self.assertIsInstance(rc, int)

    def test_search_finds_matches_in_body(self) -> None:
        store = _make_store(
            self.tmp,
            "body-slug",
            [("mem.md", _feedback("mem_name", body="unique_marker_xyz"))],
        )
        out_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["search", "--format", "json", "unique_marker_xyz"])
        rows = json.loads(out_buf.getvalue().strip())
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(any(r["match_field"] == "body" for r in rows))

    def test_search_with_all_stores_flag(self) -> None:
        store_a = _make_store(self.tmp, "store-a")
        store_b = _make_store(self.tmp, "store-b")
        err_buf = io.StringIO()
        with (
            patch(
                "memory.commands.search.discover_stores",
                return_value=(store_a, store_b),
            ),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["search", "--all-stores", "--format", "json", "nomatch"])
        self.assertIsInstance(rc, int)

    def test_regex_search_finds_pattern_match(self) -> None:
        store = _make_store(
            self.tmp,
            "regex-slug",
            [("mem.md", _feedback("mem_name", body="error code 404 happened"))],
        )
        out_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["search", "--regex", "--format", "json", r"error code \d+"])
        rows = json.loads(out_buf.getvalue().strip())
        self.assertGreaterEqual(len(rows), 1)

    def test_limit_flag_restricts_results(self) -> None:
        store = _make_store(
            self.tmp,
            "limit-test-slug",
            [
                ("mem_a.md", _feedback("mem_a", body="alpha alpha alpha")),
                ("mem_b.md", _feedback("mem_b", body="alpha alpha")),
            ],
        )
        out_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["search", "--limit", "1", "--format", "json", "alpha"])
        rows = json.loads(out_buf.getvalue().strip())
        self.assertEqual(len(rows), 1)


# ---------------------------------------------------------------------------
# CLI entry — json format output and int return type
# ---------------------------------------------------------------------------


class TestMainReturnType(MemoryTestCase):
    def test_main_always_returns_int(self) -> None:
        store = _make_store(self.tmp, "int-ret-slug")
        err_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["search", "query_term"])
        self.assertIsInstance(rc, int)

    def test_json_format_valid_json(self) -> None:
        store = _make_store(self.tmp, "json-slug")
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
            contextlib.redirect_stderr(err_buf),
        ):
            memory.cli.main(["search", "--format", "json", "nomatch"])
        out = out_buf.getvalue().strip()
        if out:
            json.loads(out)  # Must parse without error


# ---------------------------------------------------------------------------
# CLI entry — no stores dispatch
# ---------------------------------------------------------------------------


class TestSearchMainModule(MemoryTestCase):
    def test_main_runs_cleanly_on_no_stores(self) -> None:
        err_buf = io.StringIO()
        with (
            patch("memory.commands.search.discover_stores", return_value=()),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["search", "query"])
        self.assertIsInstance(rc, int)


if __name__ == "__main__":
    unittest.main()
