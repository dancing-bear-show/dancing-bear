"""Covers bundle serde round-trip, unknown_keys preservation, bundle_import namespacing,
and originSessionId dropping."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests.memory_tests.fixtures import MemoryTestCase, sample_bundle
from memory.bundle import (
    IMPORT_MARKER_KEY,
    _frontmatter_from_dict,
    build_bundle,
    load_bundle,
    render_imported_memory,
    serialize_bundle,
)
from memory.models import (
    BUNDLE_VERSION,
    ExportedMemory,
    ExportProvenance,
    MemoryFrontmatter,
    MemoryType,
    SchemaShape,
)


# ---------------------------------------------------------------------------
# File-local helpers
# ---------------------------------------------------------------------------


def _simple_memory_file(base: Path, name: str = "simple.md"):
    """Write a minimal feedback memory file to base and parse it."""
    from memory.parser import parse_memory_file

    content = "---\ntype: feedback\n---\n\nBody.\n"
    f = base / name
    f.write_text(content, encoding="utf-8")
    return parse_memory_file(f, project_slug="test-slug")


# ---------------------------------------------------------------------------
# Serde round-trip
# ---------------------------------------------------------------------------


class TestBundleSerde(MemoryTestCase):
    def test_serde_round_trip_preserves_unknown_keys(self):
        """Serialize then load; assert unknown_keys survive key-for-key (yaml and json)."""
        bundle = sample_bundle()
        for fmt in ["yaml", "json"]:
            with self.subTest(fmt=fmt):
                serialized = serialize_bundle(bundle, fmt)
                output_file = self.tmp / f"bundle.{fmt}"
                output_file.write_text(serialized, encoding="utf-8")

                reconstructed = load_bundle(output_file)

                self.assertEqual(reconstructed.bundle_version, bundle.bundle_version)
                self.assertEqual(len(reconstructed.memories), len(bundle.memories))

                original_em = bundle.memories[0]
                reconstructed_em = reconstructed.memories[0]
                self.assertEqual(
                    reconstructed_em.frontmatter.unknown_keys,
                    original_em.frontmatter.unknown_keys,
                )
                self.assertEqual(reconstructed_em.frontmatter.type, original_em.frontmatter.type)
                self.assertEqual(reconstructed_em.body, original_em.body)
                self.assertEqual(
                    reconstructed_em.provenance.origin_project_slug,
                    original_em.provenance.origin_project_slug,
                )
                self.assertEqual(
                    reconstructed_em.provenance.exported_by_version,
                    original_em.provenance.exported_by_version,
                )
                self.assertEqual(reconstructed.notes, bundle.notes)

    def test_serialize_invalid_format_raises(self):
        bundle = sample_bundle()
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            serialize_bundle(bundle, "xml")


# ---------------------------------------------------------------------------
# TestLoadBundleErrors
# ---------------------------------------------------------------------------


class TestLoadBundleErrors(MemoryTestCase):
    def test_wrong_bundle_version_raises(self):
        import yaml

        wrong_version_data = {
            "bundle_version": 999,
            "created_at": datetime.now(UTC).isoformat(),
            "memories": [],
            "notes": None,
        }
        f = self.tmp / "wrong_version.yaml"
        f.write_text(yaml.dump(wrong_version_data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "bundle_version"):
            load_bundle(f)

    def test_non_mapping_top_level_raises(self):
        f = self.tmp / "list_bundle.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "mapping"):
            load_bundle(f)

    def test_malformed_yaml_raises(self):
        f = self.tmp / "malformed.yaml"
        f.write_text("bundle_version: 1\ncreated_at: [unclosed\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "failed to parse"):
            load_bundle(f)


# ---------------------------------------------------------------------------
# TestBuildBundle
# ---------------------------------------------------------------------------


class TestBuildBundle(MemoryTestCase):
    def test_origin_session_id_dropped(self):
        """build_bundle must drop origin_session_id from all ExportedMemory provenance."""
        from memory.parser import parse_memory_file

        content = (
            "---\n"
            "name: session_test\n"
            "metadata:\n"
            "  type: feedback\n"
            "  node_type: memory\n"
            "  originSessionId: aabbccdd-1234-5678-9012-abcdef012345\n"
            "---\n\n"
            "**Why:** Test session id drop.\n\n**How to apply:** Verify.\n"
        )
        f = self.tmp / "session_test.md"
        f.write_text(content, encoding="utf-8")
        memory = parse_memory_file(f, project_slug="test-slug")

        bundle = build_bundle((memory,))
        for em in bundle.memories:
            self.assertIsNone(em.provenance.origin_session_id)
            self.assertIsNone(em.frontmatter.origin_session_id)

    def test_scrub_applied_to_body(self):
        """build_bundle scrubs /Users/<name> paths from the body."""
        from memory.parser import parse_memory_file

        content = (
            "---\ntype: feedback\n---\n\n"
            "Working at /Users/alice/code/myproject/src.\n"
        )
        f = self.tmp / "home_path.md"
        f.write_text(content, encoding="utf-8")
        memory = parse_memory_file(f, project_slug="test-slug")

        bundle = build_bundle((memory,))
        self.assertEqual(len(bundle.memories), 1)
        em = bundle.memories[0]
        self.assertNotIn("/Users/alice", em.body)

    def test_notes_preserved(self):
        memory = _simple_memory_file(self.tmp, "noted.md")

        bundle = build_bundle((memory,), notes="export for testing")
        self.assertEqual(bundle.notes, "export for testing")

    def test_empty_memories_tuple(self):
        bundle = build_bundle(())
        self.assertEqual(bundle.memories, ())
        self.assertEqual(bundle.bundle_version, BUNDLE_VERSION)

    def test_include_host_false_omits_host(self):
        memory = _simple_memory_file(self.tmp, "nohost.md")

        bundle = build_bundle((memory,), include_host=False)
        for em in bundle.memories:
            self.assertIsNone(em.provenance.origin_host)


# ---------------------------------------------------------------------------
# TestRenderImportedMemory
# ---------------------------------------------------------------------------


class TestRenderImportedMemory(MemoryTestCase):
    def _make_em(self) -> ExportedMemory:
        fm = MemoryFrontmatter(
            name="imported_thing",
            description="an imported memory",
            type=MemoryType.FEEDBACK,
            node_type="memory",
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.NESTED,
            unknown_keys={"extra_key": "extra_val"},
        )
        provenance = ExportProvenance(
            origin_project_slug="-Users-alice-code-myrepo",
            origin_repo=None,
            origin_user="alice",
            origin_host=None,
            origin_session_id=None,
            exported_at=datetime(2026, 8, 1, tzinfo=UTC),
            exported_by_version=str(BUNDLE_VERSION),
            source_sha256="abc" * 21 + "a",
        )
        return ExportedMemory(
            frontmatter=fm,
            body="**Why:** Testing render.\n\n**How to apply:** Verify output.",
            provenance=provenance,
            redactions=(),
        )

    def test_renders_nested_dialect(self):
        em = self._make_em()
        rendered = render_imported_memory(em)
        self.assertTrue(rendered.startswith("---\n"))
        self.assertIn("metadata:", rendered)
        self.assertIn("node_type: memory", rendered)

    def test_no_origin_session_id_in_output(self):
        em = self._make_em()
        rendered = render_imported_memory(em)
        self.assertNotIn("originSessionId", rendered)
        self.assertNotIn("origin_session_id", rendered)

    def test_bundle_import_provenance_present(self):
        """Provenance is stored under IMPORT_MARKER_KEY ('bundle_import') in the rendered output."""
        em = self._make_em()
        rendered = render_imported_memory(em)
        self.assertIn(IMPORT_MARKER_KEY, rendered)
        self.assertIn("bundle_import", rendered)

    def test_body_preserved(self):
        em = self._make_em()
        rendered = render_imported_memory(em)
        self.assertIn("**Why:** Testing render.", rendered)

    def test_custom_prefix_not_in_output(self):
        """render_imported_memory uses prefix for slug construction but doesn't inject it into the file body."""
        em = self._make_em()
        rendered = render_imported_memory(em, prefix="imported_")
        self.assertIn("---", rendered)


# ---------------------------------------------------------------------------
# TestBuildBundleProvenance
# ---------------------------------------------------------------------------


class TestBuildBundleProvenance(MemoryTestCase):
    def test_include_host_true_populates_origin_host(self):
        """build_bundle(include_host=True) sets origin_host to the actual hostname."""
        import socket

        memory = _simple_memory_file(self.tmp, "host_test.md")

        bundle = build_bundle((memory,), include_host=True)

        self.assertEqual(len(bundle.memories), 1)
        em = bundle.memories[0]
        self.assertEqual(em.provenance.origin_host, socket.gethostname())

    def test_anonymize_true_scrubs_origin_user(self):
        """build_bundle(anonymize=True) scrubs the username from origin_user."""
        import getpass

        from memory.redaction import scrub

        memory = _simple_memory_file(self.tmp, "anon_test.md")

        bundle = build_bundle((memory,), anonymize=True)

        self.assertEqual(len(bundle.memories), 1)
        em = bundle.memories[0]
        real_user = getpass.getuser()
        expected_scrubbed, _ = scrub(real_user, anonymize=True)
        self.assertEqual(em.provenance.origin_user, expected_scrubbed)


# ---------------------------------------------------------------------------
# TestFrontmatterFromDict
# ---------------------------------------------------------------------------


class TestFrontmatterFromDict(unittest.TestCase):
    def test_raw_type_none_produces_none_type_field(self):
        """_frontmatter_from_dict with type=None should set MemoryFrontmatter.type to None."""
        data = {
            "name": "no_type_memory",
            "description": "a memory with no type",
            "type": None,
            "node_type": "memory",
            "modified": None,
            "shape": "nested",
            "unknown_keys": {},
        }
        fm = _frontmatter_from_dict(data)
        self.assertIsNone(fm.type)
        self.assertEqual(fm.name, "no_type_memory")

    def test_raw_type_absent_produces_none_type_field(self):
        """_frontmatter_from_dict with type key missing also yields type=None."""
        data = {
            "name": "missing_type",
            "shape": "absent",
        }
        fm = _frontmatter_from_dict(data)
        self.assertIsNone(fm.type)


# ---------------------------------------------------------------------------
# TestLoadBundleEdgeCases
# ---------------------------------------------------------------------------


class TestLoadBundleEdgeCases(MemoryTestCase):
    def test_yaml_error_raises_value_error(self):
        """Malformed YAML that fails to parse raises ValueError with 'failed to parse'."""
        f = self.tmp / "bad_yaml.yaml"
        f.write_text("bundle_version: 1\ncreated_at: [bad\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "failed to parse"):
            load_bundle(f)

    def test_non_dict_top_level_raises_value_error(self):
        """A YAML list at the top level raises ValueError mentioning 'mapping'."""
        f = self.tmp / "list_top.yaml"
        f.write_text("- one\n- two\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "mapping"):
            load_bundle(f)

    def test_non_list_memories_raises_value_error(self):
        """memories field that is not a list raises ValueError."""
        import yaml

        f = self.tmp / "non_list_memories.yaml"
        data = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "notes": None,
            "memories": "not a list",
        }
        f.write_text(yaml.dump(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "memories.*list"):
            load_bundle(f)

    def test_non_dict_memory_entry_raises_value_error(self):
        """A non-dict memory entry (e.g. a string) inside memories raises ValueError."""
        import yaml

        f = self.tmp / "non_dict_entry.yaml"
        data = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "notes": None,
            "memories": ["this is a string, not a dict"],
        }
        f.write_text(yaml.dump(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "mapping"):
            load_bundle(f)

    def test_missing_created_at_falls_back_to_now(self):
        """When created_at is absent (None), load_bundle falls back to datetime.now(UTC)."""
        import yaml

        f = self.tmp / "no_created_at.yaml"
        data = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": None,
            "notes": None,
            "memories": [],
        }
        f.write_text(yaml.dump(data), encoding="utf-8")

        before = datetime.now(UTC)
        bundle = load_bundle(f)
        after = datetime.now(UTC)

        self.assertIsNotNone(bundle.created_at.tzinfo)
        self.assertGreaterEqual(bundle.created_at, before)
        self.assertLessEqual(bundle.created_at, after)


# ---------------------------------------------------------------------------
# TestSerializeBundleInvalidFormat
# ---------------------------------------------------------------------------


class TestSerializeBundleInvalidFormat(MemoryTestCase):
    def test_invalid_format_raises_value_error(self):
        """serialize_bundle with an unknown format raises ValueError."""
        bundle = sample_bundle()
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            serialize_bundle(bundle, "toml")

    def test_valid_yaml_does_not_raise(self):
        bundle = sample_bundle()
        result = serialize_bundle(bundle, "yaml")
        self.assertIsInstance(result, str)
        self.assertIn("bundle_version", result)

    def test_valid_json_does_not_raise(self):
        bundle = sample_bundle()
        result = serialize_bundle(bundle, "json")
        self.assertIsInstance(result, str)
        self.assertIn("bundle_version", result)


if __name__ == "__main__":
    unittest.main()
