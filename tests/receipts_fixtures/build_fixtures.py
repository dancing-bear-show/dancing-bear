"""Generate synthetic receipt PDFs that reproduce real-world parsing hazards.

These fixtures are SYNTHETIC. Real receipts carry patient names, addresses,
card numbers and prescribing physicians, so none of them may enter the repo.
Each fixture instead reproduces one *shape* observed in real data, with
invented values, so the parsers are tested against the label variance that
actually breaks them rather than against an idealised receipt.

Shapes encoded here, all confirmed against real files:

  jane_clinic.pdf       "Invoice #NNNNN-PNN" + "Payer Total  $190.00".
                        Covers Advanced Psychology, Aurora Speech, Balance
                        Family Chiropractic, Oak Ridges Physio, Massage Addict.

  jane_zero.pdf         Same shape, "Payer Total  $0.00". A provider that
                        direct-billed the insurer. MUST parse as 0.00, never
                        as None -- a $0 receipt is a valid parse and an
                        ineligible claim, and conflating the two silently
                        drops real receipts.

  invoice_total.pdf     "Total  $250.00" with no "Payer Total" anywhere. This
                        exact gap once understated a claim by $190 because the
                        parser only knew the "Payer Total" label.

  speech_aim.pdf        "Total Amount  $150.00" -- a third spelling.

  costco_pharmacy.pdf   OCR-degraded text: "!Patient Pays: 88.21 j", no dollar
                        sign, surrounding garble ("0/A ewe Pharmacies"). Real
                        Costco receipts are scans carrying a dirty OCR layer,
                        NOT clean text and NOT blank.

  costco_optical.pdf    Text layer present but carrying NO total label and NO
                        "$"-prefixed amount. Nothing to extract: this is the
                        genuine sidecar case, and the only one.

  image_only.pdf        A page with no text layer at all -- the OCR-fallback
                        trigger.

Run: python3 tests/receipts_fixtures/build_fixtures.py
"""
from __future__ import annotations

import pathlib

import fitz

HERE = pathlib.Path(__file__).parent

# Invented patient name shared by every fixture. Real receipts carry real
# patient names, addresses and prescribing physicians; none of that may enter
# the repo, so every fixture uses this placeholder.
PATIENT = "Pat Doe"
# Costco pharmacy prints the patient surname-first, so it needs its own form.
PATIENT_SURNAME_FIRST = "Doe, Pat"


def _page(doc: fitz.Document, lines: list[str], fontsize: int = 10) -> None:
    page = doc.new_page(width=612, height=792)
    y = 72
    for line in lines:
        page.insert_text((60, y), line, fontsize=fontsize, fontname="helv")
        y += 16


def jane_clinic(path: pathlib.Path) -> None:
    doc = fitz.open()
    _page(doc, [
        "Northside Therapy Associates Inc.",
        "100 Example Ave, Suite 4, Springfield, ON, X0X 0X0",
        "Tel: 555 555 0100  Email: billing@example-clinic.test",
        "",
        PATIENT,
        "1 Test Street, Springfield, ON, X0X 0X0",
        "",
        "Receipt",
        "Items and Payments",
        "",
        "August 28, 2026 - 2:30pm, Psychological Services (1 hour)",
        "A. Practitioner M.PSY, RP, License #000000",
        "Invoice #8254-P01",
        "$190.00",
        "Payer Total",
        "$190.00",
    ])
    doc.save(path)
    doc.close()


def jane_zero(path: pathlib.Path) -> None:
    """Direct-billed: patient owes nothing. Must parse as 0.00, not None."""
    doc = fitz.open()
    _page(doc, [
        "Springfield Physiotherapy Clinic",
        "200 Example Rd, Springfield, ON, X0X 0X0",
        "",
        PATIENT,
        "Receipt",
        "",
        "June 23, 2026 - 4:15pm, Physiotherapy Follow-up (30 minutes)",
        "B. Therapist Registered Physiotherapist, License #000000",
        "Invoice #19887-P01",
        "Insurer #0000000000 / 000000",
        "1x 1.xx.12 - Therapy",
        "-$96.00",
        "Payer Total",
        "$0.00",
    ])
    doc.save(path)
    doc.close()


def invoice_total(path: pathlib.Path) -> None:
    """No 'Payer Total' label -- only 'Total'. The $190 understatement case."""
    doc = fitz.open()
    _page(doc, [
        "Springfield Speech Services",
        "300 Example Blvd, Springfield, ON, X0X 0X0",
        "",
        PATIENT,
        "Invoice",
        "",
        "July 8, 2026 - 12:00pm, Speech-Language Pathology (60 minutes)",
        "C. Pathologist MS, SLP, License #000000",
        "Invoice #7037-P01",
        "Subtotal",
        "$250.00",
        "Total",
        "$250.00",
    ])
    doc.save(path)
    doc.close()


def speech_aim(path: pathlib.Path) -> None:
    """A third total spelling: 'Total Amount'."""
    doc = fitz.open()
    _page(doc, [
        "Example Speech Aim Centre",
        "400 Example Way, Springfield, ON, X0X 0X0",
        "",
        PATIENT,
        "Receipt",
        "",
        "August 17, 2026, Speech Therapy Session",
        "Invoice #66803-P01",
        "Total Amount",
        "$150.00",
    ])
    doc.save(path)
    doc.close()


def costco_pharmacy(path: pathlib.Path) -> None:
    """OCR-degraded scan: no '$', garbled surroundings, 'Patient Pays' label.

    Reproduces the real artefacts -- stray punctuation around the amount and
    mangled header words -- so a parser that assumes clean text fails here,
    which is the point.
    """
    doc = fitz.open()
    _page(doc, [
        "0/A ewe Pharmacies (Ontario) Ltd.",
        "35 Example Rd. Springfield",
        "9os-1eo-21os",
        "Rx:0000000",
        f"D {PATIENT_SURNAME_FIRST}",
        "Fri 14-Aug-2026",
        "3 ML Example Drug (1x4mg) 1mg",
        "DIN: 00000000",
        "Refills: 0",
        "Cost:",
        "253. 70",
        "Example Insurer Limited [EI] 169. 98",
        "!Patient Pays: 88.21 j",
        "OFFICIAL PRESCRIPTION RECEIPT",
    ])
    doc.save(path)
    doc.close()


def costco_optical(path: pathlib.Path) -> None:
    """Text layer present but no total label and no '$' amount at all.

    This is the genuine sidecar case: there is nothing in the text to extract,
    so neither a label parser nor OCR helps.
    """
    doc = fitz.open()
    _page(doc, [
        "EXAMPLE OPTICAL DEPARTMENT",
        "500 Example Pkwy, Springfield ON",
        "MEMBER 000000000000",
        "",
        "FRAME     EXAMPLE MODEL 52-18",
        "LENS      SINGLE VISION",
        "COATING   ANTI-REFLECTIVE",
        "",
        "ORDER 0000000",
        "PICKED UP 16-Aug-2026",
    ])
    doc.save(path)
    doc.close()


def image_only(path: pathlib.Path) -> None:
    """A page with no text layer -- triggers the OCR fallback path."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 60))
    pix.clear_with(255)
    page.insert_image(fitz.Rect(60, 60, 260, 120), pixmap=pix)
    doc.save(path)
    doc.close()


BUILDERS = {
    "jane_clinic.pdf": jane_clinic,
    "jane_zero.pdf": jane_zero,
    "invoice_total.pdf": invoice_total,
    "speech_aim.pdf": speech_aim,
    "costco_pharmacy.pdf": costco_pharmacy,
    "costco_optical.pdf": costco_optical,
    "image_only.pdf": image_only,
}


def build_all() -> None:
    for name, fn in BUILDERS.items():
        out = HERE / name
        fn(out)
        doc = fitz.open(out)
        text = " ".join(p.get_text() for p in doc)
        doc.close()
        print(f"  {name:22s} {len(text.strip()):5d} chars of text layer")


if __name__ == "__main__":
    build_all()
