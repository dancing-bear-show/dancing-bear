"""Tests for mail/models.py."""
import unittest

from mail.models import LabelMapping


class TestLabelMapping(unittest.TestCase):
    """Test LabelMapping dataclass."""

    def test_init_with_both_dicts(self):
        """Test initialization with both id_to_name and name_to_id."""
        id_to_name = {"1": "inbox", "2": "sent"}
        name_to_id = {"inbox": "1", "sent": "2"}
        mapping = LabelMapping(id_to_name=id_to_name, name_to_id=name_to_id)
        self.assertEqual(mapping.id_to_name, id_to_name)
        self.assertEqual(mapping.name_to_id, name_to_id)

    def test_init_with_only_id_to_name(self):
        """Test initialization with only id_to_name (name_to_id defaults to empty)."""
        id_to_name = {"1": "inbox", "2": "sent"}
        mapping = LabelMapping(id_to_name=id_to_name)
        self.assertEqual(mapping.id_to_name, id_to_name)
        self.assertEqual(mapping.name_to_id, {})

    def test_from_labels(self):
        """Test creating LabelMapping from Gmail labels list."""
        labels = [
            {"id": "INBOX", "name": "INBOX"},
            {"id": "SENT", "name": "SENT"},
            {"id": "Label_1", "name": "Work"},
            {"id": "Label_2", "name": "Personal"},
        ]
        mapping = LabelMapping.from_labels(labels)

        # Verify id_to_name mapping
        self.assertEqual(mapping.id_to_name["INBOX"], "INBOX")
        self.assertEqual(mapping.id_to_name["SENT"], "SENT")
        self.assertEqual(mapping.id_to_name["Label_1"], "Work")
        self.assertEqual(mapping.id_to_name["Label_2"], "Personal")

        # Verify name_to_id mapping
        self.assertEqual(mapping.name_to_id["INBOX"], "INBOX")
        self.assertEqual(mapping.name_to_id["SENT"], "SENT")
        self.assertEqual(mapping.name_to_id["Work"], "Label_1")
        self.assertEqual(mapping.name_to_id["Personal"], "Label_2")

    def test_from_labels_empty_list(self):
        """Test creating LabelMapping from empty labels list."""
        labels = []
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.id_to_name, {})
        self.assertEqual(mapping.name_to_id, {})

    def test_from_labels_single_label(self):
        """Test creating LabelMapping from single label."""
        labels = [{"id": "test_id", "name": "Test Label"}]
        mapping = LabelMapping.from_labels(labels)
        self.assertEqual(mapping.id_to_name, {"test_id": "Test Label"})
        self.assertEqual(mapping.name_to_id, {"Test Label": "test_id"})


if __name__ == "__main__":
    unittest.main()
