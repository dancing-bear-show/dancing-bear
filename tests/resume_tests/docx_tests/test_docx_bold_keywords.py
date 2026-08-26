"""Regression tests for BulletRenderer._bold_keywords text duplication.

When no keyword matched, the method emitted the text twice — the loop wrote the
remainder and broke with idx still 0, then the trailing fallback wrote it again.
The runs concatenated with no separator, so a rendered bullet read
"...audit systems at scaleInstrumented and monitored access-control..." while
the DOCX still looked structurally valid.

The invariant every test asserts: concatenating the runs must reproduce the
input exactly.
"""

from __future__ import annotations

import unittest

from docx import Document

from resume.docx_renderers import BulletRenderer


def _render(text: str, keywords: list[str]):
    doc = Document()
    para = doc.add_paragraph()
    BulletRenderer(doc)._bold_keywords(para, text, keywords)
    return para


class TestBoldKeywordsRoundTrip(unittest.TestCase):
    """Runs must always reassemble into the original string."""

    def test_rejects_duplicating_text_with_no_keyword_match(self):
        """Regression: unmatched text was emitted twice."""
        text = "Instrumented and monitored access-control systems"
        para = _render(text, ["AWS", "Kafka"])
        self.assertEqual("".join(r.text for r in para.runs), text)
        self.assertEqual(len(para.runs), 1)
        self.assertFalse(any(r.bold for r in para.runs))

    def test_bolds_multiple_keywords(self):
        text = "Built on AWS and Kafka today"
        para = _render(text, ["AWS", "Kafka"])
        self.assertEqual("".join(r.text for r in para.runs), text)
        self.assertEqual([r.text for r in para.runs if r.bold], ["AWS", "Kafka"])

    def test_bolds_keyword_at_string_boundaries(self):
        for text, kw in [("AWS at the start", "AWS"), ("ends with Kafka", "Kafka")]:
            with self.subTest(text=text):
                para = _render(text, [kw])
                self.assertEqual("".join(r.text for r in para.runs), text)
                self.assertEqual([r.text for r in para.runs if r.bold], [kw])

    def test_bolds_repeated_keyword_every_occurrence(self):
        text = "AWS here and AWS there"
        para = _render(text, ["AWS"])
        self.assertEqual("".join(r.text for r in para.runs), text)
        self.assertEqual(len([r for r in para.runs if r.bold]), 2)

    def test_invalid_empty_text_emits_nothing_duplicated(self):
        para = _render("", ["AWS"])
        self.assertEqual("".join(r.text for r in para.runs), "")

    def test_invalid_empty_keyword_list_leaves_text_intact(self):
        text = "No keywords supplied here"
        para = _render(text, [])
        self.assertEqual("".join(r.text for r in para.runs), text)
        self.assertFalse(any(r.bold for r in para.runs))

    def test_rejects_matching_keyword_absent_from_text(self):
        """A keyword that never appears must not alter the output."""
        text = "Plain prose without any technology names"
        para = _render(text, ["Kubernetes", "Terraform"])
        self.assertEqual("".join(r.text for r in para.runs), text)
        self.assertFalse(any(r.bold for r in para.runs))


if __name__ == "__main__":
    unittest.main()
