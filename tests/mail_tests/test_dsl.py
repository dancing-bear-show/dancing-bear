import unittest

from mail.dsl import (
    normalize_label_color_outlook,
    normalize_labels_for_outlook,
    normalize_filter_for_outlook,
    normalize_filters_for_outlook,
)


class DslNormalizeTests(unittest.TestCase):
    def test_normalize_label_color_outlook_accepts_string_name(self):
        self.assertEqual(normalize_label_color_outlook("preset3"), {"name": "preset3"})

    def test_normalize_label_color_outlook_accepts_dict_name(self):
        self.assertEqual(normalize_label_color_outlook({"name": "preset1"}), {"name": "preset1"})

    def test_normalize_label_color_outlook_ignores_hex(self):
        # Hex colors are ignored for Outlook normalization (no mapping yet)
        self.assertIsNone(normalize_label_color_outlook({"backgroundColor": "#ffffff"}))

    def test_normalize_labels_for_outlook_dedup_and_name_modes(self):
        labels = [
            {"name": "Work/HR", "color": {"name": "preset2"}},
            {"name": "Work/HR", "color": {"name": "preset3"}},  # duplicate, should be dropped
            {"name": "Lists/Commercial", "color": "preset4"},
        ]

        # default: join-dash
        out_default = normalize_labels_for_outlook(labels)
        self.assertEqual(
            out_default,
            [
                {"name": "Work-HR", "color": {"name": "preset2"}},
                {"name": "Lists-Commercial", "color": {"name": "preset4"}},
            ],
        )

        # first component only
        out_first = normalize_labels_for_outlook(labels, name_mode="first")
        self.assertEqual(
            out_first,
            [
                {"name": "Work", "color": {"name": "preset2"}},
                {"name": "Lists", "color": {"name": "preset4"}},
            ],
        )

        # join with colon
        out_colon = normalize_labels_for_outlook(labels, name_mode="join-colon")
        self.assertEqual(
            out_colon,
            [
                {"name": "Work:HR", "color": {"name": "preset2"}},
                {"name": "Lists:Commercial", "color": {"name": "preset4"}},
            ],
        )

    def test_normalize_filter_for_outlook_basic_fields(self):
        spec = {
            "match": {"from": "a@b.com", "to": "me@example.com", "subject": "hi", "ignore": "x"},
            "action": {"add": ["A", "", None], "forward": "fwd@x", "moveToFolder": "Archive/Receipts", "noop": True},
        }
        out = normalize_filter_for_outlook(spec)
        self.assertEqual(
            out,
            {
                "match": {"from": "a@b.com", "to": "me@example.com", "subject": "hi"},
                "action": {"add": ["A"], "forward": "fwd@x", "moveToFolder": "Archive/Receipts"},
            },
        )

    def test_normalize_filter_for_outlook_rejects_empty(self):
        self.assertIsNone(normalize_filter_for_outlook({}))
        self.assertIsNone(normalize_filter_for_outlook({"match": {}, "action": {}}))

    def test_normalize_filters_for_outlook_maps_list(self):
        inp = [
            {"match": {"from": "a@b"}, "action": {"add": ["X"]}},
            {},  # will be dropped
        ]
        out = normalize_filters_for_outlook(inp)
        self.assertEqual(out, [{"match": {"from": "a@b"}, "action": {"add": ["X"]}}])


if __name__ == "__main__":
    unittest.main()

