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


class ScalarAddValueTests(unittest.TestCase):
    """`action.add` given a scalar must become one label, not one per character.

    `add` comes from user-authored YAML, and `add: work` instead of
    `add: [work]` is an easy slip. Iterating the raw value turned that single
    label into ['w','o','r','k'] -- four bogus Outlook rules from a missing
    pair of brackets -- and a scalar int raised TypeError outright. These feed
    `mail outlook rules sync`, so the wrong value reaches real mailbox rules.
    """

    def _add(self, value):
        out = normalize_filters_for_outlook(
            [{"match": {"from": "a@b"}, "action": {"add": value}}]
        )
        return out[0]["action"]["add"]

    def test_string_is_one_label_not_one_per_character(self):
        self.assertEqual(self._add("work"), ["work"])

    def test_multiword_string_stays_intact(self):
        self.assertEqual(self._add("Work Urgent"), ["Work Urgent"])

    def test_int_does_not_raise(self):
        self.assertEqual(self._add(123), ["123"])

    def test_list_is_unchanged(self):
        self.assertEqual(self._add(["work"]), ["work"])

    def test_multi_element_list_is_unchanged(self):
        self.assertEqual(self._add(["work", "urgent"]), ["work", "urgent"])

    def test_tuple_is_expanded(self):
        self.assertEqual(self._add(("a", "b")), ["a", "b"])

    def test_falsy_entries_are_still_dropped(self):
        self.assertEqual(self._add(["ok", "", None]), ["ok"])

    def test_falsy_scalar_omits_action_entirely(self):
        """A falsy add is skipped by the `if a.get("add")` guard, as before."""
        for value in ("", 0, None, []):
            with self.subTest(value=value):
                out = normalize_filters_for_outlook(
                    [{"match": {"from": "a@b"}, "action": {"add": value}}]
                )
                self.assertNotIn("add", out[0]["action"])


if __name__ == "__main__":
    unittest.main()

