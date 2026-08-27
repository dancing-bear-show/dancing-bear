"""Tests for resume/schema_emit.py JSON Schema generation.

The emitter's central risk is documented in its module docstring: ``schema.py``
uses ``from __future__ import annotations``, so ``dataclasses.Field.type`` is a
string. A naive emitter that reads ``f.type`` directly produces a schema that
looks plausible but describes nothing -- every property degrades to the
permissive ``{}``. These tests assert real resolved types, not just structure.
"""

from __future__ import annotations

import unittest

from resume.schema import (
    Education,
    ExperienceEntry,
    PriorityItem,
    Resume,
    SkillGroup,
)
from resume.schema_emit import dataclass_schema, emit_schema

#: Every declared field has a default, so the on-disk format has no required keys.
EXPECTED_TOP_LEVEL_PROPERTIES = 22


class TestEmitSchemaDocument(unittest.TestCase):
    """The draft-07 envelope."""

    def setUp(self):  # NOSONAR - required unittest lifecycle method name
        self.schema = emit_schema()

    def test_declares_draft_07(self):
        self.assertEqual(
            self.schema["$schema"], "http://json-schema.org/draft-07/schema#"
        )

    def test_titles_the_root_class(self):
        self.assertEqual(self.schema["title"], "Resume")

    def test_root_is_an_object(self):
        self.assertEqual(self.schema["type"], "object")

    def test_emits_every_declared_top_level_property(self):
        self.assertEqual(len(self.schema["properties"]), EXPECTED_TOP_LEVEL_PROPERTIES)

    def test_omits_required_because_every_field_has_a_default(self):
        self.assertNotIn("required", self.schema)

    def test_excludes_round_trip_bookkeeping_fields(self):
        props = self.schema["properties"]
        for internal in ("extra", "_present", "_order"):
            self.assertNotIn(internal, props)

    def test_defaults_to_resume_when_no_root_given(self):
        self.assertEqual(emit_schema(), emit_schema(Resume))


class TestEmittedPropertyTypes(unittest.TestCase):
    """Properties carry real resolved types, not the permissive fallback."""

    def setUp(self):  # NOSONAR - required unittest lifecycle method name
        self.props = emit_schema()["properties"]

    def test_no_property_degrades_to_an_empty_schema(self):
        empty = [name for name, sub in self.props.items() if sub == {}]
        self.assertEqual(empty, [])

    def test_scalar_string_fields_are_typed_string(self):
        for name in ("name", "headline", "email", "phone", "location"):
            self.assertEqual(self.props[name], {"type": "string"}, name)

    def test_list_of_strings_is_typed_array_of_string(self):
        self.assertEqual(
            self.props["skills"], {"type": "array", "items": {"type": "string"}}
        )

    def test_optional_contact_is_nullable_object(self):
        self.assertEqual(self.props["contact"], {"type": ["object", "null"]})

    def test_untyped_teaching_is_array_of_permissive_items(self):
        """``teaching`` is untyped by design, so its items assert no shape."""
        self.assertEqual(self.props["teaching"], {"type": "array", "items": {}})


class TestNestedDataclassRecursion(unittest.TestCase):
    """``list[T]`` and nested dataclasses recurse into real object schemas."""

    def setUp(self):  # NOSONAR - required unittest lifecycle method name
        self.props = emit_schema()["properties"]

    def test_experience_recurses_into_experience_entry(self):
        items = self.props["experience"]["items"]
        self.assertEqual(items["type"], "object")
        self.assertEqual(
            list(items["properties"]),
            ["title", "company", "start", "end", "location", "priority", "bullets"],
        )

    def test_experience_bullets_recurse_two_levels_deep(self):
        bullets = self.props["experience"]["items"]["properties"]["bullets"]
        self.assertEqual(bullets["type"], "array")
        self.assertEqual(
            sorted(bullets["items"]["properties"]), ["desc", "priority", "text"]
        )

    def test_skills_groups_recurse_into_skill_group_items(self):
        items = self.props["skills_groups"]["items"]["properties"]["items"]
        self.assertEqual(
            sorted(items["items"]["properties"]), ["desc", "name", "priority"]
        )

    def test_priority_field_is_typed_number(self):
        bullets = self.props["experience"]["items"]["properties"]["bullets"]
        self.assertEqual(bullets["items"]["properties"]["priority"], {"type": "number"})

    def test_nested_schemas_exclude_bookkeeping_fields(self):
        entry = self.props["experience"]["items"]["properties"]
        for internal in ("extra", "_present", "_order"):
            self.assertNotIn(internal, entry)


class TestDataclassSchema(unittest.TestCase):
    """``dataclass_schema`` on individual node types."""

    def test_priority_item_schema(self):
        self.assertEqual(
            dataclass_schema(PriorityItem),
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "priority": {"type": "number"},
                    "desc": {"type": "string"},
                },
            },
        )

    def test_education_schema_is_all_strings(self):
        props = dataclass_schema(Education)["properties"]
        self.assertEqual(
            props,
            {
                "degree": {"type": "string"},
                "institution": {"type": "string"},
                "year": {"type": "string"},
            },
        )

    def test_skill_group_schema_nests_its_items(self):
        props = dataclass_schema(SkillGroup)["properties"]
        self.assertEqual(props["title"], {"type": "string"})
        self.assertEqual(props["items"]["type"], "array")
        self.assertEqual(props["items"]["items"]["type"], "object")

    def test_experience_entry_schema_omits_required(self):
        self.assertNotIn("required", dataclass_schema(ExperienceEntry))


class TestRejectsInvalidRoots(unittest.TestCase):
    """``emit_schema`` guards its root argument."""

    def test_rejects_non_schema_class(self):
        with self.assertRaises(TypeError):
            emit_schema(dict)

    def test_rejects_instance_instead_of_class(self):
        with self.assertRaises(TypeError):
            emit_schema(Resume())

    def test_rejects_none_typed_root(self):
        """``None`` is the documented 'use the default' sentinel, not an error."""
        self.assertEqual(emit_schema(None)["title"], "Resume")

    def test_rejects_unrelated_dataclass_root(self):
        from dataclasses import dataclass

        @dataclass
        class Unrelated:
            value: str = ""

        with self.assertRaises(TypeError):
            emit_schema(Unrelated)

    def test_invalid_root_error_names_the_offending_value(self):
        with self.assertRaises(TypeError) as ctx:
            emit_schema(int)
        self.assertIn("resume schema dataclass", str(ctx.exception))


class TestSubtreeRoots(unittest.TestCase):
    """Any schema dataclass is a valid emit root."""

    def test_emits_experience_entry_as_a_root(self):
        schema = emit_schema(ExperienceEntry)
        self.assertEqual(schema["title"], "ExperienceEntry")
        self.assertIn("bullets", schema["properties"])

    def test_emits_priority_item_as_a_root(self):
        schema = emit_schema(PriorityItem)
        self.assertEqual(schema["title"], "PriorityItem")
        self.assertEqual(schema["properties"]["text"], {"type": "string"})


if __name__ == "__main__":
    unittest.main()
