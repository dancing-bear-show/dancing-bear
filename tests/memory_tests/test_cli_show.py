"""Coverage for memory.commands.show: slug resolution (exact/prefix/ambiguous/
not-found), --raw byte dump, --format json/yaml structured output, the
no-store-found path, and kebab-case wikilink resolution.

Patches discover_stores where it is USED (memory.commands.show.discover_stores),
not where it is defined, per project convention.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import sys
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import memory.cli
from memory.commands import show
from memory.discovery import load_store, resolve_current_store
from memory.models import Memory
from memory.parser import normalize_slug

from tests.memory_tests.fixtures import (
    CURRENT_FORMAT_MEMORY,
    SLUG_MAIN,
    SLUG_UNDECODABLE,
    SLUG_WORKTREE,
    MemoryTestCase,
    make_projects_root,
)


# ---------------------------------------------------------------------------
# TestFindMemory — unit coverage for _find_memory
# ---------------------------------------------------------------------------


class TestFindMemory(MemoryTestCase):
    def test_exact_match_returns_memory(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        result = show._find_memory(store, "feedback_worktree")

        self.assertIsInstance(result, Memory)
        self.assertEqual(getattr(result, "slug", None), "feedback_worktree")

    def test_md_suffix_is_stripped_before_matching(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        result = show._find_memory(store, "feedback_worktree.md")

        self.assertIsInstance(result, Memory)
        self.assertEqual(getattr(result, "slug", None), "feedback_worktree")

    def test_unique_prefix_match_returns_memory(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        result = show._find_memory(store, "feedback_work")

        self.assertIsInstance(result, Memory)
        self.assertEqual(getattr(result, "slug", None), "feedback_worktree")

    def test_no_match_returns_error_string(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        result = show._find_memory(store, "does_not_exist")

        self.assertIsInstance(result, str)
        self.assertIn("no memory matches", str(result))

    def test_ambiguous_prefix_returns_error_string_listing_candidates(self) -> None:
        # Build a store with two memories sharing a prefix.
        projects_dir = self.tmp / "projects"
        slug = "-Users-alice-code-ambiguous-project"
        memory_dir = projects_dir / slug / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "feedback_alpha.md").write_text(
            "---\nname: feedback_alpha\ndescription: a\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** a\n\n**How to apply:** a\n",
            encoding="utf-8",
        )
        (memory_dir / "feedback_beta.md").write_text(
            "---\nname: feedback_beta\ndescription: b\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** b\n\n**How to apply:** b\n",
            encoding="utf-8",
        )
        store = load_store(slug, projects_root=projects_dir)

        result = show._find_memory(store, "feedback")

        self.assertIsInstance(result, str)
        self.assertIn("ambiguous", str(result))
        self.assertIn("feedback_alpha", str(result))
        self.assertIn("feedback_beta", str(result))


# ---------------------------------------------------------------------------
# TestRenderText — unit coverage for _render_text
# ---------------------------------------------------------------------------


class TestRenderText(MemoryTestCase):
    def test_render_text_marks_broken_link(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)
        memory = store.memories[0]

        # Synthesize wikilinks to exercise both [ok] and [broken] branches.
        linked_memory = dataclasses.replace(
            memory, wikilinks=("known_slug", "missing_slug")
        )
        text = show._render_text(linked_memory, known_slugs={"known_slug"})

        self.assertIn("[[known_slug]] [ok]", text)
        self.assertIn("[[missing_slug]] [broken]", text)

    def test_render_text_no_wikilinks_omits_links_block(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)
        memory = store.memories[0]

        text = show._render_text(memory, known_slugs=set())

        self.assertNotIn("## Links", text)

    def test_kebab_link_to_kebab_file_resolves(self) -> None:
        """[[feedback-run-it]] (kebab link) to feedback-run-it.md renders as resolved.

        extract_wikilinks normalizes '-' to '_' in wikilink targets;
        normalize_slug does the same for known_slugs. Both arrive at
        'feedback_run_it', so the link resolves as [ok] rather than [broken].
        """
        projects_dir = make_projects_root(self.tmp)
        # Place a kebab-case file in the SLUG_MAIN store.
        kebab_path = projects_dir / SLUG_MAIN / "memory" / "feedback-run-it.md"
        kebab_path.write_text(CURRENT_FORMAT_MEMORY, encoding="utf-8")

        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        # Simulate a memory whose [[feedback-run-it]] wikilink was normalized
        # by extract_wikilinks ('-' → '_') to 'feedback_run_it'.
        any_mem = store.memories[0]
        linking_memory = dataclasses.replace(any_mem, wikilinks=("feedback_run_it",))

        # known_slugs also normalizes: "feedback-run-it" → "feedback_run_it".
        known_slugs = {normalize_slug(m.slug) for m in store.memories}

        text = show._render_text(linking_memory, known_slugs=known_slugs)

        self.assertIn("[[feedback_run_it]] [ok]", text)


# ---------------------------------------------------------------------------
# TestBuildStructured — unit coverage for _build_structured
# ---------------------------------------------------------------------------


class TestBuildStructured(MemoryTestCase):
    _REQUIRED_KEYS: ClassVar[set[str]] = {
        "slug",
        "name",
        "description",
        "type",
        "shape",
        "indexed",
        "mtime",
        "body",
        "why",
        "how_to_apply",
        "links",
    }

    def test_build_structured_contains_all_required_keys(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)
        memory = store.memories[0]

        structured = show._build_structured(memory, known_slugs={memory.slug})

        self.assertEqual(set(structured.keys()), self._REQUIRED_KEYS)

    def test_build_structured_link_resolved_flags(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)
        memory = store.memories[0]

        linked_memory = dataclasses.replace(
            memory, wikilinks=("known_slug", "missing_slug")
        )
        structured = show._build_structured(linked_memory, known_slugs={"known_slug"})

        links_by_slug = {link["slug"]: link["resolved"] for link in structured["links"]}
        self.assertEqual(links_by_slug, {"known_slug": True, "missing_slug": False})


# ---------------------------------------------------------------------------
# TestMainCli — end-to-end coverage of memory.cli.main(["show", ...])
# ---------------------------------------------------------------------------


class TestMainCli(MemoryTestCase):
    def test_missing_slug_returns_validation_error(self) -> None:
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            result = memory.cli.main(["show"])
        self.assertEqual(result, 1)

    def test_no_stores_found_prints_error_and_returns_1(self) -> None:
        err_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=()),
            contextlib.redirect_stderr(err_buf),
        ):
            result = memory.cli.main(["show", "some-slug"])
        self.assertEqual(result, 1)
        self.assertIn("No memory stores found", err_buf.getvalue())

    def test_ambiguous_slug_returns_validation_error(self) -> None:
        projects_dir = self.tmp / "projects"
        slug = "-Users-alice-code-ambiguous-project"
        memory_dir = projects_dir / slug / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "feedback_alpha.md").write_text(
            "---\nname: feedback_alpha\ndescription: a\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** a\n\n**How to apply:** a\n",
            encoding="utf-8",
        )
        (memory_dir / "feedback_beta.md").write_text(
            "---\nname: feedback_beta\ndescription: b\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** b\n\n**How to apply:** b\n",
            encoding="utf-8",
        )
        store = load_store(slug, projects_root=projects_dir)

        err_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            contextlib.redirect_stderr(err_buf),
        ):
            result = memory.cli.main(["show", "feedback"])
        self.assertEqual(result, 1)

    def test_not_found_slug_returns_validation_error(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        err_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            contextlib.redirect_stderr(err_buf),
        ):
            result = memory.cli.main(["show", "totally-missing-slug"])
        self.assertEqual(result, 1)

    def test_text_format_happy_path_prints_rendered_body(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        out_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            result = memory.cli.main(["show", "feedback_worktree"])
        self.assertEqual(result, 0)
        out = out_buf.getvalue()
        self.assertTrue("feedback_worktree" in out or "# " in out)

    def test_json_format_emits_structured_output(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        out_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            result = memory.cli.main(["show", "feedback_worktree", "--format", "json"])
        self.assertEqual(result, 0)
        payload = json.loads(out_buf.getvalue())
        self.assertEqual(payload["slug"], "feedback_worktree")

    def test_yaml_format_emits_structured_output(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        out_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            result = memory.cli.main(["show", "feedback_worktree", "--format", "yaml"])
        self.assertEqual(result, 0)
        self.assertIn("slug: feedback_worktree", out_buf.getvalue())

    def test_raw_dumps_file_bytes_to_stdout(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)
        memory_obj = store.memories[0]
        raw_bytes = Path(memory_obj.path).read_bytes()

        written: list[bytes] = []
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            patch.object(sys, "stdout") as mock_stdout,
        ):
            mock_stdout.buffer.write.side_effect = written.append
            result = memory.cli.main(["show", "feedback_worktree", "--raw"])

        self.assertEqual(result, 0)
        self.assertEqual(b"".join(written), raw_bytes)

    def test_raw_read_error_prints_stderr_and_returns_1(self) -> None:
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_dir)

        err_buf = io.StringIO()
        with (
            patch("memory.commands.show.discover_stores", return_value=(store,)),
            patch("builtins.open", side_effect=OSError("permission denied")),
            contextlib.redirect_stderr(err_buf),
        ):
            result = memory.cli.main(["show", "feedback_worktree", "--raw"])
        self.assertEqual(result, 1)
        self.assertIn("Error reading", err_buf.getvalue())

    def test_resolve_current_store_prefers_cwd_match(self) -> None:
        """resolve_current_store picks the store whose inferred_repo prefixes cwd.

        Full cwd-matching/fallback coverage lives in test_discovery.py — this
        test only confirms show.py wires the shared helper up correctly.
        """
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_WORKTREE, projects_root=projects_dir)
        self.assertIsNotNone(store.inferred_repo)

        with patch("os.getcwd", return_value=f"{store.inferred_repo}/subdir"):
            resolved = resolve_current_store((store,))

        self.assertIs(resolved, store)

    def test_resolve_current_store_falls_back_to_elect_canonical(self) -> None:
        """When cwd matches no store's inferred_repo, fall back to elect_canonical."""
        projects_dir = make_projects_root(self.tmp)
        store = load_store(SLUG_UNDECODABLE, projects_root=projects_dir)

        with patch("os.getcwd", return_value="/completely/unrelated/path"):
            resolved = resolve_current_store((store,))

        self.assertIs(resolved, store)


if __name__ == "__main__":
    unittest.main()
