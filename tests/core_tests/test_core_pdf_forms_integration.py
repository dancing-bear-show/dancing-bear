"""Round-trip tests for core.pdf_forms against real PyMuPDF.

The companion suite (``test_core_pdf_forms.py``) drives these helpers through
``FakeDoc``/``FakeWidget`` stubs, which record every ``xref_set_key`` call.
That proves the helpers *ask* for the right writes; it cannot prove a real PDF
accepts them, because the stub is also the thing being asserted against. A
change to the AcroForm keys written -- or to how PyMuPDF interprets them --
passes the stub suite unchanged.

These tests build a real in-memory AcroForm, write through the helpers, save,
reopen, and assert on what the reopened document reports. Save-and-reopen is
the point: values held on a live object may never have reached the file.

A missing PyMuPDF is a **failure, not a skip**. The first revision of this
file skipped the whole class when ``fitz`` was absent, which would have hidden
precisely the regression this suite exists to catch: if the ``[pdf]`` extra
ever falls out of the install line again, eight skips still report a green
``tests`` job and nobody reads the skip count. That is the same fail-open
shape as the ``jq`` guard in ``tests/infra/test_guard_hooks.py``, and it is
handled the same way -- an assertion with an actionable message.

PyMuPDF ships in the ``[pdf]`` extra, installed by ``make test`` (Makefile)
and by CI's ``tests`` job (.github/workflows/ci.yml).
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from core.pdf_forms import (
    DEFAULT_FONT_SIZES,
    FALLBACK_FONT_SIZE,
    _widget_index,
    fill_text_fields,
    set_checkbox,
    set_text_field,
)

try:
    import fitz
except ImportError:  # pragma: no cover - the assertion below reports this
    fitz = None


_MISSING_FITZ = (
    "PyMuPDF is not installed, so these round-trip tests cannot run. This is a "
    "failure rather than a skip: a skipped run reports green while exercising "
    "none of the real-document behaviour, which is the regression this suite "
    "exists to catch. Install it with `pip install -e \".[pdf]\"` -- `make test` "
    "and CI both request the extra."
)


# The suppressions in the two builders below sit on PyMuPDF's write-only
# Widget attributes: they are read inside ``page.add_widget()``, so vulture
# sees a write with no read.
#
# Suppressed per line rather than through ``ignore_names``, which applies to
# the whole repository: a name listed there is never reported again anywhere,
# so a genuinely dead ``field_type`` or ``rect`` in unrelated code would go
# unseen. The per-line form keeps the exemption where the justification is.
#
# (Spelling the directive out in this comment would make ruff parse it as a
# real one and warn about the missing rule codes, so it is described instead.)
def _add_text(page, name: str, y: float, *, fontsize: int = 11) -> None:
    w = fitz.Widget()
    w.field_name = name
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT  # noqa
    w.rect = fitz.Rect(50, y, 300, y + 20)  # noqa
    w.field_value = ""
    w.text_fontsize = fontsize
    page.add_widget(w)


def _add_checkbox(page, name: str, y: float) -> None:
    w = fitz.Widget()
    w.field_name = name
    w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX  # noqa
    w.rect = fitz.Rect(50, y, 65, y + 15)  # noqa
    w.field_value = False
    page.add_widget(w)


class PdfFormsRoundTripTests(unittest.TestCase):
    """Write through the helpers, then read the saved file back."""

    def setUp(self):
        self.assertIsNotNone(fitz, _MISSING_FITZ)
        self.doc = fitz.open()
        page = self.doc.new_page(width=400, height=400)
        _add_text(page, "applicant_name", 50)
        _add_text(page, "2.day_phone.area", 90)
        _add_checkbox(page, "agree", 130)
        self.addCleanup(self.doc.close)

    def _reopen(self):
        """Save to disk and reopen, returning {field_name: widget}."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name, "form.pdf")
        self.doc.save(str(path))
        reopened = fitz.open(str(path))
        self.addCleanup(reopened.close)
        self._reopened = reopened
        return {
            w.field_name: w
            for pno in range(reopened.page_count)
            for w in (reopened[pno].widgets() or [])
        }

    def _as_of(self, widget) -> str:
        """The widget's /AS appearance state in the document just reopened."""
        return self._reopened.xref_get_key(widget.xref, "AS")[1]

    def test_set_text_field_value_survives_save_and_reopen(self):
        self.assertEqual(set_text_field(self.doc, "applicant_name", "Ada Lovelace"), 1)
        widgets = self._reopen()
        self.assertEqual(widgets["applicant_name"].field_value, "Ada Lovelace")

    def test_unmatched_field_name_writes_nothing(self):
        # Zero is the documented signal that a template field was renamed.
        self.assertEqual(set_text_field(self.doc, "no_such_field", "x"), 0)
        widgets = self._reopen()
        self.assertEqual(widgets["applicant_name"].field_value, "")

    def test_narrow_field_gets_the_smaller_font_size(self):
        # font_size_for maps the phone-part prefix to 7pt and leaves wide
        # fields at the fallback 9pt. Assert the sizes actually stored in the
        # file, not just the ones the helper computed.
        #
        # Both expectations are literals, deliberately. An earlier revision
        # used assertNotEqual(..., 7) for the wide field, which passes for any
        # size that is not 7 -- changing the fallback to 22pt left the suite
        # green. Importing the constants instead does not fix that: the test
        # and the code would move together, so the assertion would restate the
        # implementation rather than pin the contract. Verified by mutation --
        # 9 -> 22 now fails this test.
        set_text_field(self.doc, "2.day_phone.area", "604")
        set_text_field(self.doc, "applicant_name", "Ada Lovelace")
        widgets = self._reopen()
        self.assertEqual(widgets["2.day_phone.area"].text_fontsize, 7)
        self.assertEqual(widgets["applicant_name"].text_fontsize, 9)

    def test_the_constants_still_match_the_sizes_pinned_above(self):
        # The literals above are the contract; these are the knobs. If someone
        # deliberately changes a size, this fails alongside the round-trip test
        # and points at the decision rather than at a mysterious 9.
        self.assertEqual(DEFAULT_FONT_SIZES["2.day_phone."], 7)
        self.assertEqual(FALLBACK_FONT_SIZE, 9)

    def test_fill_text_fields_writes_every_named_field(self):
        counts = fill_text_fields(
            self.doc,
            {"applicant_name": "Grace Hopper", "2.day_phone.area": "250"},
        )
        self.assertEqual(counts, {"applicant_name": 1, "2.day_phone.area": 1})
        widgets = self._reopen()
        self.assertEqual(widgets["applicant_name"].field_value, "Grace Hopper")
        self.assertEqual(widgets["2.day_phone.area"].field_value, "250")

    def test_fill_text_fields_raises_on_a_missing_field(self):
        with self.assertRaises(KeyError) as ctx:
            fill_text_fields(self.doc, {"applicant_name": "ok", "ghost": "x"})
        self.assertIn("ghost", str(ctx.exception))

    def test_checkbox_ticks_through_a_real_document(self):
        self.assertEqual(set_checkbox(self.doc, "agree", "Yes"), 1)
        widget = self._reopen()["agree"]
        self.assertEqual(widget.field_value, "Yes")
        # /AS is asserted alongside /V because the two can disagree: writing
        # the value alone leaves the appearance state at /Off, which renders
        # as an empty box while reporting "Yes".
        self.assertEqual(self._as_of(widget), "/Yes")

    def test_checkbox_cleared_with_none_has_no_value(self):
        # A cleared box is NOT read back as "Off". set_checkbox writes
        # ``V = null`` for the off state, and PyMuPDF surfaces a null /V as
        # the empty string -- an untouched widget reports "Off", a cleared one
        # reports "". Both are unticked; only the second has been written.
        # The stub suite cannot distinguish these, because it asserts on the
        # literal "null" handed to xref_set_key rather than on what a reader
        # reports afterwards.
        set_checkbox(self.doc, "agree", "Yes")
        self.assertEqual(set_checkbox(self.doc, "agree", None), 1)
        self.assertEqual(self._reopen()["agree"].field_value, "")

    def test_untouched_checkbox_reports_off_not_empty(self):
        # The control for the case above: without a write, /V is genuinely
        # "Off". This is what makes "" meaningful rather than incidental.
        self.assertEqual(self._reopen()["agree"].field_value, "Off")


class CheckboxSiblingPairTests(unittest.TestCase):
    """A Yes/No pair sharing one field name, distinguished by on-state.

    This is the helper's real contract and the reason it writes each widget's
    xref individually: setting the *field* would tick both boxes at once.
    A single-widget test cannot show that, because there is no sibling to
    leave alone.

    Building the pair takes a detour. ``page.add_widget`` gives every checkbox
    the on-state ``Yes``, so the second widget's ``/AP /N`` dictionary is
    rewritten to key its on-appearance under ``No``. Renaming by writing
    ``AP/N/No`` and nulling ``AP/N/Yes`` is NOT enough -- the nulled key stays
    in the dictionary, ``_on_states`` still reports ``Yes`` first, and both
    widgets tick. The whole sub-dictionary has to be replaced.
    """

    def setUp(self):
        self.assertIsNotNone(fitz, _MISSING_FITZ)
        self.doc = fitz.open()
        page = self.doc.new_page(width=300, height=300)
        for i in range(2):
            _add_checkbox(page, "member_another_plan", 20 + i * 40)
        self.addCleanup(self.doc.close)

        self.xrefs = [
            w.xref
            for pno in range(self.doc.page_count)
            for w in (self.doc[pno].widgets() or [])
        ]
        _kind, val = self.doc.xref_get_key(self.xrefs[1], "AP/N")
        self.doc.xref_set_key(self.xrefs[1], "AP/N", val.replace("/Yes ", "/No "))

    def _values(self):
        """Reopen and return {xref: (field_value, appearance_state)}.

        Both halves matter. ``/V`` is what a reader reports; ``/AS`` is the
        appearance state a *viewer* renders. They can disagree: writing ``/V``
        alone yields a widget that reports "Yes" while still drawing the Off
        appearance -- a box that is ticked in the data and blank on the page.
        Asserting only ``field_value`` cannot see that, so both are returned.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name, "pair.pdf")
        self.doc.save(str(path))
        reopened = fitz.open(str(path))
        self.addCleanup(reopened.close)
        return {
            w.xref: (w.field_value, reopened.xref_get_key(w.xref, "AS")[1])
            for pno in range(reopened.page_count)
            for w in (reopened[pno].widgets() or [])
        }

    def test_the_fixture_really_builds_two_distinct_on_states(self):
        # Without this the pair tests could pass against two identical Yes
        # widgets, asserting nothing about sibling handling.
        states = [s for _n, _x, _t, s in _widget_index(self.doc)]
        self.assertEqual(states, [["Yes"], ["No"]])

    def test_ticking_yes_clears_the_no_sibling(self):
        self.assertEqual(set_checkbox(self.doc, "member_another_plan", "Yes"), 2)
        values = self._values()
        # The sibling was written off, so its value is "" rather than "Off" --
        # same distinction as test_checkbox_cleared_with_none_has_no_value.
        self.assertEqual(values[self.xrefs[0]], ("Yes", "/Yes"))
        self.assertEqual(values[self.xrefs[1]], ("", "/Off"))

    def test_ticking_no_clears_the_yes_sibling(self):
        # The mirror image: whichever widget owns the requested on-state wins,
        # so a helper that keyed off widget order rather than on-state would
        # pass the test above and fail this one.
        self.assertEqual(set_checkbox(self.doc, "member_another_plan", "No"), 2)
        values = self._values()
        self.assertEqual(values[self.xrefs[0]], ("", "/Off"))
        self.assertEqual(values[self.xrefs[1]], ("No", "/No"))

    def test_clearing_the_field_leaves_neither_ticked(self):
        set_checkbox(self.doc, "member_another_plan", "Yes")
        self.assertEqual(set_checkbox(self.doc, "member_another_plan", None), 2)
        self.assertEqual(set(self._values().values()), {("", "/Off")})


if __name__ == "__main__":
    unittest.main()
