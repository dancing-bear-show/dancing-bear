"""Shared docx-building fixtures for tests/resume_tests/docx_tests/.

Extracted from test_docx_standard.py and test_docx_truncation_warnings.py,
which had byte-identical copies of _make_mock_doc (module-level function,
not a class fixture — see test_docx_writer.py for an unrelated
self._make_mock_doc() static method that is a different shape and out of
scope here).
"""

from __future__ import annotations

from unittest.mock import MagicMock


def make_mock_doc():
    """Make a mock Document that tracks paragraphs and headings."""
    doc = MagicMock()
    paragraphs = []

    def _make_para(text="", **_kwargs):
        p = MagicMock()
        p.text = text
        p.paragraph_format = MagicMock()
        p.alignment = None
        paragraphs.append(p)
        return p

    doc.add_heading = MagicMock(side_effect=_make_para)
    doc.add_paragraph = MagicMock(side_effect=_make_para)
    doc.paragraphs = paragraphs
    doc.styles = {}
    doc.sections = [MagicMock()]
    doc.core_properties = MagicMock()
    return doc
