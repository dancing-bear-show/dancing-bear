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


class MalformedSpecTests(unittest.TestCase):
    """Non-dict and empty specs are dropped rather than raising.

    These normalizers read user-authored YAML, where a stray scalar or a
    mistyped list entry is ordinary. Nothing here should reach a traceback.
    """

    def test_non_dict_spec_returns_none(self):
        for value in (None, "nope", 42, [], ["match"], ()):
            with self.subTest(value=value):
                self.assertIsNone(normalize_filter_for_outlook(value))

    def test_filters_list_drops_non_dict_entries(self):
        out = normalize_filters_for_outlook([None, "x", 42, {"match": {"from": "a@b"}}])
        self.assertEqual(out, [{"match": {"from": "a@b"}, "action": {}}])

    def test_filters_list_handles_none(self):
        # Deliberately off-annotation: `filters or []` accepts None at runtime,
        # and an empty YAML `filters:` key parses to exactly that.
        self.assertEqual(normalize_filters_for_outlook(None), [])  # type: ignore[arg-type]

    def test_filters_list_handles_empty(self):
        self.assertEqual(normalize_filters_for_outlook([]), [])

    def test_match_only_spec_is_kept(self):
        """A spec with criteria but no action is still a usable rule."""
        out = normalize_filter_for_outlook({"match": {"from": "a@b"}})
        self.assertEqual(out, {"match": {"from": "a@b"}, "action": {}})

    def test_action_only_spec_is_kept(self):
        out = normalize_filter_for_outlook({"action": {"forward": "f@x"}})
        self.assertEqual(out, {"match": {}, "action": {"forward": "f@x"}})

    def test_falsy_match_values_are_dropped(self):
        out = normalize_filter_for_outlook(
            {"match": {"from": "a@b", "to": None, "subject": ""}}
        )
        self.assertEqual(out["match"], {"from": "a@b"})

    def test_non_string_scalars_are_coerced(self):
        """YAML `from: 123` is unquoted-number slip, not a crash."""
        out = normalize_filter_for_outlook(
            {"match": {"from": 123}, "action": {"forward": 456, "moveToFolder": 789}}
        )
        self.assertEqual(out["match"]["from"], "123")
        self.assertEqual(out["action"]["forward"], "456")
        self.assertEqual(out["action"]["moveToFolder"], "789")


class MalformedLabelTests(unittest.TestCase):
    """Label normalization skips junk entries instead of raising."""

    def test_non_dict_labels_are_skipped(self):
        self.assertEqual(normalize_labels_for_outlook([None, "x", 42, ()]), [])

    def test_none_and_empty_input(self):
        # Deliberately off-annotation: `labels or []` accepts None at runtime,
        # and an empty YAML `labels:` key parses to exactly that.
        self.assertEqual(normalize_labels_for_outlook(None), [])  # type: ignore[arg-type]
        self.assertEqual(normalize_labels_for_outlook([]), [])

    def test_missing_or_empty_name_is_skipped(self):
        self.assertEqual(normalize_labels_for_outlook([{"name": ""}, {"color": "preset1"}]), [])

    def test_label_without_color_omits_the_key(self):
        self.assertEqual(normalize_labels_for_outlook([{"name": "Work"}]), [{"name": "Work"}])

    def test_unknown_name_mode_falls_back_to_join_dash(self):
        out = normalize_labels_for_outlook([{"name": "A/B"}], name_mode="bogus-mode")
        self.assertEqual(out, [{"name": "A-B"}])

    def test_dedup_keeps_the_first_occurrence(self):
        """Dedup is post-normalization, so distinct sources can collide."""
        out = normalize_labels_for_outlook(
            [{"name": "A/B", "color": "preset1"}, {"name": "A/B", "color": "preset2"}]
        )
        self.assertEqual(out, [{"name": "A-B", "color": {"name": "preset1"}}])

    def test_distinct_names_collapsing_to_one_are_deduped(self):
        """`first` mode maps Work/HR and Work/IT onto the same Outlook name."""
        out = normalize_labels_for_outlook(
            [{"name": "Work/HR"}, {"name": "Work/IT"}], name_mode="first"
        )
        self.assertEqual(out, [{"name": "Work"}])


class LabelColorTests(unittest.TestCase):
    """Color coercion, including the shapes that yield nothing."""

    def test_none_and_empty_yield_none(self):
        for value in (None, "", {}):
            with self.subTest(value=value):
                self.assertIsNone(normalize_label_color_outlook(value))

    def test_dict_without_name_yields_none(self):
        self.assertIsNone(normalize_label_color_outlook({"backgroundColor": "#fff"}))

    def test_unrecognized_preset_passes_through(self):
        """Pins current behaviour: names are not validated against the preset set."""
        self.assertEqual(normalize_label_color_outlook("bogus"), {"name": "bogus"})


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


class MappingAddValueTests(ScalarAddValueTests):
    """A mapping `add` must not be expanded into its keys.

    `add: {work: true, urgent: false}` is malformed -- every real spec writes
    `add` as a list of strings. Iterating it yields its KEYS, so it silently
    became ['work', 'urgent']: two plausible-looking labels, one of them from a
    key the author explicitly switched off. That is the same silent-wrong-value
    failure this class exists to prevent, so a dict is treated as a scalar --
    one obviously-wrong label the author can see, not several believable ones.
    """

    def test_mapping_is_not_expanded_into_keys(self):
        self.assertEqual(self._add({"work": True}), ["{'work': True}"])

    def test_mapping_does_not_invent_a_label_from_a_disabled_key(self):
        """The old behaviour was ['work', 'urgent'] -- two believable labels."""
        result = self._add({"work": True, "urgent": False})
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result, ["work", "urgent"])
        self.assertNotIn("urgent", result)

    def test_empty_mapping_omits_action_entirely(self):
        out = normalize_filters_for_outlook(
            [{"match": {"from": "a@b"}, "action": {"add": {}}}]
        )
        self.assertNotIn("add", out[0]["action"])


class BytesAddValueTests(ScalarAddValueTests):
    """bytes must decode to text, not stringify to their repr.

    `str(b"work")` is "b'work'", so a bytes label produced an Outlook rule
    named with the literal repr -- quotes, `b` prefix and all.
    """

    def test_scalar_bytes_decode(self):
        self.assertEqual(self._add(b"work"), ["work"])

    def test_bytes_inside_a_list_decode(self):
        self.assertEqual(self._add([b"work", b"urgent"]), ["work", "urgent"])

    def test_mixed_bytes_and_str_list(self):
        self.assertEqual(self._add([b"work", "urgent"]), ["work", "urgent"])

    def test_undecodable_bytes_do_not_raise(self):
        self.assertEqual(self._add(b"w\xffork"), ["w�ork"])

    def test_empty_bytes_omits_action_entirely(self):
        out = normalize_filters_for_outlook(
            [{"match": {"from": "a@b"}, "action": {"add": b""}}]
        )
        self.assertNotIn("add", out[0]["action"])


if __name__ == "__main__":
    unittest.main()

