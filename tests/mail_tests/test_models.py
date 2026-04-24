"""Tests for mail/models.py data models."""

from __future__ import annotations

import unittest

from mail.models import LabelMapping


class TestLabelMappingFromLabels(unittest.TestCase):
    """Tests for LabelMapping.from_labels constructor."""

    def test_builds_id_to_name(self):
        """id_to_name maps label id -> name."""
        labels = [{"id": "Label_1", "name": "Work"}, {"id": "Label_2", "name": "Personal"}]
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.id_to_name, {"Label_1": "Work", "Label_2": "Personal"})

    def test_builds_name_to_id(self):
        """name_to_id maps label name -> id."""
        labels = [{"id": "Label_1", "name": "Work"}, {"id": "Label_2", "name": "Personal"}]
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.name_to_id, {"Work": "Label_1", "Personal": "Label_2"})

    def test_empty_list_produces_empty_dicts(self):
        """Empty label list yields both dicts empty."""
        mapping = LabelMapping.from_labels([])
        self.assertEqual(mapping.id_to_name, {})
        self.assertEqual(mapping.name_to_id, {})

    def test_single_label(self):
        """Single label produces single-entry dicts."""
        labels = [{"id": "INBOX", "name": "Inbox"}]
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.id_to_name, {"INBOX": "Inbox"})
        self.assertEqual(mapping.name_to_id, {"Inbox": "INBOX"})

    def test_returns_label_mapping_instance(self):
        """from_labels returns a LabelMapping instance."""
        mapping = LabelMapping.from_labels([])
        self.assertIsInstance(mapping, LabelMapping)

    def test_duplicate_names_last_id_wins(self):
        """When two labels share a name, name_to_id keeps the last entry."""
        labels = [
            {"id": "Label_1", "name": "Dup"},
            {"id": "Label_2", "name": "Dup"},
        ]
        mapping = LabelMapping.from_labels(labels)
        # id_to_name keeps both ids
        self.assertIn("Label_1", mapping.id_to_name)
        self.assertIn("Label_2", mapping.id_to_name)
        # name_to_id: last writer wins
        self.assertEqual(mapping.name_to_id["Dup"], "Label_2")

    def test_duplicate_ids_last_name_wins(self):
        """When two labels share an id, id_to_name keeps the last entry."""
        labels = [
            {"id": "Label_1", "name": "First"},
            {"id": "Label_1", "name": "Second"},
        ]
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.id_to_name["Label_1"], "Second")


class TestLabelMappingDirectConstruction(unittest.TestCase):
    """Tests for direct LabelMapping instantiation."""

    def test_default_name_to_id_is_empty(self):
        """name_to_id defaults to an empty dict when omitted."""
        mapping = LabelMapping(id_to_name={"Label_1": "Work"})
        self.assertEqual(mapping.name_to_id, {})

    def test_default_factory_does_not_share_state(self):
        """Two instances with default name_to_id are independent objects."""
        m1 = LabelMapping(id_to_name={})
        m2 = LabelMapping(id_to_name={})
        m1.name_to_id["x"] = "y"
        self.assertNotIn("x", m2.name_to_id)

    def test_explicit_name_to_id(self):
        """Explicitly supplied name_to_id is stored as-is."""
        mapping = LabelMapping(id_to_name={}, name_to_id={"Work": "Label_1"})
        self.assertEqual(mapping.name_to_id, {"Work": "Label_1"})


if __name__ == "__main__":
    unittest.main()
