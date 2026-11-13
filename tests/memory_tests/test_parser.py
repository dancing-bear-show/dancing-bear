"""Covers frontmatter dialect detection, Why/How splitting, wikilink normalization,
false-positive exclusion, anchors, malformed YAML, normalize_slug, and
fixtures.CURRENT_FORMAT_MEMORY parsing."""

from __future__ import annotations

import unittest
from datetime import datetime

from tests.memory_tests.fixtures import CURRENT_FORMAT_MEMORY, MemoryTestCase
from memory.models import MemoryType, SchemaShape
from memory.parser import (
    extract_anchors,
    extract_wikilinks,
    normalize_slug,
    parse_frontmatter,
    parse_memory_file,
)


class TestExtractWikilinks(MemoryTestCase):
    """Wikilink extraction — normalization, inclusion criteria, false-positive exclusion."""

    def test_hyphen_underscore_fold(self):
        result = extract_wikilinks("[[feedback-worktree-isolation]]")
        self.assertEqual(result, ("feedback_worktree_isolation",))

    def test_multiple_hyphens_fold_to_underscores(self):
        result = extract_wikilinks("[[foo-bar-baz]]")
        self.assertEqual(result, ("foo_bar_baz",))

    def test_plain_underscored_wikilinks_pass_through(self):
        result = extract_wikilinks("[[simple_link]]")
        self.assertEqual(result, ("simple_link",))

    def test_multiple_wikilinks_in_same_body(self):
        result = extract_wikilinks("[[link-one]] and [[link-two]]")
        self.assertEqual(result, ("link_one", "link_two"))

    def test_bash_test_false_positive(self):
        result = extract_wikilinks('[[ ! -d "$PWD" ]]')
        self.assertEqual(result, ())

    def test_path_like_wikilink_false_positive(self):
        result = extract_wikilinks("[[.llm/OTEL_GUIDE.md]]")
        self.assertEqual(result, ())

    def test_mixed_true_and_false_positives(self):
        result = extract_wikilinks('[[real-link]] and [[ ! -d "$PWD" ]] and [[.llm/PATH.md]]')
        self.assertEqual(result, ("real_link",))

    def test_empty_body(self):
        result = extract_wikilinks("")
        self.assertEqual(result, ())

    def test_wikilink_at_start(self):
        result = extract_wikilinks("[[first-link]] rest of body")
        self.assertEqual(result, ("first_link",))

    def test_wikilink_at_end(self):
        result = extract_wikilinks("body text [[end-link]]")
        self.assertEqual(result, ("end_link",))

    def test_single_word_wikilink_excluded(self):
        result = extract_wikilinks("[[word]]")
        self.assertEqual(result, ())

    def test_uppercase_excluded(self):
        result = extract_wikilinks("[[Feedback]]")
        self.assertEqual(result, ())


class TestExtractAnchors(MemoryTestCase):
    """Anchor extraction from backtick-quoted identifiers and quoted flags."""

    def test_backtick_identifiers_extracted(self):
        body = "Use `parse_frontmatter` to parse the file, then call `load_store`."
        result = extract_anchors(body)
        self.assertIn("parse_frontmatter", result)
        self.assertIn("load_store", result)

    def test_quoted_flags_extracted(self):
        body = "Pass '--dry-run' and \"-x\" flags to the command."
        result = extract_anchors(body)
        self.assertIn("--dry-run", result)
        self.assertNotIn("-x", result)

    def test_short_tokens_filtered_by_min_length(self):
        body = "Use `--` or `ls` or `ok` to run things."
        result = extract_anchors(body)
        self.assertNotIn("--", result)
        self.assertNotIn("ls", result)
        self.assertNotIn("ok", result)

    def test_stoplist_tokens_filtered(self):
        body = "Run `pytest` and `grep` and check `json` output with `yaml` format."
        result = extract_anchors(body)
        self.assertNotIn("pytest", result)
        self.assertNotIn("grep", result)
        self.assertNotIn("json", result)
        self.assertNotIn("yaml", result)

    def test_deduplication_preserves_first_seen_order(self):
        body = "`parse_memory` then `load_store` then `parse_memory` again"
        result = extract_anchors(body)
        self.assertEqual(result, ("parse_memory", "load_store"))

    def test_empty_body_returns_empty_tuple(self):
        self.assertEqual(extract_anchors(""), ())

    def test_returns_tuple(self):
        self.assertIsInstance(extract_anchors("no anchors here"), tuple)

    def test_trailing_punctuation_stripped_before_stoplist(self):
        body = "Run `pytest,` to test, check `yaml.` output, use `workflow:` stages."
        result = extract_anchors(body)
        self.assertNotIn("pytest,", result)
        self.assertNotIn("pytest", result)
        self.assertNotIn("yaml.", result)
        self.assertNotIn("yaml", result)
        self.assertNotIn("workflow:", result)
        self.assertNotIn("workflow", result)

    def test_trailing_punctuation_stripped_token_too_short(self):
        body = "Try `ls/` or `ok.` to see the result."
        result = extract_anchors(body)
        self.assertNotIn("ls/", result)
        self.assertNotIn("ls", result)
        self.assertNotIn("ok.", result)
        self.assertNotIn("ok", result)

    def test_trailing_punctuation_does_not_strip_valid_token(self):
        body = "Call `parse_memory,` to load the data."
        result = extract_anchors(body)
        self.assertIn("parse_memory", result)
        self.assertNotIn("parse_memory,", result)


class TestParseFrontmatter(MemoryTestCase):
    """parse_frontmatter() — all four SchemaShape outcomes and edge cases."""

    def test_nested_dialect(self):
        text = "---\nname: nm\nmetadata:\n  type: feedback\n  node_type: memory\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.NESTED)
        self.assertEqual(result.type, MemoryType.FEEDBACK)
        self.assertEqual(result.node_type, "memory")
        self.assertEqual(result.name, "nm")

    def test_flat_dialect(self):
        text = "---\nname: flat_mem\ntype: project\nnode_type: memory\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.FLAT)
        self.assertEqual(result.type, MemoryType.PROJECT)
        self.assertEqual(result.node_type, "memory")

    def test_absent_type(self):
        text = "---\nname: no_type\ndescription: some desc\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.ABSENT)
        self.assertIsNone(result.type)

    def test_no_frontmatter(self):
        text = "# Just a markdown heading\n\nsome content\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.NO_FRONTMATTER)
        self.assertIsNone(result.type)
        self.assertIsNone(result.name)

    def test_malformed_yaml_returns_absent(self):
        text = "---\nmetadata:\n  type: feedback\n  bad: [unclosed\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.ABSENT)

    def test_unterminated_frontmatter_returns_absent(self):
        text = "---\ntype: feedback\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.ABSENT)

    def test_non_mapping_yaml_raises_type_error(self):
        text = "---\n- item1\n- item2\n---\n"
        with self.assertRaisesRegex(TypeError, "mapping"):
            parse_frontmatter(text)

    def test_nested_unknown_keys_preserved(self):
        text = "---\nmetadata:\n  type: feedback\n  node_type: memory\n  extra_key: val\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.NESTED)
        self.assertEqual(result.unknown_keys.get("metadata.extra_key"), "val")

    def test_nested_recognized_top_keys_absent_from_unknown_keys(self):
        text = (
            "---\nname: test_memory\ndescription: A test memory\nmodified: 2026-08-06\n"
            "metadata:\n  type: feedback\n  node_type: memory\n  extra_key: val\n---\n"
        )
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.NESTED)
        self.assertEqual(result.name, "test_memory")
        self.assertEqual(result.description, "A test memory")
        self.assertNotIn("name", result.unknown_keys)
        self.assertNotIn("description", result.unknown_keys)
        self.assertNotIn("modified", result.unknown_keys)
        self.assertEqual(result.unknown_keys.get("metadata.extra_key"), "val")

    def test_flat_unknown_keys_preserved(self):
        text = "---\ntype: project\nfuture_field: future_value\nanother_key: 99\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.FLAT)
        self.assertEqual(result.unknown_keys.get("future_field"), "future_value")
        self.assertEqual(result.unknown_keys.get("another_key"), 99)

    def test_type_coercion_unknown_value_yields_none(self):
        text = "---\nmetadata:\n  type: unknowntype\n  node_type: memory\n---\n"
        result = parse_frontmatter(text)
        self.assertIsNone(result.type)

    def test_empty_frontmatter_block_returns_absent(self):
        text = "---\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result.shape, SchemaShape.ABSENT)


class TestParseMemoryFile(MemoryTestCase):
    """parse_memory_file() — full file parsing including Why/How split."""

    def test_nested_dialect_file(self):
        content = (
            "---\n"
            "name: feedback_worktree\n"
            "description: A feedback memory\n"
            "metadata:\n"
            "  type: feedback\n"
            "  node_type: memory\n"
            "---\n\n"
            "**Why:** This was added for worktree isolation.\n\n"
            "**How to apply:** Always work in a worktree.\n\n"
            "See [[other_feedback]] for more context.\n"
        )
        f = self.tmp / "feedback_worktree.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")

        self.assertEqual(memory.slug, "feedback_worktree")
        self.assertEqual(memory.project_slug, "test-slug")
        self.assertEqual(memory.frontmatter.shape, SchemaShape.NESTED)
        self.assertEqual(memory.frontmatter.type, MemoryType.FEEDBACK)
        self.assertEqual(memory.frontmatter.node_type, "memory")
        self.assertIsNotNone(memory.why)
        self.assertIn("worktree isolation", memory.why)
        self.assertIsNotNone(memory.how_to_apply)
        self.assertIn("worktree", memory.how_to_apply)
        self.assertIn("other_feedback", memory.wikilinks)
        self.assertTrue(memory.is_memory)

    def test_flat_dialect_file(self):
        content = "---\ntype: project\nname: proj_state\n---\n\nState of the project.\n"
        f = self.tmp / "proj_state.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertEqual(memory.frontmatter.shape, SchemaShape.FLAT)
        self.assertEqual(memory.frontmatter.type, MemoryType.PROJECT)
        self.assertTrue(memory.is_memory)

    def test_no_frontmatter_file_is_not_memory(self):
        content = "# Just Markdown\n\nNo frontmatter.\n"
        f = self.tmp / "scratch.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertEqual(memory.frontmatter.shape, SchemaShape.NO_FRONTMATTER)
        self.assertFalse(memory.is_memory)

    def test_absent_type_file_is_not_memory(self):
        content = "---\nname: no_type\n---\n\nSome content.\n"
        f = self.tmp / "no_type.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertEqual(memory.frontmatter.shape, SchemaShape.ABSENT)
        self.assertFalse(memory.is_memory)

    def test_why_absent_yields_none(self):
        content = "---\ntype: feedback\n---\n\n**How to apply:** Do this.\n"
        f = self.tmp / "no_why.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertIsNone(memory.why)
        self.assertIsNotNone(memory.how_to_apply)

    def test_how_absent_yields_none(self):
        content = "---\ntype: feedback\n---\n\n**Why:** Because reasons.\n"
        f = self.tmp / "no_how.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertIsNotNone(memory.why)
        self.assertIsNone(memory.how_to_apply)

    def test_index_entries_populate_indexed_fields(self):
        from memory.models import IndexEntry

        content = "---\ntype: feedback\nname: indexed_mem\n---\n\nContent.\n"
        f = self.tmp / "indexed_mem.md"
        f.write_text(content, encoding="utf-8")

        entry = IndexEntry(
            target="indexed_mem.md",
            title="Indexed Mem",
            hook="indexed memory hook",
            section="Feedback",
            line_no=5,
        )

        memory = parse_memory_file(f, project_slug="test-slug", index_entries=(entry,))
        self.assertTrue(memory.indexed)
        self.assertEqual(memory.index_hook, "indexed memory hook")
        self.assertEqual(memory.index_section, "Feedback")

    def test_no_index_entry_yields_not_indexed(self):
        content = "---\ntype: feedback\n---\n\nContent.\n"
        f = self.tmp / "unindexed.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertFalse(memory.indexed)
        self.assertIsNone(memory.index_hook)
        self.assertIsNone(memory.index_section)

    def test_mtime_and_size_populated(self):
        content = "---\ntype: feedback\n---\n\nContent.\n"
        f = self.tmp / "sized.md"
        f.write_text(content, encoding="utf-8")

        memory = parse_memory_file(f, project_slug="test-slug")
        self.assertGreater(memory.size_bytes, 0)
        self.assertIsInstance(memory.mtime, datetime)
        self.assertIsNotNone(memory.mtime.tzinfo)


class TestCurrentFormatMemory(MemoryTestCase):
    """Parse fixtures.CURRENT_FORMAT_MEMORY and verify all expected fields."""

    def _write_and_parse(self, filename: str = "feedback-run-it.md"):
        f = self.tmp / filename
        f.write_text(CURRENT_FORMAT_MEMORY, encoding="utf-8")
        return parse_memory_file(f, project_slug="test-slug")

    def test_shape_is_nested(self):
        memory = self._write_and_parse()
        self.assertEqual(memory.frontmatter.shape, SchemaShape.NESTED)

    def test_type_is_feedback(self):
        memory = self._write_and_parse()
        self.assertEqual(memory.frontmatter.type, MemoryType.FEEDBACK)

    def test_node_type_is_memory(self):
        memory = self._write_and_parse()
        self.assertEqual(memory.frontmatter.node_type, "memory")

    def test_origin_session_id_populated(self):
        memory = self._write_and_parse()
        self.assertEqual(
            memory.frontmatter.origin_session_id,
            "00000000-0000-4000-8000-000000000000",
        )

    def test_origin_session_id_not_in_unknown_keys(self):
        memory = self._write_and_parse()
        self.assertNotIn("originSessionId", memory.frontmatter.unknown_keys)
        self.assertNotIn("metadata.originSessionId", memory.frontmatter.unknown_keys)

    def test_modified_populated_from_metadata(self):
        memory = self._write_and_parse()
        self.assertIsNotNone(memory.frontmatter.modified)
        self.assertIn("2026-11-11", memory.frontmatter.modified)

    def test_metadata_modified_not_in_unknown_keys(self):
        memory = self._write_and_parse()
        self.assertNotIn("modified", memory.frontmatter.unknown_keys)
        self.assertNotIn("metadata.modified", memory.frontmatter.unknown_keys)

    def test_kebab_wikilink_normalized(self):
        memory = self._write_and_parse()
        self.assertIn("project_dry_run_notes", memory.wikilinks)

    def test_slug_derived_from_filename(self):
        memory = self._write_and_parse("feedback-run-it.md")
        self.assertEqual(memory.slug, "feedback-run-it")

    def test_is_memory_true(self):
        memory = self._write_and_parse()
        self.assertTrue(memory.is_memory)

    def test_why_and_how_to_apply_extracted(self):
        memory = self._write_and_parse()
        self.assertIsNotNone(memory.why)
        self.assertIsNotNone(memory.how_to_apply)
        self.assertIn("runtime", memory.why)
        self.assertIn("Execute", memory.how_to_apply)


class TestNormalizeSlug(unittest.TestCase):
    """normalize_slug — dash to underscore folding."""

    def test_dashes_folded_to_underscores(self):
        self.assertEqual(normalize_slug("feedback-run-it"), "feedback_run_it")

    def test_multiple_dashes(self):
        self.assertEqual(normalize_slug("project-dry-run-notes"), "project_dry_run_notes")

    def test_already_underscored_unchanged(self):
        self.assertEqual(normalize_slug("feedback_run_it"), "feedback_run_it")

    def test_mixed_separators_normalized(self):
        self.assertEqual(normalize_slug("foo-bar_baz-qux"), "foo_bar_baz_qux")

    def test_empty_string(self):
        self.assertEqual(normalize_slug(""), "")

    def test_no_separator(self):
        self.assertEqual(normalize_slug("word"), "word")

    def test_idempotent(self):
        slug = "some-compound-name"
        self.assertEqual(normalize_slug(normalize_slug(slug)), normalize_slug(slug))


if __name__ == "__main__":
    unittest.main()
