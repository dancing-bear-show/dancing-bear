"""Covers CHECK_REGISTRY completeness, run_checks contract, exit-code mapping, and specific check behaviors."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from memory.models import IndexEntry, MemoryStore
from memory.validation import CHECK_REGISTRY, CheckResult, run_checks
from tests.memory_tests.fixtures import (
    CURRENT_FORMAT_INDEX,
    CURRENT_FORMAT_MEMORY,
    MemoryTestCase,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(tmp_path: Path, slug: str, content: str):
    from memory.parser import parse_memory_file

    f = tmp_path / f"{slug}.md"
    f.write_text(content, encoding="utf-8")
    return parse_memory_file(f, project_slug="test-slug")


def _make_store(
    tmp_path: Path,
    memories=(),
    non_memory_files=(),
    index_entries=(),
    index_path: str | None = None,
) -> MemoryStore:
    return MemoryStore(
        project_slug="test-slug",
        root=str(tmp_path),
        memories=tuple(memories),
        non_memory_files=tuple(non_memory_files),
        index_path=index_path,
        index_entries=tuple(index_entries),
        inferred_repo=None,
        is_worktree_slug=False,
    )


# ---------------------------------------------------------------------------
# CHECK_REGISTRY completeness assertions
# ---------------------------------------------------------------------------


class TestCheckRegistryCompleteness(unittest.TestCase):
    EXPECTED_CHECK_IDS: ClassVar[set[str]] = {
        "staleness",
        "index-orphan",
        "index-dangling",
        "index-duplicate-entry",
        "index-duplicate-section",
        "index-hook-drift",
        "contradiction-topic-overlap",
        "schema-no-frontmatter",
        "schema-missing-type",
        "schema-ambiguous",
        "schema-flat-dialect",
        "schema-unknown-key",
        "schema-name-slug-mismatch",
        "ref-broken-wikilink",
        "ref-dead-path",
        "ref-dead-cli",
        "stale-superseded-pr",
    }

    FORBIDDEN_CHECK_IDS: ClassVar[set[str]] = {
        "duplicate-pr",
        "contradiction-fix",
        "graduate",
    }

    def test_all_expected_checks_registered(self) -> None:
        for check_id in self.EXPECTED_CHECK_IDS:
            with self.subTest(check_id=check_id):
                self.assertIn(
                    check_id,
                    CHECK_REGISTRY,
                    f"Expected check {check_id!r} missing from CHECK_REGISTRY",
                )

    def test_phase2_checks_not_registered(self) -> None:
        """Checks that must never appear in CHECK_REGISTRY (invalid / removed concepts)."""
        for check_id in self.FORBIDDEN_CHECK_IDS:
            with self.subTest(check_id=check_id):
                self.assertNotIn(
                    check_id,
                    CHECK_REGISTRY,
                    f"Check {check_id!r} must not be in CHECK_REGISTRY",
                )

    def test_check_registry_contains_only_callables(self) -> None:
        for check_id, fn in CHECK_REGISTRY.items():
            with self.subTest(check_id=check_id):
                self.assertTrue(callable(fn), f"CHECK_REGISTRY[{check_id!r}] must be callable")


# ---------------------------------------------------------------------------
# run_checks contract
# ---------------------------------------------------------------------------


class TestRunChecksContract(MemoryTestCase):
    def test_returns_tuple(self) -> None:
        store = _make_store(self.tmp)
        result = run_checks(store)
        self.assertIsInstance(result, tuple)

    def test_empty_store_returns_empty_or_info_only(self) -> None:
        store = _make_store(self.tmp)
        result = run_checks(store)
        non_info = [r for r in result if r.severity not in ("info",)]
        self.assertEqual(
            len(non_info),
            0,
            f"Empty store should produce no warn/error findings, got {non_info}",
        )

    def test_unknown_check_id_raises_value_error(self) -> None:
        store = _make_store(self.tmp)
        with self.assertRaises(ValueError) as ctx:
            run_checks(store, checks=("nonexistent-check-id",))
        self.assertIn("unknown check id", str(ctx.exception))

    def test_check_result_fields_present(self) -> None:
        """Every CheckResult in any result set must have all required fields."""
        m = _make_memory(
            self.tmp,
            "orphan_test",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(), index_path=None)
        results = run_checks(store, checks=("index-orphan",))

        for r in results:
            with self.subTest(r=r):
                self.assertIsInstance(r, CheckResult)
                self.assertIn(r.check_id, CHECK_REGISTRY)
                self.assertIn(r.severity, ("error", "warn", "info"))
                self.assertIsInstance(r.target, str)
                self.assertIsInstance(r.message, str)
                self.assertIsInstance(r.fixable, bool)
                self.assertTrue(r.detail is None or isinstance(r.detail, str))

    def test_subset_checks_respected(self) -> None:
        store = _make_store(self.tmp)
        results = run_checks(store, checks=("staleness",))
        check_ids = {r.check_id for r in results}
        self.assertLessEqual(
            check_ids,
            {"staleness"},
            f"Got unexpected check ids: {check_ids - {'staleness'}}",
        )


# ---------------------------------------------------------------------------
# Specific check behaviors
# ---------------------------------------------------------------------------


class TestIndexOrphan(MemoryTestCase):
    def test_orphan_detected(self) -> None:
        m = _make_memory(
            self.tmp,
            "orphan_mem",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\n**Why:** Test.\n\n**How to apply:** Test.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("index-orphan",))
        orphan_results = [r for r in results if r.check_id == "index-orphan"]
        self.assertEqual(len(orphan_results), 1)
        self.assertEqual(orphan_results[0].severity, "warn")
        self.assertTrue(orphan_results[0].fixable)

    def test_indexed_memory_no_orphan(self) -> None:
        m = _make_memory(
            self.tmp,
            "indexed_mem",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\n**Why:** Test.\n\n**How to apply:** Test.\n",
        )
        entry = IndexEntry(
            target="indexed_mem.md",
            title="Indexed Mem",
            hook="hook",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(entry,))
        results = run_checks(store, checks=("index-orphan",))
        orphan_results = [r for r in results if r.check_id == "index-orphan"]
        self.assertEqual(orphan_results, [])


class TestIndexDangling(MemoryTestCase):
    def test_dangling_detected(self) -> None:
        entry = IndexEntry(
            target="nonexistent.md",
            title="Ghost",
            hook="hook",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, index_entries=(entry,))
        results = run_checks(store, checks=("index-dangling",))
        dangling = [r for r in results if r.check_id == "index-dangling"]
        self.assertEqual(len(dangling), 1)
        self.assertEqual(dangling[0].target, "nonexistent.md")
        self.assertEqual(dangling[0].severity, "warn")
        self.assertTrue(dangling[0].fixable)


class TestIndexDuplicateEntry(MemoryTestCase):
    def test_duplicate_entry_detected(self) -> None:
        entry1 = IndexEntry(
            target="dup.md", title="Dup", hook="h", section="Feedback", line_no=2
        )
        entry2 = IndexEntry(
            target="dup.md", title="Dup2", hook="h2", section="Feedback", line_no=4
        )
        store = _make_store(self.tmp, index_entries=(entry1, entry2))
        results = run_checks(store, checks=("index-duplicate-entry",))
        dup_entries = [r for r in results if r.check_id == "index-duplicate-entry"]
        self.assertEqual(len(dup_entries), 1)
        self.assertEqual(dup_entries[0].target, "dup.md")


class TestIndexDuplicateSection(MemoryTestCase):
    def test_duplicate_section_detected(self) -> None:
        """A '## Reference' header appearing twice in the real file must fire."""
        index_path = self.tmp / "MEMORY.md"
        index_path.write_text(
            "## Reference\n"
            "- [a.md](a.md) — first\n"
            "## Reference\n"
            "- [b.md](b.md) — second\n",
            encoding="utf-8",
        )
        entry1 = IndexEntry(
            target="a.md", title="A", hook="h", section="Reference", line_no=2
        )
        entry2 = IndexEntry(
            target="b.md", title="B", hook="h", section="Reference", line_no=4
        )
        store = _make_store(
            self.tmp,
            index_entries=(entry1, entry2),
            index_path=str(index_path),
        )
        results = run_checks(store, checks=("index-duplicate-section",))
        dup_sec = [r for r in results if r.check_id == "index-duplicate-section"]
        self.assertEqual(len(dup_sec), 1)

    def test_multiple_entries_under_one_header_is_not_a_false_positive(self) -> None:
        """Many entries sharing one section NAME under a single header must NOT fire."""
        index_path = self.tmp / "MEMORY.md"
        index_path.write_text(
            "## Reference\n"
            "- [a.md](a.md) — first\n"
            "- [b.md](b.md) — second\n"
            "- [c.md](c.md) — third\n",
            encoding="utf-8",
        )
        entries = tuple(
            IndexEntry(
                target=f"{letter}.md",
                title=letter.upper(),
                hook="h",
                section="Reference",
                line_no=i + 2,
            )
            for i, letter in enumerate(("a", "b", "c"))
        )
        store = _make_store(
            self.tmp,
            index_entries=entries,
            index_path=str(index_path),
        )
        results = run_checks(store, checks=("index-duplicate-section",))
        dup_sec = [r for r in results if r.check_id == "index-duplicate-section"]
        self.assertEqual(dup_sec, [])


class TestSchemaChecks(MemoryTestCase):
    def test_schema_missing_type_detected(self) -> None:
        from memory.models import Memory, MemoryFrontmatter, SchemaShape

        fm = MemoryFrontmatter(
            name="typeless",
            description="no type field",
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.FLAT,
        )
        mem = Memory(
            slug="typeless",
            path=str(self.tmp / "typeless.md"),
            project_slug="test-slug",
            frontmatter=fm,
            body="Content.",
            why=None,
            how_to_apply=None,
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=8,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))
        results = run_checks(store, checks=("schema-missing-type",))
        missing = [r for r in results if r.check_id == "schema-missing-type"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].target, "typeless")
        self.assertEqual(missing[0].severity, "warn")

    def test_schema_flat_dialect_detected(self) -> None:
        m = _make_memory(
            self.tmp,
            "flat_mem",
            "---\ntype: feedback\nname: flat_mem\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-flat-dialect",))
        flat_results = [r for r in results if r.check_id == "schema-flat-dialect"]
        self.assertEqual(len(flat_results), 1)
        self.assertEqual(flat_results[0].severity, "info")
        self.assertFalse(flat_results[0].fixable)

    def test_schema_unknown_key_detected(self) -> None:
        m = _make_memory(
            self.tmp,
            "unknown_key_mem",
            "---\ntype: feedback\nname: nm\nfuture_field: future_val\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-unknown-key",))
        unknown = [r for r in results if r.check_id == "schema-unknown-key"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].severity, "info")

    def test_schema_name_slug_mismatch_detected(self) -> None:
        m = _make_memory(
            self.tmp,
            "my_slug",
            "---\ntype: feedback\nname: Totally Different Name\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-name-slug-mismatch",))
        mismatch = [r for r in results if r.check_id == "schema-name-slug-mismatch"]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0].severity, "info")


class TestRefChecks(MemoryTestCase):
    def test_ref_broken_wikilink_detected(self) -> None:
        m = _make_memory(
            self.tmp,
            "ref_mem",
            "---\ntype: feedback\n---\n\nSee [[broken_wikilink_target]] for more.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-broken-wikilink",))
        broken = [r for r in results if r.check_id == "ref-broken-wikilink"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0].severity, "warn")

    def test_ref_known_wikilink_no_finding(self) -> None:
        m1 = _make_memory(
            self.tmp,
            "mem_one",
            "---\ntype: feedback\n---\n\nSee [[mem_two]] for more.\n",
        )
        m2 = _make_memory(
            self.tmp,
            "mem_two",
            "---\ntype: feedback\n---\n\nI exist.\n",
        )
        store = _make_store(self.tmp, memories=(m1, m2))
        results = run_checks(store, checks=("ref-broken-wikilink",))
        broken = [r for r in results if r.check_id == "ref-broken-wikilink"]
        self.assertEqual(broken, [])

    def test_ref_dead_path_skipped_without_repo(self) -> None:
        """ref-dead-path requires repo= kwarg; without it returns no results."""
        m = _make_memory(
            self.tmp,
            "path_mem",
            "---\ntype: feedback\n---\n\nSee src/core/nonexistent/file.py for details.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-path",))
        dead_path = [r for r in results if r.check_id == "ref-dead-path"]
        self.assertEqual(dead_path, [])


# ---------------------------------------------------------------------------
# Exit-code mapping contract
# ---------------------------------------------------------------------------


class TestExitCodeMapping(MemoryTestCase):
    """The exit-code contract is: 0=no warn/error, 1=warn only, 2=any error."""

    def _exit_code_for(self, results: tuple[CheckResult, ...]) -> int:
        severities = {r.severity for r in results}
        if "error" in severities:
            return 2
        if "warn" in severities:
            return 1
        return 0

    def test_exit_code_mapping(self) -> None:
        cases = [("clean", 0), ("warn_only", 1), ("has_error", 2)]
        for fixture_kind, expected_code in cases:
            with self.subTest(fixture_kind=fixture_kind):
                if fixture_kind == "clean":
                    store = _make_store(self.tmp)
                    results = run_checks(store)
                    code = self._exit_code_for(results)
                elif fixture_kind == "warn_only":
                    m = _make_memory(
                        self.tmp,
                        "orphan_warn",
                        "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\n**Why:** T.\n\n**How to apply:** T.\n",
                    )
                    store = _make_store(self.tmp, memories=(m,))
                    results = run_checks(store, checks=("index-orphan",))
                    code = self._exit_code_for(results)
                elif fixture_kind == "has_error":
                    error_result = CheckResult(
                        check_id="staleness",
                        severity="error",
                        target="test-slug",
                        message="simulated error",
                        fixable=False,
                    )
                    code = self._exit_code_for((error_result,))
                else:
                    raise ValueError(f"Unknown fixture_kind: {fixture_kind!r}")

                self.assertEqual(
                    code,
                    expected_code,
                    f"Expected exit code {expected_code} for {fixture_kind!r}, got {code}",
                )


# ---------------------------------------------------------------------------
# Fix application paths (fix=True)
# ---------------------------------------------------------------------------


class TestFixApplication(MemoryTestCase):
    def test_fix_index_orphan_adds_entry(self) -> None:
        """fix=True for index-orphan must append the orphaned memory to MEMORY.md."""
        index_file = self.tmp / "MEMORY.md"
        index_file.write_text("## Feedback\n", encoding="utf-8")

        m = _make_memory(
            self.tmp,
            "orphan_fix_test",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\nname: orphan_fix_test\ndescription: orphan fix test\n---\n\n**Why:** Test.\n\n**How to apply:** Test.\n",
        )
        store = MemoryStore(
            project_slug="test-slug",
            root=str(self.tmp),
            memories=(m,),
            non_memory_files=(),
            index_path=str(index_file),
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )

        results = run_checks(store, checks=("index-orphan",), fix=True)
        orphan_results = [r for r in results if r.check_id == "index-orphan"]
        self.assertEqual(len(orphan_results), 1)

        content = index_file.read_text(encoding="utf-8")
        self.assertIn("orphan_fix_test.md", content)

    def test_fix_index_dangling_removes_entry(self) -> None:
        """fix=True for index-dangling must remove the entry for the missing file."""
        index_file = self.tmp / "MEMORY.md"
        index_file.write_text(
            "## Feedback\n- [ghost.md](ghost.md) — ghost entry\n",
            encoding="utf-8",
        )

        entry = IndexEntry(
            target="ghost.md",
            title="ghost.md",
            hook="ghost entry",
            section="Feedback",
            line_no=2,
        )
        store = MemoryStore(
            project_slug="test-slug",
            root=str(self.tmp),
            memories=(),
            non_memory_files=(),
            index_path=str(index_file),
            index_entries=(entry,),
            inferred_repo=None,
            is_worktree_slug=False,
        )

        results = run_checks(store, checks=("index-dangling",), fix=True)
        dangling_results = [r for r in results if r.check_id == "index-dangling"]
        self.assertEqual(len(dangling_results), 1)

        content = index_file.read_text(encoding="utf-8")
        self.assertNotIn("ghost.md", content)

    def test_fix_index_duplicate_section_merges(self) -> None:
        """fix=True for index-duplicate-section must merge duplicate sections."""
        index_file = self.tmp / "MEMORY.md"
        index_file.write_text(
            "## Feedback\n- [a.md](a.md) — first\n## Feedback\n- [b.md](b.md) — second\n",
            encoding="utf-8",
        )
        entry1 = IndexEntry(
            target="a.md", title="a.md", hook="first", section="Feedback", line_no=2
        )
        entry2 = IndexEntry(
            target="b.md", title="b.md", hook="second", section="Feedback", line_no=4
        )

        store = MemoryStore(
            project_slug="test-slug",
            root=str(self.tmp),
            memories=(),
            non_memory_files=(),
            index_path=str(index_file),
            index_entries=(entry1, entry2),
            inferred_repo=None,
            is_worktree_slug=False,
        )

        run_checks(store, checks=("index-duplicate-section",), fix=True)

        content = index_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("## Feedback"), 1)

    def test_check_exception_surfaces_as_error_result(self) -> None:
        """A check that raises an exception must surface as an error-severity CheckResult."""
        store = _make_store(self.tmp)

        def _broken_check(s, ctx):
            raise RuntimeError("something went very wrong")

        with patch.dict("memory.validation.CHECK_REGISTRY", {"staleness": _broken_check}):
            results = run_checks(store, checks=("staleness",))

        error_results = [r for r in results if r.severity == "error"]
        self.assertEqual(len(error_results), 1)
        self.assertIn("staleness", error_results[0].check_id)
        self.assertIn("something went very wrong", error_results[0].message)

    def test_fix_schema_missing_type_inserts_into_existing_frontmatter(self) -> None:
        """fix=True for schema-missing-type must insert a type: line into an
        existing frontmatter block, backing up the original file first."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape

        mem_path = self.tmp / "feedback_typeless.md"
        mem_path.write_text(
            "---\nname: feedback_typeless\ndescription: no type field\n---\n\nBody.\n",
            encoding="utf-8",
        )
        fm = MemoryFrontmatter(
            name="feedback_typeless",
            description="no type field",
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.FLAT,
        )
        mem = Memory(
            slug="feedback_typeless",
            path=str(mem_path),
            project_slug="test-slug",
            frontmatter=fm,
            body="Body.",
            why=None,
            how_to_apply=None,
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=mem_path.stat().st_size,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))

        results = run_checks(store, checks=("schema-missing-type",), fix=True)
        missing = [r for r in results if r.check_id == "schema-missing-type"]
        self.assertEqual(len(missing), 1)

        rewritten = mem_path.read_text(encoding="utf-8")
        self.assertIn("type: feedback", rewritten)

        backup_path = mem_path.with_suffix(mem_path.suffix + ".bak")
        self.assertTrue(backup_path.exists())
        self.assertNotIn("type:", backup_path.read_text(encoding="utf-8"))

    def test_fix_schema_missing_type_prepends_frontmatter_when_absent(self) -> None:
        """fix=True for schema-missing-type on a body with no frontmatter block
        at all must prepend a fresh --- type: ... --- block."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape

        mem_path = self.tmp / "project_typeless.md"
        mem_path.write_text("No frontmatter here, just body text.\n", encoding="utf-8")
        fm = MemoryFrontmatter(
            name="project_typeless",
            description="no type field",
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.FLAT,
        )
        mem = Memory(
            slug="project_typeless",
            path=str(mem_path),
            project_slug="test-slug",
            frontmatter=fm,
            body="No frontmatter here, just body text.",
            why=None,
            how_to_apply=None,
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=mem_path.stat().st_size,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))

        run_checks(store, checks=("schema-missing-type",), fix=True)

        rewritten = mem_path.read_text(encoding="utf-8")
        self.assertTrue(rewritten.startswith("---\ntype: project\n---\n\n"))
        self.assertIn("No frontmatter here", rewritten)

    def test_fix_schema_no_frontmatter_archives_file(self) -> None:
        """fix=True for schema-no-frontmatter must back up and move the
        offending file into an _archive/ subdirectory."""
        from memory.validation import _FIXERS

        raw_path = self.tmp / "no_frontmatter.md"
        raw_path.write_text(
            "Just a plain markdown file, no frontmatter.\n", encoding="utf-8"
        )
        store = _make_store(self.tmp, non_memory_files=(str(raw_path),))

        finding = CheckResult(
            check_id="schema-no-frontmatter",
            severity="warn",
            target=str(raw_path),
            message="no frontmatter",
            fixable=True,
        )

        _FIXERS["schema-no-frontmatter"](store, (finding,))

        self.assertFalse(raw_path.exists())
        archived = self.tmp / "_archive" / "no_frontmatter.md"
        self.assertTrue(archived.exists())
        backup_path = raw_path.with_suffix(raw_path.suffix + ".bak")
        self.assertTrue(backup_path.exists())


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize(unittest.TestCase):
    def test_tokenize_lowercases_and_splits(self) -> None:
        from memory.validation import _tokenize

        result = _tokenize("Hello World 123")
        self.assertEqual(result, {"hello", "world", "123"})

    def test_tokenize_empty_string(self) -> None:
        from memory.validation import _tokenize

        result = _tokenize("")
        self.assertEqual(result, set())

    def test_tokenize_punctuation_only(self) -> None:
        from memory.validation import _tokenize

        result = _tokenize("!!! --- ???")
        self.assertEqual(result, set())


# ---------------------------------------------------------------------------
# _check_index_hook_drift
# ---------------------------------------------------------------------------


class TestIndexHookDrift(MemoryTestCase):
    def test_hook_drift_detected_when_no_shared_tokens(self) -> None:
        m = _make_memory(
            self.tmp,
            "drift_mem",
            "---\ntype: feedback\nname: drift_mem\ndescription: worktree isolation strategy for branches\n---\n\nBody.\n",
        )
        entry = IndexEntry(
            target="drift_mem.md",
            title="Drift Mem",
            hook="unrelated xyz completely different",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(entry,))
        results = run_checks(store, checks=("index-hook-drift",))
        drift = [r for r in results if r.check_id == "index-hook-drift"]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0].severity, "info")
        self.assertFalse(drift[0].fixable)
        self.assertIsNotNone(drift[0].detail)
        self.assertIn("hook=", drift[0].detail or "")
        self.assertIn("description=", drift[0].detail or "")

    def test_hook_drift_no_finding_when_tokens_overlap(self) -> None:
        m = _make_memory(
            self.tmp,
            "aligned_mem",
            "---\ntype: feedback\nname: aligned_mem\ndescription: memory isolation strategy\n---\n\nBody.\n",
        )
        entry = IndexEntry(
            target="aligned_mem.md",
            title="Aligned Mem",
            hook="memory isolation policy",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(entry,))
        results = run_checks(store, checks=("index-hook-drift",))
        drift = [r for r in results if r.check_id == "index-hook-drift"]
        self.assertEqual(drift, [])

    def test_hook_drift_skipped_when_no_index_entry(self) -> None:
        """Memory with no corresponding index entry must produce no hook-drift finding."""
        m = _make_memory(
            self.tmp,
            "unindexed_drift",
            "---\ntype: feedback\nname: unindexed_drift\ndescription: some description\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=())
        results = run_checks(store, checks=("index-hook-drift",))
        drift = [r for r in results if r.check_id == "index-hook-drift"]
        self.assertEqual(drift, [])

    def test_hook_drift_skipped_when_no_description(self) -> None:
        """Memory without a frontmatter description must produce no hook-drift finding."""
        m = _make_memory(
            self.tmp,
            "nodesc_mem",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        entry = IndexEntry(
            target="nodesc_mem.md",
            title="No Desc",
            hook="completely unrelated hook words",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(entry,))
        results = run_checks(store, checks=("index-hook-drift",))
        drift = [r for r in results if r.check_id == "index-hook-drift"]
        self.assertEqual(drift, [])

    def test_hook_drift_skipped_when_hook_tokenizes_to_empty(self) -> None:
        """When the index entry hook has no alphanumeric tokens, skip the comparison."""
        m = _make_memory(
            self.tmp,
            "empty_hook_mem",
            "---\ntype: feedback\nname: empty_hook_mem\ndescription: memory isolation strategy\n---\n\nBody.\n",
        )
        entry = IndexEntry(
            target="empty_hook_mem.md",
            title="Empty Hook",
            hook="--- --- ---",
            section="Feedback",
            line_no=2,
        )
        store = _make_store(self.tmp, memories=(m,), index_entries=(entry,))
        results = run_checks(store, checks=("index-hook-drift",))
        drift = [r for r in results if r.check_id == "index-hook-drift"]
        self.assertEqual(drift, [])


# ---------------------------------------------------------------------------
# _check_contradiction_topic_overlap
# ---------------------------------------------------------------------------


class TestContradictionTopicOverlap(MemoryTestCase):
    def test_overlap_detected_when_anchor_in_claude_md(self) -> None:
        """An anchor mentioned in both the memory body and a CLAUDE.md-style file fires."""
        claude_file = self.tmp / "CLAUDE.md"
        claude_file.write_text(
            "# Project rules\n\nUse `worktree` isolation for all agents.\n",
            encoding="utf-8",
        )
        m = _make_memory(
            self.tmp,
            "overlap_mem",
            "---\ntype: feedback\n---\n\nAlways use `worktree` isolation.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(
            store,
            checks=("contradiction-topic-overlap",),
            claude_md=(str(claude_file),),
        )
        overlaps = [r for r in results if r.check_id == "contradiction-topic-overlap"]
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0].severity, "info")
        self.assertFalse(overlaps[0].fixable)
        self.assertIn("worktree", overlaps[0].message)
        self.assertIsNotNone(overlaps[0].detail)
        self.assertIn("memory:", overlaps[0].detail or "")
        self.assertIn("claude_md:", overlaps[0].detail or "")

    def test_no_overlap_when_anchors_differ(self) -> None:
        claude_file = self.tmp / "CLAUDE.md"
        claude_file.write_text(
            "# Rules\n\nUse `main` as the base branch.\n",
            encoding="utf-8",
        )
        m = _make_memory(
            self.tmp,
            "no_overlap_mem",
            "---\ntype: feedback\n---\n\nAlways use `worktree` isolation.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(
            store,
            checks=("contradiction-topic-overlap",),
            claude_md=(str(claude_file),),
        )
        overlaps = [r for r in results if r.check_id == "contradiction-topic-overlap"]
        self.assertEqual(overlaps, [])

    def test_no_overlap_when_no_claude_md_paths(self) -> None:
        """When no CLAUDE.md paths are found/given, the check returns empty."""
        m = _make_memory(
            self.tmp,
            "no_claude_mem",
            "---\ntype: feedback\n---\n\nUse `worktree` isolation.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(
            store,
            checks=("contradiction-topic-overlap",),
            claude_md=(str(self.tmp / "DOES_NOT_EXIST.md"),),
        )
        overlaps = [r for r in results if r.check_id == "contradiction-topic-overlap"]
        self.assertEqual(overlaps, [])


# ---------------------------------------------------------------------------
# _check_schema_no_frontmatter
# ---------------------------------------------------------------------------


class TestSchemaNoFrontmatter(MemoryTestCase):
    def test_no_frontmatter_detected_for_plain_md_file(self) -> None:
        """A .md file with no --- block in non_memory_files fires schema-no-frontmatter."""
        raw_path = self.tmp / "plain.md"
        raw_path.write_text("# Just markdown\n\nNo frontmatter.\n", encoding="utf-8")
        store = _make_store(self.tmp, non_memory_files=(str(raw_path),))
        results = run_checks(store, checks=("schema-no-frontmatter",))
        findings = [r for r in results if r.check_id == "schema-no-frontmatter"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warn")
        self.assertTrue(findings[0].fixable)
        self.assertIn("plain.md", findings[0].message)

    def test_no_frontmatter_skipped_for_missing_file(self) -> None:
        """A non_memory_files path that doesn't exist on disk must produce no finding."""
        store = _make_store(self.tmp, non_memory_files=(str(self.tmp / "missing.md"),))
        results = run_checks(store, checks=("schema-no-frontmatter",))
        findings = [r for r in results if r.check_id == "schema-no-frontmatter"]
        self.assertEqual(findings, [])

    def test_no_frontmatter_skipped_for_file_with_frontmatter(self) -> None:
        """A non_memory_files path that DOES have frontmatter must produce no finding."""
        fm_path = self.tmp / "has_fm.md"
        fm_path.write_text("---\nname: something\n---\n\nBody.\n", encoding="utf-8")
        store = _make_store(self.tmp, non_memory_files=(str(fm_path),))
        results = run_checks(store, checks=("schema-no-frontmatter",))
        findings = [r for r in results if r.check_id == "schema-no-frontmatter"]
        self.assertEqual(findings, [])


# ---------------------------------------------------------------------------
# _check_schema_ambiguous
# ---------------------------------------------------------------------------


class TestSchemaAmbiguous(MemoryTestCase):
    def test_ambiguous_detected_when_all_signals_absent(self) -> None:
        """Memory that passes is_memory but has no node_type, no Why/How, no name/description fires."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape

        fm = MemoryFrontmatter(
            name=None,
            description=None,
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.FLAT,
        )
        mem = Memory(
            slug="ambiguous_mem",
            path=str(self.tmp / "ambiguous_mem.md"),
            project_slug="test-slug",
            frontmatter=fm,
            body="Some content without markers.",
            why=None,
            how_to_apply=None,
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=30,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))
        results = run_checks(store, checks=("schema-ambiguous",))
        ambiguous = [r for r in results if r.check_id == "schema-ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0].severity, "warn")
        self.assertFalse(ambiguous[0].fixable)

    def test_ambiguous_not_detected_when_node_type_present(self) -> None:
        """Memory with node_type='memory' must NOT fire schema-ambiguous."""
        m = _make_memory(
            self.tmp,
            "clear_mem",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\n**Why:** Exists.\n\n**How to apply:** Use it.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-ambiguous",))
        ambiguous = [r for r in results if r.check_id == "schema-ambiguous"]
        self.assertEqual(ambiguous, [])

    def test_ambiguous_not_detected_when_one_signal_present(self) -> None:
        """Any single signal (why/how/name/description) prevents schema-ambiguous."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape

        cases = [
            ("Has why text.", None, None, None),
            (None, "Has how text.", None, None),
            (None, None, "has_name", None),
            (None, None, None, "has description"),
        ]
        for why, how_to_apply, name, description in cases:
            with self.subTest(why=why, how_to_apply=how_to_apply, name=name, description=description):
                fm = MemoryFrontmatter(
                    name=name,
                    description=description,
                    type=None,
                    node_type=None,
                    origin_session_id=None,
                    modified=None,
                    shape=SchemaShape.FLAT,
                )
                mem = Memory(
                    slug="partial_signal",
                    path=str(self.tmp / "partial_signal.md"),
                    project_slug="test-slug",
                    frontmatter=fm,
                    body="Content.",
                    why=why,
                    how_to_apply=how_to_apply,
                    wikilinks=(),
                    mtime=datetime.now(UTC),
                    size_bytes=8,
                    indexed=False,
                    index_hook=None,
                    index_section=None,
                )
                store = _make_store(self.tmp, memories=(mem,))
                results = run_checks(store, checks=("schema-ambiguous",))
                ambiguous = [r for r in results if r.check_id == "schema-ambiguous"]
                self.assertEqual(ambiguous, [])


# ---------------------------------------------------------------------------
# schema-name-slug-mismatch: no-name skip
# ---------------------------------------------------------------------------


class TestSchemaNameSlugMismatchNoName(MemoryTestCase):
    def test_no_finding_when_name_is_none(self) -> None:
        """Memory without a frontmatter name must produce no schema-name-slug-mismatch."""
        m = _make_memory(
            self.tmp,
            "unnamed_mem",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-name-slug-mismatch",))
        mismatch = [r for r in results if r.check_id == "schema-name-slug-mismatch"]
        self.assertEqual(mismatch, [])

    def test_no_finding_when_slugified_name_matches_slug(self) -> None:
        """Memory whose name slugifies to the same slug must produce no finding."""
        m = _make_memory(
            self.tmp,
            "my_slug",
            "---\ntype: feedback\nname: my_slug\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-name-slug-mismatch",))
        mismatch = [r for r in results if r.check_id == "schema-name-slug-mismatch"]
        self.assertEqual(mismatch, [])


# ---------------------------------------------------------------------------
# ref-dead-path with repo set
# ---------------------------------------------------------------------------


class TestRefDeadPath(MemoryTestCase):
    def test_dead_path_detected_with_repo(self) -> None:
        """A path mention pointing to a non-existent file under repo must fire."""
        repo_dir = self.tmp / "repo"
        repo_dir.mkdir()
        m = _make_memory(
            self.tmp,
            "dead_path_mem",
            "---\ntype: feedback\n---\n\nSee src/core/nonexistent/module.py for reference.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-path",), repo=str(repo_dir))
        dead = [r for r in results if r.check_id == "ref-dead-path"]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].severity, "warn")
        self.assertFalse(dead[0].fixable)
        self.assertIn("nonexistent", dead[0].message)

    def test_live_path_no_finding_with_repo(self) -> None:
        """A path mention pointing to a real file under repo must produce no finding."""
        repo_dir = self.tmp / "repo"
        live_file = repo_dir / "src" / "myapp" / "existing" / "module.py"
        live_file.parent.mkdir(parents=True)
        live_file.write_text("# exists\n", encoding="utf-8")

        m = _make_memory(
            self.tmp,
            "live_path_mem",
            "---\ntype: feedback\n---\n\nSee src/myapp/existing/module.py for reference.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-path",), repo=str(repo_dir))
        dead = [r for r in results if r.check_id == "ref-dead-path"]
        self.assertEqual(dead, [])

    def test_dead_path_skipped_when_prefix_not_matched(self) -> None:
        """A path not matching the dead-path prefixes must not fire even with repo set."""
        repo_dir = self.tmp / "repo"
        repo_dir.mkdir()
        m = _make_memory(
            self.tmp,
            "other_path_mem",
            "---\ntype: feedback\n---\n\nSee some/other/path/file.py for context.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-path",), repo=str(repo_dir))
        dead = [r for r in results if r.check_id == "ref-dead-path"]
        self.assertEqual(dead, [])


# ---------------------------------------------------------------------------
# ref-dead-cli with repo set
# ---------------------------------------------------------------------------


class TestRefDeadCli(MemoryTestCase):
    def test_dead_cli_detected_with_repo(self) -> None:
        """A ./bin/nonexistent reference with repo set must fire ref-dead-cli."""
        repo_dir = self.tmp / "repo"
        (repo_dir / "bin").mkdir(parents=True)
        m = _make_memory(
            self.tmp,
            "dead_cli_mem",
            "---\ntype: feedback\n---\n\nRun ./bin/nonexistent to start.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-cli",), repo=str(repo_dir))
        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].severity, "warn")
        self.assertFalse(dead[0].fixable)
        self.assertIn("nonexistent", dead[0].message)

    def test_live_cli_no_finding_with_repo(self) -> None:
        """A ./bin/existing reference to a real binary must produce no finding."""
        repo_dir = self.tmp / "repo"
        bin_dir = repo_dir / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "existing-tool").write_text("#!/bin/sh\n", encoding="utf-8")

        m = _make_memory(
            self.tmp,
            "live_cli_mem",
            "---\ntype: feedback\n---\n\nRun ./bin/existing-tool to check status.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-cli",), repo=str(repo_dir))
        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead, [])

    def test_dead_cli_skipped_without_repo(self) -> None:
        """ref-dead-cli must return empty when no repo is set."""
        m = _make_memory(
            self.tmp,
            "cli_no_repo",
            "---\ntype: feedback\n---\n\nRun ./bin/nonexistent-cli to start.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("ref-dead-cli",))
        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead, [])

    def test_dead_cli_fallback_succeeds_when_repo_garbled(self) -> None:
        """When ctx.repo has no bin/ dir, git fallback finds a real bin/ with the CLI."""

        real_repo = self.tmp / "real_repo"
        bin_dir = real_repo / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "existing-tool").write_text("#!/bin/sh\n", encoding="utf-8")

        garbled_repo = self.tmp / "garbled_path_that_does_not_exist"

        m = _make_memory(
            self.tmp,
            "fallback_live",
            "---\ntype: feedback\n---\n\nRun ./bin/existing-tool to check status.\n",
        )
        store = _make_store(self.tmp, memories=(m,))

        with patch("memory.validation.subprocess.check_output") as mock_sub:
            mock_sub.return_value = str(real_repo)
            results = run_checks(
                store, checks=("ref-dead-cli",), repo=str(garbled_repo)
            )

        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead, [])
        mock_sub.assert_called_once()

    def test_dead_cli_fallback_exception_returns_empty(self) -> None:
        """When git rev-parse raises CalledProcessError, _check_ref_dead_cli returns ()."""
        import subprocess

        garbled_repo = self.tmp / "garbled_path_that_does_not_exist"

        m = _make_memory(
            self.tmp,
            "fallback_exc",
            "---\ntype: feedback\n---\n\nRun ./bin/some-tool to check.\n",
        )
        store = _make_store(self.tmp, memories=(m,))

        with patch("memory.validation.subprocess.check_output") as mock_sub:
            mock_sub.side_effect = subprocess.CalledProcessError(1, "git")
            results = run_checks(
                store, checks=("ref-dead-cli",), repo=str(garbled_repo)
            )

        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead, [])

    def test_dead_cli_fallback_bin_still_missing_returns_empty(self) -> None:
        """When git succeeds but the returned path also lacks bin/, returns ()."""
        garbled_repo = self.tmp / "garbled_path_that_does_not_exist"
        also_no_bin = self.tmp / "also_no_bin"
        also_no_bin.mkdir(parents=True)

        m = _make_memory(
            self.tmp,
            "fallback_no_bin",
            "---\ntype: feedback\n---\n\nRun ./bin/some-tool to check.\n",
        )
        store = _make_store(self.tmp, memories=(m,))

        with patch("memory.validation.subprocess.check_output") as mock_sub:
            mock_sub.return_value = str(also_no_bin)
            results = run_checks(
                store, checks=("ref-dead-cli",), repo=str(garbled_repo)
            )

        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead, [])


# ---------------------------------------------------------------------------
# _apply_fix_* no-index_path guard
# ---------------------------------------------------------------------------


class TestFixerNoIndexPath(MemoryTestCase):
    def test_fix_index_orphan_noop_when_no_index_path(self) -> None:
        """_apply_fix_index_orphan must be a no-op when store.index_path is None."""
        from memory.validation import _FIXERS

        m = _make_memory(
            self.tmp,
            "orphan_noop",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        store = _make_store(self.tmp, memories=(m,), index_path=None)
        finding = CheckResult(
            check_id="index-orphan",
            severity="warn",
            target="orphan_noop",
            message="orphan",
            fixable=True,
        )
        _FIXERS["index-orphan"](store, (finding,))

    def test_fix_index_dangling_noop_when_no_index_path(self) -> None:
        """_apply_fix_index_dangling must be a no-op when store.index_path is None."""
        from memory.validation import _FIXERS

        store = _make_store(self.tmp, index_path=None)
        finding = CheckResult(
            check_id="index-dangling",
            severity="warn",
            target="ghost.md",
            message="dangling",
            fixable=True,
        )
        _FIXERS["index-dangling"](store, (finding,))

    def test_fix_index_duplicate_section_noop_when_no_index_path(self) -> None:
        """_apply_fix_index_duplicate_section must be a no-op when store.index_path is None."""
        from memory.validation import _FIXERS

        store = _make_store(self.tmp, index_path=None)
        finding = CheckResult(
            check_id="index-duplicate-section",
            severity="warn",
            target="MEMORY.md",
            message="dup section",
            fixable=True,
        )
        _FIXERS["index-duplicate-section"](store, (finding,))


# ---------------------------------------------------------------------------
# _apply_fix_schema_missing_type: target-not-in-store and unknown-prefix
# ---------------------------------------------------------------------------


class TestFixSchemaTypeSadPaths(MemoryTestCase):
    def test_fix_schema_missing_type_ignores_wrong_check_id(self) -> None:
        """Findings with check_id other than schema-missing-type must be ignored."""
        from memory.validation import _FIXERS

        store = _make_store(self.tmp, memories=())
        finding = CheckResult(
            check_id="index-orphan",
            severity="warn",
            target="some_slug",
            message="wrong check",
            fixable=True,
        )
        _FIXERS["schema-missing-type"](store, (finding,))

    def test_fix_schema_missing_type_noop_when_target_not_in_store(self) -> None:
        """Finding whose target slug does not match any store memory must be a no-op."""
        from memory.validation import _FIXERS

        store = _make_store(self.tmp, memories=())
        finding = CheckResult(
            check_id="schema-missing-type",
            severity="warn",
            target="nonexistent_slug",
            message="no type",
            fixable=True,
        )
        _FIXERS["schema-missing-type"](store, (finding,))

    def test_fix_schema_missing_type_noop_for_unknown_prefix(self) -> None:
        """A memory slug with an unrecognized prefix must produce no file modification."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape
        from memory.validation import _FIXERS

        mem_path = self.tmp / "unknown_typeless.md"
        mem_path.write_text(
            "---\nname: unknown_typeless\ndescription: no type\n---\n\nBody.\n",
            encoding="utf-8",
        )
        original = mem_path.read_text(encoding="utf-8")

        fm = MemoryFrontmatter(
            name="unknown_typeless",
            description="no type",
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.FLAT,
        )
        mem = Memory(
            slug="unknown_typeless",
            path=str(mem_path),
            project_slug="test-slug",
            frontmatter=fm,
            body="Body.",
            why=None,
            how_to_apply=None,
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=mem_path.stat().st_size,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))
        finding = CheckResult(
            check_id="schema-missing-type",
            severity="warn",
            target="unknown_typeless",
            message="no type",
            fixable=True,
        )
        _FIXERS["schema-missing-type"](store, (finding,))

        self.assertEqual(mem_path.read_text(encoding="utf-8"), original)
        self.assertFalse(mem_path.with_suffix(mem_path.suffix + ".bak").exists())


# ---------------------------------------------------------------------------
# _apply_fix_schema_no_frontmatter: wrong check_id and non-file path
# ---------------------------------------------------------------------------


class TestFixSchemaNoFrontmatterSadPaths(MemoryTestCase):
    def test_fix_schema_no_frontmatter_ignores_wrong_check_id(self) -> None:
        """Findings with check_id other than schema-no-frontmatter must be ignored."""
        from memory.validation import _FIXERS

        raw_path = self.tmp / "some_file.md"
        raw_path.write_text("content\n", encoding="utf-8")
        store = _make_store(self.tmp)
        finding = CheckResult(
            check_id="schema-missing-type",
            severity="warn",
            target=str(raw_path),
            message="not this check",
            fixable=True,
        )
        _FIXERS["schema-no-frontmatter"](store, (finding,))
        self.assertTrue(raw_path.exists())

    def test_fix_schema_no_frontmatter_noop_when_file_missing(self) -> None:
        """When the target path doesn't exist, the fixer must not raise."""
        from memory.validation import _FIXERS

        store = _make_store(self.tmp)
        finding = CheckResult(
            check_id="schema-no-frontmatter",
            severity="warn",
            target=str(self.tmp / "nonexistent_file.md"),
            message="no frontmatter",
            fixable=True,
        )
        _FIXERS["schema-no-frontmatter"](store, (finding,))


# ---------------------------------------------------------------------------
# _rewrite_frontmatter_type: nested dialect path
# ---------------------------------------------------------------------------


class TestRewriteFrontmatterTypeNested(MemoryTestCase):
    def test_rewrite_inserts_under_metadata_in_nested_dialect(self) -> None:
        """A file with a nested 'metadata:' block must get type inserted under metadata."""
        from memory.models import Memory, MemoryFrontmatter, SchemaShape
        from memory.validation import _FIXERS

        mem_path = self.tmp / "feedback_nested.md"
        mem_path.write_text(
            "---\nname: feedback_nested\ndescription: nested dialect memory\nmetadata:\n  node_type: memory\n---\n\n**Why:** Test.\n\n**How to apply:** Apply.\n",
            encoding="utf-8",
        )
        fm = MemoryFrontmatter(
            name="feedback_nested",
            description="nested dialect memory",
            type=None,
            node_type="memory",
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.NESTED,
        )
        mem = Memory(
            slug="feedback_nested",
            path=str(mem_path),
            project_slug="test-slug",
            frontmatter=fm,
            body="**Why:** Test.\n\n**How to apply:** Apply.",
            why="Test.",
            how_to_apply="Apply.",
            wikilinks=(),
            mtime=datetime.now(UTC),
            size_bytes=mem_path.stat().st_size,
            indexed=False,
            index_hook=None,
            index_section=None,
        )
        store = _make_store(self.tmp, memories=(mem,))
        finding = CheckResult(
            check_id="schema-missing-type",
            severity="warn",
            target="feedback_nested",
            message="no type",
            fixable=True,
        )
        _FIXERS["schema-missing-type"](store, (finding,))

        rewritten = mem_path.read_text(encoding="utf-8")
        self.assertIn("  type: feedback", rewritten)
        self.assertIn("metadata:", rewritten)

    def test_rewrite_frontmatter_type_no_closing_dashes(self) -> None:
        """A file that starts with --- but has no closing --- falls through to prepend path."""
        from memory.models import MemoryType
        from memory.validation import _rewrite_frontmatter_type

        broken_path = self.tmp / "broken_fm.md"
        broken_path.write_text(
            "---\nname: broken\nno closing dashes here\n",
            encoding="utf-8",
        )
        _rewrite_frontmatter_type(broken_path, MemoryType.PROJECT)

        result = broken_path.read_text(encoding="utf-8")
        self.assertTrue(result.startswith("---\ntype: project\n---\n\n"))


# ---------------------------------------------------------------------------
# run_checks: repo from store.inferred_repo
# ---------------------------------------------------------------------------


class TestRunChecksGivenRepo(MemoryTestCase):
    def test_repo_inferred_from_store(self) -> None:
        """When repo kwarg is None and store.inferred_repo is set, it must be used."""
        repo_dir = self.tmp / "inferred_repo"
        (repo_dir / "bin").mkdir(parents=True)
        (repo_dir / "bin" / "live-tool").write_text("#!/bin/sh\n", encoding="utf-8")

        m = _make_memory(
            self.tmp,
            "inferred_repo_mem",
            "---\ntype: feedback\n---\n\nRun ./bin/dead-cli to check.\n",
        )
        store = MemoryStore(
            project_slug="test-slug",
            root=str(self.tmp),
            memories=(m,),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=str(repo_dir),
            is_worktree_slug=False,
        )
        results = run_checks(store, checks=("ref-dead-cli",))
        dead = [r for r in results if r.check_id == "ref-dead-cli"]
        self.assertEqual(len(dead), 1)
        self.assertIn("dead-cli", dead[0].message)

    def test_repo_kwarg_takes_precedence_over_inferred(self) -> None:
        """When both repo kwarg and store.inferred_repo are set, repo kwarg wins."""
        inferred_dir = self.tmp / "inferred"
        kwarg_dir = self.tmp / "kwarg_repo"
        (inferred_dir / "bin").mkdir(parents=True)
        (kwarg_dir / "bin").mkdir(parents=True)
        (kwarg_dir / "bin" / "the-cli").write_text("#!/bin/sh\n", encoding="utf-8")

        m = _make_memory(
            self.tmp,
            "kwarg_repo_mem",
            "---\ntype: feedback\n---\n\nRun ./bin/the-cli to check.\n",
        )
        store = MemoryStore(
            project_slug="test-slug",
            root=str(self.tmp),
            memories=(m,),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=str(inferred_dir),
            is_worktree_slug=False,
        )
        results_kwarg = run_checks(store, checks=("ref-dead-cli",), repo=str(kwarg_dir))
        dead_kwarg = [r for r in results_kwarg if r.check_id == "ref-dead-cli"]
        self.assertEqual(dead_kwarg, [])

        results_inferred = run_checks(store, checks=("ref-dead-cli",))
        dead_inferred = [r for r in results_inferred if r.check_id == "ref-dead-cli"]
        self.assertEqual(len(dead_inferred), 1)

    def test_claude_md_explicit_paths_override_default_discovery(self) -> None:
        """When claude_md kwarg is given, default CLAUDE.md path discovery is skipped."""
        repo_dir = self.tmp / "repo"
        repo_dir.mkdir()
        (repo_dir / "CLAUDE.md").write_text(
            "Use `worktree` isolation.\n", encoding="utf-8"
        )
        nonexistent_path = str(self.tmp / "DOES_NOT_EXIST.md")

        m = _make_memory(
            self.tmp,
            "override_claude_md",
            "---\ntype: feedback\n---\n\nAlways use `worktree`.\n",
        )
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(
            store,
            checks=("contradiction-topic-overlap",),
            repo=str(repo_dir),
            claude_md=(nonexistent_path,),
        )
        overlaps = [r for r in results if r.check_id == "contradiction-topic-overlap"]
        self.assertEqual(overlaps, [])


# ---------------------------------------------------------------------------
# _check_index_duplicate_section: index_path exists but nonexistent file
# ---------------------------------------------------------------------------


class TestIndexDuplicateSectionPathMissing(MemoryTestCase):
    def test_no_finding_when_index_path_file_does_not_exist(self) -> None:
        """When store.index_path is set but the file doesn't exist, return empty."""
        store = _make_store(
            self.tmp,
            index_path=str(self.tmp / "MISSING_MEMORY.md"),
        )
        results = run_checks(store, checks=("index-duplicate-section",))
        dup = [r for r in results if r.check_id == "index-duplicate-section"]
        self.assertEqual(dup, [])


# ---------------------------------------------------------------------------
# stale-superseded-pr check
# ---------------------------------------------------------------------------

_PROJECT_CONTENT = (
    "---\n"
    "name: {name}\n"
    "description: {desc}\n"
    "metadata:\n"
    "  type: project\n"
    "  node_type: memory\n"
    "---\n\n"
    "**Why:** Testing.\n\n**How to apply:** {body}\n"
)

_FEEDBACK_CONTENT_VAL = (
    "---\n"
    "name: {name}\n"
    "description: {desc}\n"
    "metadata:\n"
    "  type: feedback\n"
    "  node_type: memory\n"
    "---\n\n"
    "**Why:** Testing.\n\n**How to apply:** {body}\n"
)


def _make_project_memory(tmp_path: Path, slug: str, body: str):
    from memory.parser import parse_memory_file

    f = tmp_path / f"{slug}.md"
    content = _PROJECT_CONTENT.format(name=slug, desc="desc", body=body)
    f.write_text(content, encoding="utf-8")
    return parse_memory_file(f, project_slug="test-slug")


class TestStaleSupersededPrCheck(MemoryTestCase):
    def _make_project_memory(self, slug: str, body: str):
        return _make_project_memory(self.tmp, slug, body)

    def _make_feedback_memory(self, slug: str, body: str):
        from memory.parser import parse_memory_file

        f = self.tmp / f"{slug}.md"
        content = _FEEDBACK_CONTENT_VAL.format(name=slug, desc="desc", body=body)
        f.write_text(content, encoding="utf-8")
        return parse_memory_file(f, project_slug="test-slug")

    def test_fires_on_closed_pr(self) -> None:
        from memory.validation import _CheckContext, _check_stale_superseded_pr

        m = self._make_project_memory("project_foo", "See PR #42 for details.")
        store = _make_store(self.tmp, memories=(m,))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)

        results = _check_stale_superseded_pr(
            store, ctx, github_caller=lambda _n: {"state": "closed"}
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_id, "stale-superseded-pr")
        self.assertEqual(results[0].severity, "warn")
        self.assertIn("#42", results[0].message)
        self.assertIn("closed", results[0].message)

    def test_fires_on_merged_pr(self) -> None:
        from memory.validation import _CheckContext, _check_stale_superseded_pr

        m = self._make_project_memory("project_bar", "See PR #99 for details.")
        store = _make_store(self.tmp, memories=(m,))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)

        results = _check_stale_superseded_pr(
            store, ctx, github_caller=lambda _n: {"state": "merged"}
        )
        self.assertEqual(len(results), 1)
        self.assertIn("merged", results[0].message)

    def test_skips_open_pr(self) -> None:
        from memory.validation import _CheckContext, _check_stale_superseded_pr

        m = self._make_project_memory("project_open", "Tracking PR #7.")
        store = _make_store(self.tmp, memories=(m,))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)

        results = _check_stale_superseded_pr(
            store, ctx, github_caller=lambda _n: {"state": "open"}
        )
        self.assertEqual(results, ())

    def test_skips_on_network_failure(self) -> None:
        from memory.validation import _CheckContext, _check_stale_superseded_pr

        m = self._make_project_memory("project_net", "See PR #5.")
        store = _make_store(self.tmp, memories=(m,))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)

        def _failing_caller(n: int) -> dict:
            raise RuntimeError("network unavailable")

        results = _check_stale_superseded_pr(store, ctx, github_caller=_failing_caller)
        self.assertEqual(results, ())

    def test_only_runs_on_project_memories(self) -> None:
        from memory.validation import _CheckContext, _check_stale_superseded_pr

        m = self._make_feedback_memory("feedback_pr", "See PR #123 for details.")
        store = _make_store(self.tmp, memories=(m,))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)

        results = _check_stale_superseded_pr(
            store, ctx, github_caller=lambda _n: {"state": "closed"}
        )
        self.assertEqual(results, ())


# ---------------------------------------------------------------------------
# Sad-path additions
# ---------------------------------------------------------------------------


class TestRunChecksUnknownCheckId(MemoryTestCase):
    """run_checks raises ValueError immediately for any unrecognised check id."""

    def test_mixed_known_and_unknown_raises(self) -> None:
        store = _make_store(self.tmp)
        with self.assertRaises(ValueError) as ctx:
            run_checks(store, checks=("staleness", "totally-bogus-id"))
        self.assertIn("unknown check id", str(ctx.exception))


class TestRunChecksCheckRaisesBecomesErrorFinding(MemoryTestCase):
    """A check function that raises must be captured as an error-severity CheckResult."""

    def test_crashing_check_yields_error_result_not_exception(self) -> None:
        store = _make_store(self.tmp)

        def _exploding_check(s, ctx):
            raise RuntimeError("simulated internal failure")

        with patch.dict("memory.validation.CHECK_REGISTRY", {"staleness": _exploding_check}):
            results = run_checks(store, checks=("staleness",))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].severity, "error")
        self.assertEqual(results[0].check_id, "staleness")
        self.assertIn("simulated internal failure", results[0].message)


# ---------------------------------------------------------------------------
# Current on-disk format tests
# ---------------------------------------------------------------------------


class TestCurrentOnDiskFormat(MemoryTestCase):
    """Tests for the on-disk format Claude Code writes today (kebab-case filenames,
    nested metadata, [[wikilinks]], metadata.modified).

    Uses CURRENT_FORMAT_MEMORY and CURRENT_FORMAT_INDEX from fixtures.
    """

    def test_kebab_wikilink_resolves_no_broken_link(self) -> None:
        """[[project-dry-run-notes]] in feedback-run-it.md resolves when the target exists."""
        from memory.parser import parse_memory_file

        # Write CURRENT_FORMAT_MEMORY and the wikilink target
        f1 = self.tmp / "feedback-run-it.md"
        f1.write_text(CURRENT_FORMAT_MEMORY, encoding="utf-8")

        f2 = self.tmp / "project-dry-run-notes.md"
        f2.write_text(
            "---\nname: project-dry-run-notes\nmetadata:\n  type: project\n"
            "  node_type: memory\n---\n\nContent.\n",
            encoding="utf-8",
        )

        # Also write CURRENT_FORMAT_INDEX as MEMORY.md to populate the store index
        index_path = self.tmp / "MEMORY.md"
        index_path.write_text(CURRENT_FORMAT_INDEX, encoding="utf-8")

        m1 = parse_memory_file(f1, project_slug="test-slug")
        m2 = parse_memory_file(f2, project_slug="test-slug")
        store = _make_store(self.tmp, memories=(m1, m2))
        results = run_checks(store, checks=("ref-broken-wikilink",))
        broken = [r for r in results if r.check_id == "ref-broken-wikilink"]
        self.assertEqual(broken, [])

    def test_type_prefixed_filename_name_lacks_prefix_no_mismatch(self) -> None:
        """A feedback-*.md file whose name field omits the type prefix is not a mismatch."""
        from memory.parser import parse_memory_file

        # Variant of CURRENT_FORMAT_MEMORY where the name is just "Run It" (no prefix)
        content = (
            "---\n"
            "name: Run It\n"
            'description: "Run the thing once instead of reasoning about it"\n'
            "metadata:\n"
            "  node_type: memory\n"
            "  type: feedback\n"
            "  originSessionId: 00000000-0000-4000-8000-000000000000\n"
            "  modified: 2026-11-11T21:38:57.947Z\n"
            "---\n\n"
            "One dry run beats five review rounds.\n\n"
            "**Why:** Reading misses runtime behaviour.\n\n"
            "**How to apply:** Execute before reviewing.\n"
        )
        f = self.tmp / "feedback-run-it.md"
        f.write_text(content, encoding="utf-8")
        m = parse_memory_file(f, project_slug="test-slug")
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-name-slug-mismatch",))
        mismatch = [r for r in results if r.check_id == "schema-name-slug-mismatch"]
        self.assertEqual(
            mismatch,
            [],
            "feedback-run-it.md with name='Run It' should not be a slug mismatch "
            "(type prefix accepted)",
        )

    def test_metadata_modified_does_not_trigger_unknown_key(self) -> None:
        """metadata.modified in CURRENT_FORMAT_MEMORY must not fire schema-unknown-key."""
        from memory.parser import parse_memory_file

        f = self.tmp / "feedback-run-it.md"
        f.write_text(CURRENT_FORMAT_MEMORY, encoding="utf-8")
        m = parse_memory_file(f, project_slug="test-slug")
        store = _make_store(self.tmp, memories=(m,))
        results = run_checks(store, checks=("schema-unknown-key",))
        unknown = [r for r in results if r.check_id == "schema-unknown-key"]
        self.assertEqual(
            unknown,
            [],
            f"metadata.modified must not appear in unknown_keys; "
            f"frontmatter.unknown_keys={m.frontmatter.unknown_keys!r}",
        )

    def test_default_checks_excludes_stale_superseded_pr(self) -> None:
        """DEFAULT_CHECKS must not include stale-superseded-pr (network check; opt-in only)."""
        from memory.validation import DEFAULT_CHECKS

        self.assertNotIn(
            "stale-superseded-pr",
            DEFAULT_CHECKS,
            "stale-superseded-pr is a network check and must be excluded from DEFAULT_CHECKS",
        )
