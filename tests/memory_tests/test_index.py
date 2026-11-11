"""Covers parse_index, render_index_line, append_entry, remove_entry, merge_duplicate_sections,
and parsing fixtures.CURRENT_FORMAT_INDEX (flat format, two entries, empty section, hooks)."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.memory_tests.fixtures import CURRENT_FORMAT_INDEX, MemoryTestCase
from memory.index import (
    append_entry,
    merge_duplicate_sections,
    parse_index,
    remove_entry,
    render_index_line,
)
from memory.parser import parse_memory_file


# ---------------------------------------------------------------------------
# File-local helpers
# ---------------------------------------------------------------------------


def _make_memory(base: Path, slug: str, content: str):
    """Write a .md file and parse it into a Memory."""
    f = base / f"{slug}.md"
    f.write_text(content, encoding="utf-8")
    return parse_memory_file(f, project_slug="test-slug")


def _make_index(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# TestParseIndex
# ---------------------------------------------------------------------------


class TestParseIndex(MemoryTestCase):
    def test_missing_file_returns_empty_tuple(self):
        result = parse_index(self.tmp / "MEMORY.md")
        self.assertEqual(result, ())

    def test_basic_entries_parsed(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Feedback\n- [foo.md](foo.md) — a foo thing\n")

        entries = parse_index(index_file)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].target, "foo.md")
        self.assertEqual(entries[0].title, "foo.md")
        self.assertEqual(entries[0].hook, "a foo thing")
        self.assertEqual(entries[0].section, "Feedback")
        self.assertEqual(entries[0].line_no, 2)

    def test_section_tracked_per_entry(self):
        content = (
            "## Feedback\n"
            "- [a.md](a.md) — entry a\n"
            "## Reference\n"
            "- [b.md](b.md) — entry b\n"
        )
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, content)

        entries = parse_index(index_file)
        self.assertEqual(len(entries), 2)
        sections = {e.target: e.section for e in entries}
        self.assertEqual(sections["a.md"], "Feedback")
        self.assertEqual(sections["b.md"], "Reference")

    def test_duplicate_sections_preserved_not_collapsed(self):
        """parse_index does NOT collapse duplicate sections — it sees them as separate."""
        content = (
            "## Reference\n"
            "- [a.md](a.md) — first ref\n"
            "## Reference\n"
            "- [b.md](b.md) — second ref\n"
        )
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, content)

        entries = parse_index(index_file)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e.section == "Reference" for e in entries))

    def test_line_no_is_one_indexed(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Sec\n- [x.md](x.md) — hook\n")

        entries = parse_index(index_file)
        self.assertEqual(entries[0].line_no, 2)

    def test_entry_without_hook(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Sec\n- [x.md](x.md)\n")

        entries = parse_index(index_file)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].hook, "")

    def test_current_format_index_two_entries(self):
        """fixtures.CURRENT_FORMAT_INDEX (flat format) parses to exactly two entries."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        entries = parse_index(index_file)
        self.assertEqual(len(entries), 2)

    def test_current_format_index_empty_section(self):
        """Flat CURRENT_FORMAT_INDEX has no ## headers, so section is empty string."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        entries = parse_index(index_file)
        for entry in entries:
            self.assertEqual(entry.section, "")

    def test_current_format_index_hooks(self):
        """CURRENT_FORMAT_INDEX entries carry expected hooks."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        entries = parse_index(index_file)
        targets = {e.target: e.hook for e in entries}
        self.assertIn("feedback-run-it.md", targets)
        self.assertIn("project-dry-run-notes.md", targets)
        self.assertIn("run the thing", targets["feedback-run-it.md"])
        self.assertIn("dry run", targets["project-dry-run-notes.md"])

    def test_current_format_index_titles(self):
        """CURRENT_FORMAT_INDEX entry titles match the link text."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        entries = parse_index(index_file)
        titles = {e.target: e.title for e in entries}
        self.assertEqual(titles["feedback-run-it.md"], "Run It")
        self.assertEqual(titles["project-dry-run-notes.md"], "Dry Run Notes")


# ---------------------------------------------------------------------------
# TestRenderIndexLine
# ---------------------------------------------------------------------------


class TestRenderIndexLine(MemoryTestCase):
    def test_renders_description(self):
        m = _make_memory(
            self.tmp,
            "feedback_thing",
            "---\ntype: feedback\nname: Feedback Thing\ndescription: a feedback thing\n---\n\nBody.\n",
        )
        line = render_index_line(m)
        self.assertEqual(line, "- [feedback_thing.md](feedback_thing.md) — a feedback thing")

    def test_falls_back_to_name(self):
        m = _make_memory(
            self.tmp,
            "named_thing",
            "---\ntype: feedback\nname: Named Thing\n---\n\nBody.\n",
        )
        line = render_index_line(m)
        self.assertIn("Named Thing", line)

    def test_falls_back_to_slug(self):
        m = _make_memory(
            self.tmp,
            "just_slug",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        line = render_index_line(m)
        self.assertIn("just_slug", line)

    def test_no_literal_none_in_output(self):
        m = _make_memory(
            self.tmp,
            "no_desc",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        line = render_index_line(m)
        self.assertNotIn("None", line)


# ---------------------------------------------------------------------------
# TestAppendEntry
# ---------------------------------------------------------------------------


class TestAppendEntry(MemoryTestCase):
    def test_append_to_existing_section(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Feedback\n- [a.md](a.md) — existing\n")

        m = _make_memory(
            self.tmp,
            "new_entry",
            "---\ntype: feedback\nname: New Entry\ndescription: new entry desc\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        content = index_file.read_text(encoding="utf-8")
        self.assertIn("new_entry.md", content)
        # Must land in the ONE existing section, not create a second one
        self.assertEqual(content.count("## Feedback"), 1)
        self.assertNotIn("## feedback", content)

    def test_append_matches_existing_section_case_insensitively(self):
        """MemoryType.value ('feedback') must match an existing '## Feedback' header."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(
            index_file,
            "## Feedback\n- [existing.md](existing.md) — existing\n\n"
            "## Project\n- [other.md](other.md) — other\n",
        )

        m = _make_memory(
            self.tmp,
            "case_test",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        content = index_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("## Feedback"), 1)
        self.assertNotIn("## feedback", content)
        self.assertIn("case_test.md", content)
        # The new entry must sit in the Feedback section, not append after Project
        feedback_section = content.split("## Feedback")[1].split("## Project")[0]
        self.assertIn("case_test.md", feedback_section)

    def test_append_creates_new_section_when_missing(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Reference\n- [a.md](a.md) — existing\n")

        m = _make_memory(
            self.tmp,
            "feedback_new",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        content = index_file.read_text(encoding="utf-8")
        self.assertIn("feedback_new.md", content)
        self.assertTrue(
            "## feedback" in content.lower() or "## Feedback" in content
        )

    def test_append_creates_file_when_absent(self):
        index_file = self.tmp / "MEMORY.md"
        self.assertFalse(index_file.exists())

        m = _make_memory(
            self.tmp,
            "brand_new",
            "---\ntype: reference\nname: Brand New\ndescription: brand new desc\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        self.assertTrue(index_file.exists())
        self.assertIn("brand_new.md", index_file.read_text(encoding="utf-8"))

    def test_section_kwarg_overrides_type(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## CustomSection\n")

        m = _make_memory(
            self.tmp,
            "override_sec",
            "---\ntype: project\nname: Override Sec\ndescription: override\n---\n\nBody.\n",
        )
        append_entry(index_file, m, section="CustomSection")

        content = index_file.read_text(encoding="utf-8")
        self.assertIn("override_sec.md", content)

    def test_append_to_flat_index_no_section_created(self):
        """Flat index (CURRENT_FORMAT_INDEX has no ## headers) gets entry appended
        at the end without creating a ## section header."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        m = _make_memory(
            self.tmp,
            "new_flat_entry",
            "---\nmetadata:\n  type: feedback\n  node_type: memory\nname: New Flat Entry\ndescription: flat entry\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        content = index_file.read_text(encoding="utf-8")
        self.assertIn("new_flat_entry.md", content)
        # No ## section header should be created in a flat index
        self.assertNotIn("## ", content)
        # Original entries still present
        self.assertIn("feedback-run-it.md", content)
        self.assertIn("project-dry-run-notes.md", content)

    def test_append_flat_index_happy_path_has_entry(self):
        """Appending to a flat index preserves the flat structure."""
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, CURRENT_FORMAT_INDEX)

        m = _make_memory(
            self.tmp,
            "another_entry",
            "---\ntype: project\ndescription: proj entry\n---\n\nBody.\n",
        )
        append_entry(index_file, m)

        entries_after = parse_index(index_file)
        targets = {e.target for e in entries_after}
        self.assertIn("another_entry.md", targets)
        self.assertIn("feedback-run-it.md", targets)


# ---------------------------------------------------------------------------
# TestRemoveEntry
# ---------------------------------------------------------------------------


class TestRemoveEntry(MemoryTestCase):
    def test_remove_existing_returns_true(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Feedback\n- [target.md](target.md) — hook\n")

        result = remove_entry(index_file, "target.md")
        self.assertTrue(result)
        content = index_file.read_text(encoding="utf-8")
        self.assertNotIn("target.md", content)

    def test_remove_nonexistent_returns_false(self):
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, "## Feedback\n- [other.md](other.md) — hook\n")

        result = remove_entry(index_file, "missing.md")
        self.assertFalse(result)

    def test_remove_missing_file_returns_false(self):
        result = remove_entry(self.tmp / "MEMORY.md", "anything.md")
        self.assertFalse(result)

    def test_append_remove_round_trip(self):
        index_file = self.tmp / "MEMORY.md"
        original_content = "## Feedback\n- [entry1.md](entry1.md) — first entry\n"
        _make_index(index_file, original_content)

        m = _make_memory(
            self.tmp,
            "entry2",
            "---\ntype: feedback\nname: Entry2\ndescription: second entry\n---\n\nBody.\n",
        )
        append_entry(index_file, m)
        self.assertIn("entry2.md", index_file.read_text(encoding="utf-8"))

        result = remove_entry(index_file, "entry2.md")
        self.assertTrue(result)

        final_content = index_file.read_text(encoding="utf-8")
        self.assertNotIn("entry2.md", final_content)
        self.assertIn("entry1.md", final_content)


# ---------------------------------------------------------------------------
# TestMergeDuplicateSections
# ---------------------------------------------------------------------------


class TestMergeDuplicateSections(MemoryTestCase):
    def test_no_duplicates_returns_zero_and_leaves_file_unchanged(self):
        index_file = self.tmp / "MEMORY.md"
        original = (
            "## Feedback\n- [a.md](a.md) — aaa\n## Reference\n- [b.md](b.md) — bbb\n"
        )
        _make_index(index_file, original)

        count = merge_duplicate_sections(index_file)
        self.assertEqual(count, 0)
        self.assertEqual(index_file.read_text(encoding="utf-8"), original)

    def test_one_duplicate_returns_one(self):
        content = (
            "## Reference\n"
            "- [a.md](a.md) — first\n"
            "## Feedback\n"
            "- [b.md](b.md) — only feedback\n"
            "## Reference\n"
            "- [c.md](c.md) — second\n"
        )
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, content)

        count = merge_duplicate_sections(index_file)
        self.assertEqual(count, 1)

        entries = parse_index(index_file)
        ref_entries = [e for e in entries if e.section == "Reference"]
        self.assertEqual(len(ref_entries), 2)

    def test_missing_file_returns_zero(self):
        count = merge_duplicate_sections(self.tmp / "MEMORY.md")
        self.assertEqual(count, 0)

    def test_entries_preserved_after_merge(self):
        content = (
            "## Feedback\n"
            "- [x.md](x.md) — first feedback\n"
            "## Feedback\n"
            "- [y.md](y.md) — second feedback\n"
        )
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, content)

        merge_duplicate_sections(index_file)
        entries = parse_index(index_file)
        targets = {e.target for e in entries}
        self.assertIn("x.md", targets)
        self.assertIn("y.md", targets)

    def test_case_mismatched_duplicate_headers_are_merged(self):
        """A lowercase '## feedback' header must merge with an existing '## Feedback' header."""
        content = (
            "## Feedback\n"
            "- [x.md](x.md) — original\n"
            "## Project\n"
            "- [z.md](z.md) — unrelated\n"
            "## feedback\n"
            "- [y.md](y.md) — appended with mismatched case\n"
        )
        index_file = self.tmp / "MEMORY.md"
        _make_index(index_file, content)

        count = merge_duplicate_sections(index_file)
        self.assertEqual(count, 1)

        final_content = index_file.read_text(encoding="utf-8")
        self.assertEqual(final_content.count("## Feedback"), 1)
        self.assertNotIn("## feedback", final_content)

        entries = parse_index(index_file)
        feedback_targets = {e.target for e in entries if e.section == "Feedback"}
        self.assertEqual(feedback_targets, {"x.md", "y.md"})


if __name__ == "__main__":
    unittest.main()
