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

Skipped when PyMuPDF is absent. It ships in the ``[pdf]`` extra, installed by
``make test``, so a skip here in CI means the extra stopped being installed.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from core.pdf_forms import fill_text_fields, set_checkbox, set_text_field

try:
    import fitz
except ImportError:  # pragma: no cover - exercised only without the [pdf] extra
    fitz = None


# The `# noqa` marks in the two builders below sit on PyMuPDF's write-only
# Widget attributes: they are read inside ``page.add_widget()``, so vulture
# sees a write with no read. Suppressed per line rather than via
# ``ignore_names``, which is global -- ``rect`` alone is used 28 times in
# src/diagrams/ for an unrelated Mermaid node shape.
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


@unittest.skipIf(fitz is None, "PyMuPDF not installed (pip install -e '.[pdf]')")
class PdfFormsRoundTripTests(unittest.TestCase):
    """Write through the helpers, then read the saved file back."""

    def setUp(self):
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
        return {
            w.field_name: w
            for pno in range(reopened.page_count)
            for w in (reopened[pno].widgets() or [])
        }

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
        # fields at the fallback. Assert the size actually stored in the file,
        # not just the one the helper computed.
        set_text_field(self.doc, "2.day_phone.area", "604")
        set_text_field(self.doc, "applicant_name", "Ada Lovelace")
        widgets = self._reopen()
        self.assertEqual(widgets["2.day_phone.area"].text_fontsize, 7)
        self.assertNotEqual(widgets["applicant_name"].text_fontsize, 7)

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
        self.assertEqual(self._reopen()["agree"].field_value, "Yes")

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


if __name__ == "__main__":
    unittest.main()
