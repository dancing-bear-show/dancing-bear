"""Fake python-docx objects for testing.

Provides fake Document, Paragraph, and Run objects that mimic the python-docx
library's interface without requiring the actual library.
"""

from __future__ import annotations

from unittest.mock import MagicMock


class FakeStyle:
    """Fake docx Style object for testing."""

    def __init__(self, name: str = "Normal"):
        self.name = name


class FakeRun:
    """Fake docx Run object for testing."""

    def __init__(self):
        self.text = ""
        self.bold = False
        self.italic = False


class FakeParagraph:
    """Fake docx Paragraph object for testing.

    ``text`` is derived from the runs, as it is in python-docx, rather than
    being a field frozen at construction. The real ``Paragraph.text`` is a
    read-only property that concatenates the run texts, so a paragraph built
    as ``add_paragraph()`` followed by ``add_run("X")`` reads back as "X".

    A fake that stored only the constructor argument reported such a paragraph
    as empty, which made a renderer switching from ``add_paragraph(text)`` to
    ``add_paragraph()`` + ``add_run(text)`` -- the change needed to weight part
    of a line -- look like it had stopped emitting the text at all. That is a
    difference between the fake and python-docx, not a difference in output.
    """

    def __init__(self, text: str = "", style: str = "Normal"):
        self.style = FakeStyle(style)
        self.runs: list = []
        self.paragraph_format = MagicMock()
        if text:
            self.add_run(text)

    @property
    def text(self) -> str:
        """Concatenated run text, matching ``docx.text.paragraph.Paragraph``."""
        return "".join(r.text for r in self.runs)

    def add_run(self, text: str = "") -> FakeRun:
        r = FakeRun()
        r.text = text
        self.runs.append(r)
        return r


class FakeDocument:
    """Fake docx Document for testing."""

    def __init__(self):
        self.paragraphs: list = []

    def add_paragraph(self, text: str = "", style: str = "Normal") -> FakeParagraph:
        p = FakeParagraph(text, style)
        self.paragraphs.append(p)
        return p
