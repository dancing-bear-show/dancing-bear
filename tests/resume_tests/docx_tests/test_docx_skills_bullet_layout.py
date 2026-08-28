"""Rendered-output contract for skills groups and sidebar entry alignment.

These assert properties of the *rendered* .docx rather than of a fake document,
because both properties under test are only observable once paragraphs exist:
"how many bullet glyphs ended up inside one paragraph" is not a call the
renderer makes, it is a shape the output has.

The style target is a single-column resume that uses ``Normal`` paragraphs with
a literal "• " prefix and never nests a glyph inside a paragraph. No content
from that document appears here -- every fixture value below is invented.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from resume.docx_writer import write_resume_docx
from resume.schema import Resume

from tests.resume_tests.golden.golden_fixtures import sidebar_template, standard_template

BULLET = "•"

# The reference document's longest bullet paragraph. A group collapsed into one
# paragraph blows past this immediately, so it doubles as a ceiling check.
REFERENCE_MAX_PARAGRAPH_CHARS = 310


def _all_paragraphs(path: str) -> list:
    """Every paragraph in the document, including those inside table cells.

    The sidebar layout puts its content in a table, so a body-only walk would
    silently skip that entire layout.
    """
    import docx

    doc = docx.Document(path)
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    return paragraphs


def _render(resume_data: dict, template: dict) -> list:
    """Render a fixture through the public writer and return its paragraphs."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "resume.docx")
        write_resume_docx(Resume.from_dict(resume_data), template, out)
        return _all_paragraphs(out)


def _multi_group_skills(group_count: int = 7, items_per_group: int = 6) -> dict:
    """A skills-group resume shaped like a real one: several groups, long descs.

    Sized deliberately: the collapsing bug is proportional to items-per-group,
    so a two-item fixture would still fit on one line and hide the defect.
    """
    groups = []
    for gi in range(group_count):
        groups.append({
            "title": f"Group {gi}",
            "items": [
                {
                    "name": f"Capability {gi}-{i}",
                    "desc": "a representative description of the capability "
                            "and the context where it was applied",
                }
                for i in range(items_per_group)
            ],
        })
    return {"name": "Example Candidate", "headline": "Example Headline",
            "skills_groups": groups}


class SkillsGroupBulletLayoutTests(unittest.TestCase):
    """Each skill item renders as its own bullet paragraph."""

    def test_no_paragraph_contains_more_than_one_bullet_glyph(self):
        """The regression that would silently return: items joined into one run.

        Asserted directly on glyph counts rather than on paragraph count,
        because a renderer could emit the right number of paragraphs and still
        bury separators inside them.
        """
        paragraphs = _render(_multi_group_skills(), standard_template())

        offenders = [p.text for p in paragraphs if p.text.count(BULLET) > 1]
        self.assertEqual(
            offenders, [],
            f"{len(offenders)} paragraph(s) hold more than one '{BULLET}'; "
            "skill items were joined into a single paragraph instead of "
            "getting one paragraph each.",
        )

    def test_each_skill_item_is_its_own_paragraph(self):
        """Every item appears as a bullet paragraph carrying only that item."""
        data = _multi_group_skills(group_count=2, items_per_group=3)
        paragraphs = _render(data, standard_template())

        bullet_texts = [p.text for p in paragraphs if p.text.strip().startswith(BULLET)]
        for gi in range(2):
            for i in range(3):
                needle = f"Capability {gi}-{i}"
                matches = [t for t in bullet_texts if needle in t]
                self.assertEqual(
                    len(matches), 1,
                    f"expected exactly one bullet paragraph for {needle}, got {matches}",
                )

    def test_group_title_renders_unprefixed(self):
        """The group name is its own line and carries no bullet glyph."""
        data = _multi_group_skills(group_count=2, items_per_group=2)
        paragraphs = _render(data, standard_template())

        titles = [p.text for p in paragraphs if p.text.strip() in ("Group 0", "Group 1")]
        self.assertEqual(
            sorted(titles), ["Group 0", "Group 1"],
            "group titles must render on their own line, unprefixed and "
            "not folded into the first item's paragraph",
        )

    def test_no_paragraph_exceeds_reference_maximum_length(self):
        """A collapsed group produces one oversized prose paragraph."""
        paragraphs = _render(_multi_group_skills(), standard_template())

        longest = max((len(p.text) for p in paragraphs), default=0)
        self.assertLessEqual(
            longest, REFERENCE_MAX_PARAGRAPH_CHARS,
            f"longest paragraph is {longest} chars, over the "
            f"{REFERENCE_MAX_PARAGRAPH_CHARS}-char reference maximum",
        )

    def test_sidebar_layout_also_avoids_multi_bullet_paragraphs(self):
        """The same property holds for the two-column layout."""
        paragraphs = _render(_multi_group_skills(), sidebar_template())

        offenders = [p.text for p in paragraphs if p.text.count(BULLET) > 1]
        self.assertEqual(offenders, [])


class SidebarEntryIndentTests(unittest.TestCase):
    """A sidebar entry's bullet line and its continuation lines agree.

    The sidebar is a table layout with its own hanging-indent convention: the
    glyph is a run inside the headline paragraph (so the headline text already
    starts past it) and continuation lines carry an explicit 0.25" indent to
    line up underneath that text. Education, experience and presentations all
    use it, so it is pinned here as the shared local contract rather than
    per-section.
    """

    CONTINUATION_INDENT_EMU = 228600  # 0.25"

    def _entry_fixture(self) -> dict:
        return {
            "name": "Example Candidate",
            "education": [
                {"degree": "BSc Example", "institution": "Example University",
                 "year": "2010"},
            ],
            "experience": [
                {"title": "Example Role", "company": "Example Co",
                 "start": "2020", "end": "2024",
                 "bullets": [{"text": "an example accomplishment line"}]},
            ],
            "presentations": [
                {"title": "Example Talk Title", "authors": "A. Author",
                 "event": "Example Conference 2019", "note": "an example note"},
            ],
        }

    def test_presentation_continuations_share_the_sidebar_indent(self):
        """Authors, event and note all sit at the shared continuation indent."""
        paragraphs = _render(self._entry_fixture(), sidebar_template())
        by_text = {p.text.strip(): p for p in paragraphs if p.text.strip()}

        for line in ("A. Author", "Example Conference 2019", "an example note"):
            self.assertIn(line, by_text)
            self.assertEqual(
                by_text[line].paragraph_format.left_indent,
                self.CONTINUATION_INDENT_EMU,
                f"{line!r} must sit at the sidebar continuation indent so it "
                "aligns under the bullet line's text",
            )

    def test_presentation_bullet_line_matches_other_sidebar_sections(self):
        """The glyph-bearing headline is unindented in every sidebar section."""
        paragraphs = _render(self._entry_fixture(), sidebar_template())

        headlines = [
            p for p in paragraphs if p.text.strip().startswith(BULLET)
        ]
        self.assertGreaterEqual(len(headlines), 3, "expected edu/exp/pres headlines")
        for p in headlines:
            self.assertIsNone(
                p.paragraph_format.left_indent,
                f"{p.text!r} carries an explicit indent; sidebar bullet lines "
                "hang the glyph at the margin instead",
            )
