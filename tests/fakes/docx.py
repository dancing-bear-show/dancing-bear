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
    """Fake docx Paragraph object for testing."""

    def __init__(self, text: str = "", style: str = "Normal"):
        self.text = text
        self.style = FakeStyle(style)
        self.runs: list = []
        self.paragraph_format = MagicMock()

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
