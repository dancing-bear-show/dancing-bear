"""Coverage for memory.commands.import_cmd and memory.commands.export_cmd:
error paths (missing selector, no stores, blocking redactions, bad bundle path),
--on-conflict skip/rename/overwrite dispositions, native-file overwrite guard,
--dry-run, and export's confirmation/--yes/--output paths.

Patches discover_stores where it is USED in each command module, not
where it is defined, per project convention.
"""

from __future__ import annotations

import contextlib
import io
import json
import ntpath
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory.bundle import IMPORT_MARKER_KEY, serialize_bundle
from memory.commands import export_cmd, import_cmd
from memory.discovery import load_store
from memory.models import MemoryBundle, MemoryStore
from tests.memory_tests.fixtures import (
    SLUG_MAIN,
    MemoryTestCase,
    make_projects_root,
    sample_bundle,
)


# ---------------------------------------------------------------------------
# Symlink support check (platform guard)
# ---------------------------------------------------------------------------


def _symlinks_supported() -> bool:
    try:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.txt")
            lnk = os.path.join(d, "lnk.txt")
            with open(src, "w") as f:
                f.write("x")
            os.symlink(src, lnk)
        return True
    except (OSError, NotImplementedError):
        return False


_requires_symlinks = unittest.skipUnless(_symlinks_supported(), "symlinks not supported on this platform")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_from_slug(projects_root: Path, slug: str = SLUG_MAIN) -> MemoryStore:
    return load_store(slug, projects_root=projects_root)


def _write_bundle_file(tmp_path: Path, bundle: MemoryBundle, *, fmt: str = "yaml") -> Path:
    content = serialize_bundle(bundle, fmt=fmt)
    path = tmp_path / f"bundle.{fmt}"
    path.write_text(content, encoding="utf-8")
    return path


def _store_with_index(tmp_path: Path, slug: str = "-Users-alice-code-indexed-project") -> MemoryStore:
    """Build a store whose memory/ dir has a MEMORY.md, so index_path is set."""
    projects_dir = tmp_path / "indexed_projects"
    memory_dir = projects_dir / slug / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    return load_store(slug, projects_root=projects_dir)


def _run_export(argv: list[str]) -> tuple[int, str, str]:
    """Run memory.cli.main with the export subcommand; return (rc, stdout, stderr)."""
    from memory.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = main(["export"] + argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _run_import(argv: list[str]) -> tuple[int, str, str]:
    """Run memory.cli.main with the import subcommand; return (rc, stdout, stderr)."""
    from memory.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = main(["import"] + argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# export_cmd — _select_memories unit coverage
# ---------------------------------------------------------------------------


class TestExportSelectMemories(MemoryTestCase):
    """Unit coverage for _select_memories filter logic."""

    def setUp(self) -> None:
        super().setUp()
        self.projects_root = make_projects_root(self.tmp)

    def test_include_all_returns_every_memory(self) -> None:
        store = _store_from_slug(self.projects_root)

        selected = export_cmd._select_memories(
            store, slugs=None, types=None, include_all=True
        )

        self.assertEqual(selected, store.memories)

    def test_slug_filter_returns_only_matching(self) -> None:
        store = _store_from_slug(self.projects_root)

        selected = export_cmd._select_memories(
            store, slugs=["feedback_worktree"], types=None, include_all=False
        )

        self.assertEqual([m.slug for m in selected], ["feedback_worktree"])

    def test_type_filter_returns_only_matching(self) -> None:
        store = _store_from_slug(self.projects_root)

        selected = export_cmd._select_memories(
            store, slugs=None, types=["feedback"], include_all=False
        )

        self.assertTrue(
            all(
                m.frontmatter.type is not None and m.frontmatter.type.value == "feedback"
                for m in selected
            )
        )

    def test_no_selectors_returns_empty(self) -> None:
        store = _store_from_slug(self.projects_root)

        selected = export_cmd._select_memories(
            store, slugs=None, types=None, include_all=False
        )

        self.assertEqual(selected, ())


# ---------------------------------------------------------------------------
# export_cmd — CLI coverage
# ---------------------------------------------------------------------------


class TestExportMainCli(MemoryTestCase):
    """End-to-end coverage of export via memory.cli.main argv handling and exit codes."""

    def setUp(self) -> None:
        super().setUp()
        self.projects_root = make_projects_root(self.tmp)

    def test_missing_selector_returns_validation_error(self) -> None:
        rc, _, _ = _run_export([])

        self.assertEqual(rc, 1)

    def test_no_stores_found_prints_error_and_returns_1(self) -> None:
        with patch("memory.commands.export_cmd.discover_stores", return_value=()):
            rc, _, err = _run_export(["--all"])

        self.assertEqual(rc, 1)
        self.assertIn("No memory stores found", err)

    def test_no_memories_matched_returns_0_with_message(self) -> None:
        store = _store_from_slug(self.projects_root)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, err = _run_export(["--slug", "does-not-exist"])

        self.assertEqual(rc, 0)
        self.assertIn("No memories matched", err)

    def test_blocking_redaction_aborts_export(self) -> None:
        """A memory body containing a block-severity secret refuses export."""
        projects_dir = self.tmp / "projects"
        slug = "-Users-alice-code-dirty-project"
        memory_dir = projects_dir / slug / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "leaky.md").write_text(
            "---\nname: leaky\ndescription: has a secret\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** leak.\n\n**How to apply:** n/a.\n\n"
            "AKIA" + "0123456789ABCDEF\n",
            encoding="utf-8",
        )
        store = load_store(slug, projects_root=projects_dir)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, err = _run_export(["--all", "--yes"])

        self.assertEqual(rc, 1)
        self.assertIn("Export blocked", err)

    def test_dry_run_prints_would_export_count_and_returns_0(self) -> None:
        store = _store_from_slug(self.projects_root)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, err = _run_export(["--all", "--dry-run"])

        self.assertEqual(rc, 0)
        self.assertIn("Dry-run", err)

    def test_confirmation_declined_returns_1(self) -> None:
        store = _store_from_slug(self.projects_root)

        with (
            patch("memory.commands.export_cmd.discover_stores", return_value=(store,)),
            patch("builtins.input", return_value="n"),
        ):
            rc, _, err = _run_export(["--all"])

        self.assertEqual(rc, 1)
        self.assertIn("Export cancelled", err)

    def test_confirmation_eof_returns_1(self) -> None:
        store = _store_from_slug(self.projects_root)

        def _raise_eof(_prompt: str) -> str:
            raise EOFError

        with (
            patch("memory.commands.export_cmd.discover_stores", return_value=(store,)),
            patch("builtins.input", side_effect=_raise_eof),
        ):
            rc, _, err = _run_export(["--all"])

        self.assertEqual(rc, 1)
        self.assertIn("EOF", err)

    def test_yes_flag_skips_confirmation_and_prints_to_stdout(self) -> None:
        store = _store_from_slug(self.projects_root)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_export(["--all", "--yes", "--format", "json"])

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["bundle_version"], 1)

    def test_output_file_writes_bundle_and_reports_path(self) -> None:
        store = _store_from_slug(self.projects_root)
        out_path = self.tmp / "out" / "bundle.yaml"

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, err = _run_export(["--all", "--yes", "--output", str(out_path)])

        self.assertEqual(rc, 0)
        self.assertTrue(out_path.exists())
        self.assertIn("Bundle written to", err)

    def test_output_write_error_returns_1(self) -> None:
        store = _store_from_slug(self.projects_root)
        out_path = self.tmp / "out" / "bundle.yaml"

        with (
            patch("memory.commands.export_cmd.discover_stores", return_value=(store,)),
            patch(
                "memory.commands.export_cmd.atomic_write_text",
                side_effect=OSError("disk full"),
            ),
        ):
            rc, _, err = _run_export(["--all", "--yes", "--output", str(out_path)])

        self.assertEqual(rc, 1)
        self.assertIn("Error writing", err)

    @_requires_symlinks
    def test_output_symlink_destination_refused(self) -> None:
        """A symlink at --output is refused and the link target is not modified."""
        store = _store_from_slug(self.projects_root)
        victim = self.tmp / "victim.txt"
        victim.write_text("original\n", encoding="utf-8")
        out_path = self.tmp / "bundle.yaml"
        out_path.symlink_to(victim)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, err = _run_export(["--all", "--yes", "--output", str(out_path)])

        self.assertEqual(rc, 1)
        self.assertEqual(victim.read_text(encoding="utf-8"), "original\n")
        self.assertTrue(out_path.is_symlink())
        self.assertIn("refusing to write through symlink", err)

    def test_allow_warn_does_not_bypass_block_severity(self) -> None:
        """--allow-warn only affects warn severity; block-severity still refuses."""
        projects_dir = self.tmp / "projects2"
        slug = "-Users-alice-code-dirty-project2"
        memory_dir = projects_dir / slug / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "leaky.md").write_text(
            "---\nname: leaky\ndescription: has a secret\nmetadata:\n  type: feedback\n"
            "  node_type: memory\n---\n\n**Why:** leak.\n\n**How to apply:** n/a.\n\n"
            "AKIA" + "0123456789ABCDEF\n",
            encoding="utf-8",
        )
        store = load_store(slug, projects_root=projects_dir)

        with patch("memory.commands.export_cmd.discover_stores", return_value=(store,)):
            rc, _, _ = _run_export(["--all", "--yes", "--allow-warn"])

        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# import_cmd — helper unit coverage
# ---------------------------------------------------------------------------


class TestImportHelpers(MemoryTestCase):
    """Unit coverage for import_cmd helper functions."""

    def test_slugify_lowercases_and_underscores(self) -> None:
        self.assertEqual(import_cmd._slugify("My Cool Memory!"), "my_cool_memory")

    def test_slugify_empty_result_falls_back_to_memory(self) -> None:
        self.assertEqual(import_cmd._slugify("!!!"), "memory")

    def test_derive_slug_uses_name_when_present(self) -> None:
        bundle = sample_bundle()
        em = bundle.memories[0]
        self.assertEqual(import_cmd._derive_slug(em, counter=7), "test_memory")

    def test_derive_slug_falls_back_to_counter_when_no_name(self) -> None:
        import dataclasses

        bundle = sample_bundle()
        em = bundle.memories[0]
        fm_no_name = dataclasses.replace(em.frontmatter, name=None)
        em_no_name = dataclasses.replace(em, frontmatter=fm_no_name)

        self.assertEqual(import_cmd._derive_slug(em_no_name, counter=7), "memory_0007")

    def test_is_native_file_true_when_marker_absent(self) -> None:
        native = self.tmp / "native.md"
        native.write_text("---\nname: native\n---\n\nnative body\n", encoding="utf-8")

        self.assertTrue(import_cmd._is_native_file(native))

    def test_is_native_file_false_when_marker_present(self) -> None:
        imported = self.tmp / "imported.md"
        imported.write_text(
            f"---\nmetadata:\n  {IMPORT_MARKER_KEY}:\n    origin_repo: null\n---\n\nbody\n",
            encoding="utf-8",
        )

        self.assertFalse(import_cmd._is_native_file(imported))

    def test_is_native_file_unreadable_treated_as_native(self) -> None:
        missing = self.tmp / "does-not-exist.md"

        self.assertTrue(import_cmd._is_native_file(missing))


# ---------------------------------------------------------------------------
# import_cmd — CLI coverage
# ---------------------------------------------------------------------------


class TestImportMainCli(MemoryTestCase):
    """End-to-end coverage of import via memory.cli.main argv handling, dispositions, and exit codes."""

    def setUp(self) -> None:
        super().setUp()
        self.projects_root = make_projects_root(self.tmp)

    def test_bad_bundle_path_returns_validation_error(self) -> None:
        rc, _, _ = _run_import([str(self.tmp / "does-not-exist.yaml")])

        self.assertEqual(rc, 1)

    def test_malformed_bundle_content_returns_validation_error(self) -> None:
        bad_path = self.tmp / "bad.yaml"
        bad_path.write_text("not: a, valid: [bundle", encoding="utf-8")

        rc, _, _ = _run_import([str(bad_path)])

        self.assertEqual(rc, 1)

    def test_blocking_redaction_in_bundle_body_rejected(self) -> None:
        import dataclasses

        bundle = sample_bundle()
        em = bundle.memories[0]
        dirty_em = dataclasses.replace(em, body=em.body + "\nAKIA" + "0123456789ABCDEF\n")
        dirty_bundle = MemoryBundle(
            bundle_version=bundle.bundle_version,
            created_at=bundle.created_at,
            memories=(dirty_em,),
            notes=bundle.notes,
        )
        bundle_path = _write_bundle_file(self.tmp, dirty_bundle)

        rc, _, _ = _run_import([str(bundle_path)])

        self.assertEqual(rc, 1)

    def test_no_stores_found_prints_error_and_returns_1(self) -> None:
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=()):
            rc, _, err = _run_import([str(bundle_path)])

        self.assertEqual(rc, 1)
        self.assertIn("No memory stores found", err)

    def test_import_new_memory_writes_file_and_reports_imported(self) -> None:
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "imported")
        written = Path(store.root) / "memory" / "imported_test_memory.md"
        self.assertTrue(written.exists())

    def test_dry_run_does_not_write_file(self) -> None:
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, _, _ = _run_import([str(bundle_path), "--dry-run"])

        self.assertEqual(rc, 0)
        written = Path(store.root) / "memory" / "imported_test_memory.md"
        self.assertFalse(written.exists())

    def test_on_conflict_skip_reports_skipped_when_file_exists(self) -> None:
        store = _store_from_slug(self.projects_root)
        target = Path(store.root) / "memory" / "imported_test_memory.md"
        original_content = "pre-existing content\n"
        target.write_text(original_content, encoding="utf-8")
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--on-conflict", "skip", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "skipped")
        self.assertEqual(rows[0]["reason"], "file exists")
        self.assertEqual(target.read_text(encoding="utf-8"), original_content)

    def test_on_conflict_rename_creates_numbered_file(self) -> None:
        store = _store_from_slug(self.projects_root)
        target = Path(store.root) / "memory" / "imported_test_memory.md"
        target.write_text("pre-existing content\n", encoding="utf-8")
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--on-conflict", "rename", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "renamed")
        renamed = Path(store.root) / "memory" / "imported_test_memory_1.md"
        self.assertTrue(renamed.exists())

    def test_on_conflict_overwrite_native_file_returns_error_row(self) -> None:
        """A native (no bundle_import) file cannot be overwritten — returns an error disposition."""
        store = _store_from_slug(self.projects_root)
        target = Path(store.root) / "memory" / "imported_test_memory.md"
        target.write_text("---\nname: native\n---\n\nnative content\n", encoding="utf-8")
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--on-conflict", "overwrite", "--format", "json"])

        # emit_rows succeeds even though the row reports an error action
        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "error")
        self.assertIn("native memory", rows[0]["reason"])
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "---\nname: native\n---\n\nnative content\n",
        )

    def test_on_conflict_overwrite_imported_file_writes_bak_and_overwrites(self) -> None:
        store = _store_from_slug(self.projects_root)
        target = Path(store.root) / "memory" / "imported_test_memory.md"
        target.write_text(
            f"---\nmetadata:\n  {IMPORT_MARKER_KEY}:\n    origin_repo: null\n---\n\nold body\n",
            encoding="utf-8",
        )
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--on-conflict", "overwrite", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "overwrite")
        bak_file = Path(str(target) + ".bak")
        self.assertTrue(bak_file.exists())
        self.assertIn("old body", bak_file.read_text(encoding="utf-8"))
        self.assertNotIn("old body", target.read_text(encoding="utf-8"))

    def test_reindex_appends_entry_on_success(self) -> None:
        store = _store_with_index(self.tmp)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, _, _ = _run_import([str(bundle_path), "--reindex", "--format", "json"])

        self.assertEqual(rc, 0)
        self.assertIsNotNone(store.index_path)
        index_content = Path(str(store.index_path)).read_text(encoding="utf-8")
        self.assertIn("test_memory", index_content)

    def test_reindex_failure_is_warned_not_fatal(self) -> None:
        """If reindexing raises, import still succeeds — the row still reports 'imported'."""
        store = _store_with_index(self.tmp)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with (
            patch("memory.commands.import_cmd.discover_stores", return_value=(store,)),
            patch("memory.parser.parse_memory_file", side_effect=RuntimeError("boom")),
        ):
            rc, out, err = _run_import([str(bundle_path), "--reindex", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "imported")
        self.assertIn("Warning: reindex failed", err)

    def test_write_atomic_error_returns_error_row(self) -> None:
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with (
            patch("memory.commands.import_cmd.discover_stores", return_value=(store,)),
            patch(
                "memory.commands.import_cmd._write_atomic",
                side_effect=OSError("disk full"),
            ),
        ):
            rc, out, _ = _run_import([str(bundle_path), "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "error")
        self.assertIn("disk full", rows[0]["reason"])

    @_requires_symlinks
    def test_dangling_symlink_target_refused(self) -> None:
        """A dangling link at the target reads as 'new memory' but is not followed."""
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            # First dry-run to discover the target filename
            _, out, _ = _run_import([str(bundle_path), "--dry-run", "--format", "json"])
            target_name = json.loads(out)[0]["target"]
            # Plant a dangling symlink at the target
            escaped = self.tmp / "outside" / "planted.md"
            link = Path(store.root) / "memory" / target_name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(escaped)

            rc, out, _ = _run_import([str(bundle_path), "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["action"], "error")
        self.assertIn("refusing to write through symlink", rows[0]["reason"])
        self.assertFalse(escaped.exists())
        self.assertTrue(link.is_symlink())

    def test_custom_prefix_applied_to_target_filename(self) -> None:
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--prefix", "custom_", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["target"], "custom_test_memory.md")
        self.assertTrue((Path(store.root) / "memory" / "custom_test_memory.md").is_file())

    def test_prefix_with_path_separator_is_rejected_before_any_write(self) -> None:
        """A --prefix that would leave <store>/memory/ fails validation and writes nothing."""
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        for prefix in ["../escaped_", "../../../escaped_", "sub/escaped_", "/nonexistent/escaped_"]:
            with self.subTest(prefix=prefix):
                before = sorted(p for p in self.tmp.rglob("*") if p.is_file())

                with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
                    rc, _, err = _run_import([str(bundle_path), "--prefix", prefix, "--format", "json"])

                self.assertEqual(rc, 1, f"expected exit 1 for prefix={prefix!r}")
                self.assertIn("--prefix", err)
                self.assertIn("path separators", err)
                self.assertFalse(list(self.tmp.rglob("*escaped_*")))
                self.assertEqual(sorted(p for p in self.tmp.rglob("*") if p.is_file()), before)

    def test_dot_only_prefix_stays_a_filename(self) -> None:
        """'..' without a separator is just part of the filename, not a traversal."""
        store = _store_from_slug(self.projects_root)
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(store,)):
            rc, out, _ = _run_import([str(bundle_path), "--prefix", "..", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["target"], "..test_memory.md")
        self.assertTrue((Path(store.root) / "memory" / "..test_memory.md").is_file())

    def test_drive_qualified_prefix_is_rejected_bare(self) -> None:
        # splitdrive only recognises drives on Windows; substituting ntpath's
        # implementation exercises the drive-qualified branch on every platform.
        with patch("memory.commands.import_cmd.os.path.splitdrive", ntpath.splitdrive):
            issue = import_cmd._prefix_issue("D:")
        self.assertIsNotNone(issue)
        self.assertIn("drive-qualified", issue or "")

    def test_drive_qualified_prefix_is_rejected_named(self) -> None:
        with patch("memory.commands.import_cmd.os.path.splitdrive", ntpath.splitdrive):
            issue = import_cmd._prefix_issue("c:imported_")
        self.assertIsNotNone(issue)
        self.assertIn("drive-qualified", issue or "")

    def test_plain_prefix_passes_under_windows_drive_rules(self) -> None:
        with patch("memory.commands.import_cmd.os.path.splitdrive", ntpath.splitdrive):
            issue = import_cmd._prefix_issue("imported_")
        self.assertIsNone(issue)

    def test_drive_qualified_prefix_rejected_before_bundle_is_read(self) -> None:
        bundle = sample_bundle()
        bundle_path = _write_bundle_file(self.tmp, bundle)

        with (
            patch("memory.commands.import_cmd.os.path.splitdrive", ntpath.splitdrive),
            patch("memory.commands.import_cmd.load_bundle") as mock_load,
            patch("memory.commands.import_cmd.discover_stores") as mock_discover,
        ):
            rc, _, err = _run_import([str(bundle_path), "--prefix", "D:"])

        self.assertEqual(rc, 1)
        self.assertIn("drive-qualified", err)
        mock_load.assert_not_called()
        mock_discover.assert_not_called()


# ---------------------------------------------------------------------------
# Round-trip: export then import
# ---------------------------------------------------------------------------


class TestExportImportRoundTrip(MemoryTestCase):
    """Composes export and import: exported bundle imports cleanly."""

    def test_export_then_import_round_trip(self) -> None:
        projects_root = make_projects_root(self.tmp)
        export_store = _store_from_slug(projects_root)
        out_path = self.tmp / "roundtrip.yaml"

        with patch("memory.commands.export_cmd.discover_stores", return_value=(export_store,)):
            export_rc, _, _ = _run_export(["--all", "--yes", "--output", str(out_path)])
        self.assertEqual(export_rc, 0)
        self.assertTrue(out_path.exists())

        # Import into a second, separate empty store.
        import_projects_dir = self.tmp / "import_projects"
        import_slug = "-Users-alice-code-import-target"
        import_memory_dir = import_projects_dir / import_slug / "memory"
        import_memory_dir.mkdir(parents=True)
        import_store = load_store(import_slug, projects_root=import_projects_dir)

        with patch("memory.commands.import_cmd.discover_stores", return_value=(import_store,)):
            import_rc, out, _ = _run_import([str(out_path), "--format", "json"])

        self.assertEqual(import_rc, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), len(export_store.memories))
        self.assertTrue(all(row["action"] == "imported" for row in rows))


if __name__ == "__main__":
    unittest.main()
