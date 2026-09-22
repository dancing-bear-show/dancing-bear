"""Generate a synthetic BLANK claim template for the font-size migration proof.

The migration in claims-domain-build.yaml has to prove that moving the
insurer's field-size prefixes out of core.pdf_forms does not change how a form
renders. That proof needs a form to fill.

It must not be a real one. Insurer-supplied claim templates are personalised:
the IBM template on the author's machine arrives pre-populated with member ID,
full name, date of birth and home address, so it carries PII before any claim
is filled. And accepting a caller-supplied path is worse than useless as a
safeguard -- checking whether a PDF is blank means reading its page text, so a
filled claim would be read before it could be rejected.

So this builds one: a real AcroForm with the same field NAMES the size map
keys on, every widget empty, and no personal data anywhere. Field names are
not personal data; they are the form's schema.

Covers the five size-mapped prefixes plus representative wide fields:
    dateOfBirth*      2.day_phone.*     4.DOB.*
    5.date.*          3.total_claimed.*
    lastName  firstName  certNumber  addressLine1

Run: python3 tests/receipts_fixtures/build_claim_template.py
"""
from __future__ import annotations

import pathlib

import fitz

HERE = pathlib.Path(__file__).parent
OUT = HERE / "blank_claim_template.pdf"

# (field_name, label, x, y) -- laid out in two columns, no overlap.
FIELDS: list[tuple[str, str]] = [
    ("certNumber", "Member ID number"),
    ("lastName", "Your last name"),
    ("firstName", "First name"),
    ("addressLine1", "Your address"),
    ("dateOfBirthYear", "DOB year"),
    ("dateOfBirthMonth", "DOB month"),
    ("dateOfBirthDate", "DOB day"),
    ("2.day_phone.area", "Phone area"),
    ("2.day_phone.number1", "Phone 1"),
    ("2.day_phone.number2", "Phone 2"),
    ("5.date.year", "Signed year"),
    ("5.date.month", "Signed month"),
    ("5.date.day", "Signed day"),
    ("4.DOB.year", "Claimant 1 DOB year"),
    ("4.DOB.month", "Claimant 1 DOB month"),
    ("4.DOB.day", "Claimant 1 DOB day"),
    ("4.DOB.year2", "Claimant 2 DOB year"),
    ("4.DOB.month2", "Claimant 2 DOB month"),
    ("4.DOB.day2", "Claimant 2 DOB day"),
    ("3.total_claimed.0", "Amount claimed 1"),
    ("3.total_claimed.1", "Amount claimed 2"),
    ("3.total_claimed.5", "Total claimed"),
]


def build(path: pathlib.Path = OUT) -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((54, 48), "SYNTHETIC CLAIM TEMPLATE -- TEST FIXTURE",
                     fontsize=12, fontname="hebo")
    page.insert_text((54, 64), "Not an insurer form. No personal data.",
                     fontsize=8, fontname="helv")

    y = 96
    for name, label in FIELDS:
        page.insert_text((54, y), label, fontsize=7, fontname="helv")
        widget = fitz.Widget()
        widget.field_name = name
        # The three suppressions below: PyMuPDF reads these inside
        # add_widget(), so vulture sees write-only attributes. Scoped per line
        # rather than through ignore_names, which applies to the whole
        # repository — a name listed there is never reported again anywhere,
        # so a genuinely dead field_type or rect in unrelated code would go
        # unseen.
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT  # noqa
        widget.rect = fitz.Rect(220, y - 9, 380, y + 5)  # noqa
        widget.field_value = ""
        # 9pt matches the insurer template's own default, which is what makes
        # the migration's before/after comparison meaningful.
        widget.text_fontsize = 9  # noqa
        page.add_widget(widget)
        y += 26

    doc.save(path)
    doc.close()


if __name__ == "__main__":
    build()
    doc = fitz.open(OUT)
    widgets = [w for pno in range(doc.page_count) for w in (doc[pno].widgets() or [])]
    filled = [w.field_name for w in widgets if (w.field_value or "").strip()]
    text = " ".join(p.get_text() for p in doc)
    doc.close()
    print(f"  {OUT.name}: {len(widgets)} widgets, {len(filled)} filled, "
          f"{len(text)} chars of page text")
