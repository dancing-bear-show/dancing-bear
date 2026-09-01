"""Tests for core.pdf_forms AcroForm field helpers."""

import unittest

from core.pdf_forms import (
    DEFAULT_FONT_SIZES,
    FALLBACK_FONT_SIZE,
    fill_text_fields,
    font_size_for,
    format_da,
    set_checkbox,
    set_text_field,
)


class TestFontSizeFor(unittest.TestCase):
    def test_narrow_date_and_phone_cells_shrink(self):
        for field in (
            "dateOfBirthYear",
            "dateOfBirthMonth",
            "dateOfBirthDate",
            "2.day_phone.area",
            "2.day_phone.number1",
            "2.day_phone.number2",
            "5.date.day",
        ):
            self.assertEqual(font_size_for(field), 7, field)

    def test_repeated_row_suffixes_match_by_prefix(self):
        # Claimant rows 1-4 are named 4.DOB.year, 4.DOB.year2, ... A prefix
        # rule must cover every row without enumerating the suffixes.
        for field in ("4.DOB.year", "4.DOB.year2", "4.DOB.month3", "4.DOB.day4"):
            self.assertEqual(font_size_for(field), 7, field)

    def test_currency_fields_use_intermediate_size(self):
        self.assertEqual(font_size_for("3.total_claimed.0"), 8)
        self.assertEqual(font_size_for("3.total_claimed.5"), 8)

    def test_wide_fields_keep_template_default(self):
        for field in ("lastName", "firstName", "certNumber", "addressLine1"):
            self.assertEqual(font_size_for(field), FALLBACK_FONT_SIZE, field)

    def test_unknown_field_uses_fallback(self):
        self.assertEqual(font_size_for("someBrandNewField"), FALLBACK_FONT_SIZE)

    def test_longest_prefix_wins_regardless_of_mapping_order(self):
        sizes = {"4.": 9, "4.DOB.": 7, "4.DOB.year": 6}
        self.assertEqual(font_size_for("4.DOB.year", sizes), 6)
        self.assertEqual(font_size_for("4.DOB.month", sizes), 7)
        self.assertEqual(font_size_for("4.other", sizes), 9)

    def test_custom_sizes_override_defaults(self):
        self.assertEqual(font_size_for("lastName", {"lastName": 5}), 5)

    def test_default_table_is_not_mutated_by_callers(self):
        before = dict(DEFAULT_FONT_SIZES)
        font_size_for("lastName", {"lastName": 5})
        self.assertEqual(DEFAULT_FONT_SIZES, before)


class TestFormatDa(unittest.TestCase):
    def test_wraps_value_in_pdf_string_parentheses(self):
        # xref_set_key writes the value verbatim. Without the parentheses this
        # is not a PDF string literal, /DA silently stores null, and viewers
        # auto-size the text LARGER than the template default.
        self.assertEqual(format_da(7), "(0 g /Helv 7 Tf)")

    def test_honours_font_and_colour_overrides(self):
        self.assertEqual(format_da(9, font="TiRo", color="0.5 g"), "(0.5 g /TiRo 9 Tf)")


class FakeWidget:
    """Stand-in for a PyMuPDF widget, matching the attributes used here."""

    def __init__(self, field_name, xref, field_type_string, states=None):
        self.field_name = field_name
        self.xref = xref
        self.field_type_string = field_type_string
        self._states = states

    def button_states(self):
        return self._states


class FakeDoc:
    """Minimal fitz.Document double recording every xref_set_key write."""

    def __init__(self, pages):
        self._pages = pages
        self.writes = []

    @property
    def page_count(self):
        return len(self._pages)

    def __getitem__(self, pno):
        page = self._pages[pno]

        class _Page:
            @staticmethod
            def widgets():
                return page

        return _Page()

    def xref_set_key(self, xref, key, value):
        self.writes.append((xref, key, value))

    def written(self, xref, key):
        for x, k, v in self.writes:
            if (x, k) == (xref, key):
                return v
        return None


class TestSetTextField(unittest.TestCase):
    def _doc(self):
        return FakeDoc([[
            FakeWidget("lastName", 10, "Text"),
            FakeWidget("2.day_phone.area", 11, "Text"),
            FakeWidget("1.language", 12, "CheckBox", {"normal": ["Off", "Eng"]}),
        ]])

    def test_writes_value_and_sized_da_and_clears_appearance(self):
        doc = self._doc()
        self.assertEqual(set_text_field(doc, "2.day_phone.area", "416"), 1)
        self.assertEqual(doc.written(11, "V"), "(416)")
        self.assertEqual(doc.written(11, "DA"), "(0 g /Helv 7 Tf)")
        # The cached appearance stream must be dropped or the viewer keeps
        # rendering the old text at the old size.
        self.assertEqual(doc.written(11, "AP"), "null")

    def test_wide_field_keeps_default_size(self):
        doc = self._doc()
        set_text_field(doc, "lastName", "Sherwin")
        self.assertEqual(doc.written(10, "DA"), "(0 g /Helv 9 Tf)")

    def test_ignores_non_text_widgets_with_the_same_name(self):
        doc = self._doc()
        self.assertEqual(set_text_field(doc, "1.language", "Eng"), 0)
        self.assertEqual(doc.writes, [])

    def test_returns_zero_when_no_widget_matches(self):
        doc = self._doc()
        self.assertEqual(set_text_field(doc, "renamedOnNewTemplate", "x"), 0)


class TestFillTextFields(unittest.TestCase):
    def _doc(self):
        return FakeDoc([[FakeWidget("lastName", 10, "Text"),
                         FakeWidget("firstName", 11, "Text")]])

    def test_fills_all_fields_and_reports_counts(self):
        doc = self._doc()
        counts = fill_text_fields(doc, {"lastName": "Sherwin", "firstName": "Brian"})
        self.assertEqual(counts, {"lastName": 1, "firstName": 1})
        self.assertEqual(doc.written(10, "V"), "(Sherwin)")
        self.assertEqual(doc.written(11, "V"), "(Brian)")

    def test_raises_on_unmatched_field_by_default(self):
        # A template revision that renames a field would otherwise produce a
        # blank form with no error at all.
        with self.assertRaises(KeyError) as ctx:
            fill_text_fields(self._doc(), {"lastName": "Sherwin", "gone": "x"})
        self.assertIn("gone", str(ctx.exception))

    def test_require_all_false_tolerates_unmatched_fields(self):
        counts = fill_text_fields(
            self._doc(), {"lastName": "Sherwin", "gone": "x"}, require_all=False
        )
        self.assertEqual(counts, {"lastName": 1, "gone": 0})


class TestSetCheckbox(unittest.TestCase):
    def _pair(self):
        # A Yes/No pair: ONE field name, two widgets, distinguished only by
        # their on-state. This is the shape that makes name-level setting tick
        # both boxes at once.
        return FakeDoc([[
            FakeWidget("2.member_another_plan", 20, "CheckBox", {"normal": ["Off", "Yes"]}),
            FakeWidget("2.member_another_plan", 21, "CheckBox", {"normal": ["Off", "No"]}),
        ]])

    def test_ticks_only_the_matching_widget_of_a_shared_name_pair(self):
        doc = self._pair()
        self.assertEqual(set_checkbox(doc, "2.member_another_plan", "Yes"), 2)
        self.assertEqual(doc.written(20, "AS"), "/Yes")
        self.assertEqual(doc.written(20, "V"), "/Yes")
        # The sibling must be explicitly turned off, not merely left alone.
        self.assertEqual(doc.written(21, "AS"), "/Off")
        self.assertEqual(doc.written(21, "V"), "null")

    def test_none_clears_both_widgets(self):
        doc = self._pair()
        set_checkbox(doc, "2.member_another_plan", None)
        self.assertEqual(doc.written(20, "AS"), "/Off")
        self.assertEqual(doc.written(21, "AS"), "/Off")

    def test_unknown_on_state_clears_rather_than_guessing(self):
        doc = self._pair()
        set_checkbox(doc, "2.member_another_plan", "Maybe")
        self.assertEqual(doc.written(20, "AS"), "/Off")
        self.assertEqual(doc.written(21, "AS"), "/Off")

    def test_tolerates_widget_with_no_button_states(self):
        # button_states() returns None for non-button widgets, and a button
        # may carry {"normal": None}. Neither may raise.
        doc = FakeDoc([[
            FakeWidget("cb", 30, "CheckBox", None),
            FakeWidget("cb", 31, "CheckBox", {"normal": None}),
        ]])
        self.assertEqual(set_checkbox(doc, "cb", "Yes"), 2)
        self.assertEqual(doc.written(30, "AS"), "/Off")
        self.assertEqual(doc.written(31, "AS"), "/Off")

    def test_ignores_text_widgets_with_the_same_name(self):
        doc = FakeDoc([[FakeWidget("shared", 40, "Text")]])
        self.assertEqual(set_checkbox(doc, "shared", "Yes"), 0)
        self.assertEqual(doc.writes, [])


if __name__ == "__main__":
    unittest.main()
