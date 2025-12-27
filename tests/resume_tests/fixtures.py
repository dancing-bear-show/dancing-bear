"""Resume-specific test fixtures.

Docx document fakes and helpers for testing resume rendering.
"""

from __future__ import annotations

from unittest.mock import MagicMock


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
        self.style = style
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
