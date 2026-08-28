"""Inline markup at the renderer level: which fields honour it, and which do not.

The parser itself is tested in ``tests/resume_tests/test_inline_markup.py``.
These tests assert that markup survives all the way to real runs on a
paragraph, per candidate prose field, and that template-supplied chrome is
deliberately left alone.
"""
from __future__ import annotations

import unittest

from resume.schema import Resume
from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules


def runs_of(paragraph) -> list[tuple[str, bool, bool]]:
    """Return a paragraph's runs as ``(text, bold, italic)`` triples."""
    return [(r.text, bool(r.bold), bool(r.italic)) for r in paragraph.runs]


def emphasised(doc) -> dict[str, tuple[bool, bool]]:
    """Map run text -> (bold, italic) for every emphasised run in a document."""
    return {
        r.text: (bool(r.bold), bool(r.italic))
        for p in doc.paragraphs
        for r in p.runs
        if r.bold or r.italic
    }


def all_text(doc) -> str:
    """Concatenate every run's text across the document."""
    return "".join(r.text for p in doc.paragraphs for r in p.runs)


@mock_docx_modules
class TestBulletRendererMarkup(unittest.TestCase):
    """Markup resolves to runs through the shared bullet mechanism."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_bold_markup_becomes_a_bold_run(self):
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Led **the platform team**", glyph="•")
        self.assertEqual(
            runs_of(doc.paragraphs[0]),
            [("• ", False, False), ("Led ", False, False), ("the platform team", True, False)],
        )

    def test_italic_markup_becomes_an_italic_run(self):
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Shipped *continuously*", glyph="•")
        self.assertEqual(
            runs_of(doc.paragraphs[0]),
            [("• ", False, False), ("Shipped ", False, False), ("continuously", False, True)],
        )

    def test_plain_bullet_text_stays_a_single_run(self):
        """No markup means the glyph run plus exactly one text run."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Reduced incident volume", glyph="•")
        self.assertEqual(len(doc.paragraphs[0].runs), 2)

    def test_literal_asterisks_survive_rendering(self):
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("5 * 3 = 15 for file*.txt", glyph="•")
        self.assertEqual(
            runs_of(doc.paragraphs[0]),
            [("• ", False, False), ("5 * 3 = 15 for file*.txt", False, False)],
        )

    def test_named_bullet_description_honours_markup(self):
        """The description half of a named bullet is prose and takes markup."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "used **daily** in production", glyph="•")
        self.assertEqual(emphasised(doc), {"Python": (True, False), "daily": (True, False)})

    def test_named_bullet_name_strips_markup_rather_than_printing_it(self):
        """The name half is bold by construction, so delimiters are removed."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("**Python**", "a language", glyph="•")
        self.assertNotIn("*", all_text(doc))
        self.assertEqual(runs_of(doc.paragraphs[0])[1], ("Python", True, False))

    def test_joined_paragraph_honours_markup(self):
        """The non-bullet joined form emits runs, so markup works there too."""
        renderer, doc = self._get_renderer()
        renderer.add_joined_paragraph(["**Alpha**", "plain", "*Beta*"], " • ")
        self.assertEqual(emphasised(doc), {"Alpha": (True, False), "Beta": (False, True)})
        self.assertEqual(all_text(doc), "Alpha • plain • Beta")

    def test_joined_paragraph_without_markup_stays_a_single_run(self):
        """Unmarked input keeps the pre-feature run structure, byte for byte.

        Splitting an unmarked joined paragraph into per-item runs leaves the
        visible text identical but rewrites ``word/document.xml``, which moves
        every render golden that uses the ``bullets: false`` branch. The split
        is only paid for when some item actually carries markup.
        """
        renderer, doc = self._get_renderer()
        renderer.add_joined_paragraph(["Leadership", "Planning"], " • ")
        self.assertEqual(
            runs_of(doc.paragraphs[0]), [("Leadership • Planning", False, False)]
        )

    def test_joined_paragraph_with_literal_asterisks_stays_a_single_run(self):
        """A literal asterisk is not markup, so it must not trigger the split."""
        renderer, doc = self._get_renderer()
        renderer.add_joined_paragraph(["5 * 3", "file*.txt"], " • ")
        self.assertEqual(
            runs_of(doc.paragraphs[0]), [("5 * 3 • file*.txt", False, False)]
        )


@mock_docx_modules
class TestMarkupAndKeywordBolding(unittest.TestCase):
    """Markup and keyword bolding compose without fighting or double-wrapping."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_keyword_inside_bold_markup_stays_one_run(self):
        """An author-bolded span is not re-split by the keyword pass."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Scaled **Kubernetes clusters**", keywords=["Kubernetes"], glyph="•"
        )
        self.assertEqual(
            runs_of(doc.paragraphs[0]),
            [
                ("• ", False, False),
                ("Scaled ", False, False),
                ("Kubernetes clusters", True, False),
            ],
        )

    def test_keyword_inside_italic_markup_is_bold_and_italic(self):
        """The keyword goes bold; the span's italic flag is preserved."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Ran *Python jobs*", keywords=["Python"], glyph="•")
        self.assertEqual(
            runs_of(doc.paragraphs[0]),
            [
                ("• ", False, False),
                ("Ran ", False, False),
                ("Python", True, True),
                (" jobs", False, True),
            ],
        )

    def test_keyword_bolding_still_applies_outside_markup(self):
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Used Terraform and **Ansible**", keywords=["Terraform"], glyph="•"
        )
        self.assertEqual(
            emphasised(doc), {"Terraform": (True, False), "Ansible": (True, False)}
        )

    def test_keyword_bolding_alone_is_unchanged_by_the_markup_pass(self):
        """Text with no markup behaves exactly as it did before this feature."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python and JavaScript",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        self.assertEqual(
            emphasised(doc), {"Python": (True, False), "JavaScript": (True, False)}
        )

    def test_literal_asterisk_with_keywords_is_not_swallowed(self):
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Scaled 5 * 3 Python nodes", keywords=["Python"], glyph="•")
        self.assertEqual(all_text(doc), "• Scaled 5 * 3 Python nodes")


@mock_docx_modules
class TestMarkupPerCandidateField(unittest.TestCase):
    """Every covered prose field renders markup as runs -- asserted per field."""

    def _render(self, renderer_class, candidate: dict, sec: dict | None = None, **kw):
        from tests.fakes.docx import FakeDocument
        doc = FakeDocument()
        renderer = renderer_class(doc)
        renderer.render(Resume.from_dict(candidate), sec, **kw)
        return doc

    def test_summary_items_honour_markup(self):
        from resume.docx_sections_skills import SummarySectionRenderer
        doc = self._render(
            SummarySectionRenderer,
            {"summary": [{"text": "Led **platform teams** across *three* orgs"}]},
        )
        self.assertEqual(
            emphasised(doc), {"platform teams": (True, False), "three": (False, True)}
        )

    def test_prose_summary_honours_markup(self):
        """The scalar/prose summary branch, not just the bulleted one."""
        from resume.docx_sections_skills import SummarySectionRenderer
        doc = self._render(
            SummarySectionRenderer, {"summary": "Engineer with **deep** SRE experience"}
        )
        self.assertEqual(emphasised(doc), {"deep": (True, False)})

    def test_experience_bullets_honour_markup(self):
        from resume.docx_sections_exp import ExperienceSectionRenderer
        doc = self._render(
            ExperienceSectionRenderer,
            {
                "experience": [
                    {
                        "title": "SRE",
                        "company": "Acme",
                        "bullets": [{"text": "Cut toil by **40%** using *automation*"}],
                    }
                ]
            },
        )
        self.assertEqual(emphasised(doc)["40%"], (True, False))
        self.assertEqual(emphasised(doc)["automation"], (False, True))

    def test_skills_item_descriptions_honour_markup(self):
        from resume.docx_sections_skills import SkillsSectionRenderer
        doc = self._render(
            SkillsSectionRenderer,
            {
                "skills_groups": [
                    {
                        "title": "Languages",
                        "items": [{"name": "Python", "desc": "used **daily**"}],
                    }
                ]
            },
            {"bullets": True, "show_desc": True, "desc_separator": ": "},
        )
        self.assertEqual(emphasised(doc)["daily"], (True, False))

    def test_interests_honour_markup(self):
        from resume.docx_sections_simple import InterestsSectionRenderer
        doc = self._render(
            InterestsSectionRenderer, {"interests": [{"text": "**Cycling** and *chess*"}]}
        )
        self.assertEqual(
            emphasised(doc), {"Cycling": (True, False), "chess": (False, True)}
        )

    def test_presentations_honour_markup(self):
        from resume.docx_sections_simple import PresentationsSectionRenderer
        doc = self._render(
            PresentationsSectionRenderer,
            {"presentations": [{"title": "Scaling **Nurse**", "event": "SREcon"}]},
        )
        self.assertEqual(emphasised(doc)["Nurse"], (True, False))

    def test_technologies_honour_markup(self):
        from resume.docx_sections_skills import TechnologiesSectionRenderer
        doc = self._render(
            TechnologiesSectionRenderer,
            {"technologies": [{"name": "**Kubernetes**"}]},
            {"bullets": True},
        )
        self.assertEqual(emphasised(doc)["Kubernetes"], (True, False))

    def test_coursework_honours_markup(self):
        from resume.docx_sections_simple import CourseworkSectionRenderer
        doc = self._render(
            CourseworkSectionRenderer,
            {"coursework": [{"name": "**Distributed Systems**"}]},
        )
        self.assertEqual(emphasised(doc)["Distributed Systems"], (True, False))

    def test_languages_honour_markup(self):
        from resume.docx_sections_simple import LanguagesSectionRenderer
        doc = self._render(
            LanguagesSectionRenderer,
            {"languages": [{"name": "**English**", "level": "native"}]},
        )
        self.assertEqual(emphasised(doc)["English"], (True, False))

    def test_certifications_honour_markup(self):
        from resume.docx_sections_simple import CertificationsSectionRenderer
        doc = self._render(
            CertificationsSectionRenderer, {"certifications": [{"name": "**CKA**"}]}
        )
        self.assertEqual(emphasised(doc)["CKA"], (True, False))

    def test_teaching_honours_markup(self):
        from resume.docx_sections_simple import TeachingSectionRenderer
        doc = self._render(
            TeachingSectionRenderer, {"teaching": [{"name": "**Mentoring** juniors"}]}
        )
        self.assertEqual(emphasised(doc)["Mentoring"], (True, False))

    def test_literal_asterisks_survive_in_experience_bullets(self):
        """The backward-compatibility guarantee, asserted end to end."""
        from resume.docx_sections_exp import ExperienceSectionRenderer
        doc = self._render(
            ExperienceSectionRenderer,
            {"experience": [{"title": "SRE", "bullets": [{"text": "Ran 5 * 3 jobs"}]}]},
        )
        self.assertIn("Ran 5 * 3 jobs", all_text(doc))
        # Only the bullet paragraph is checked for stray emphasis: the header
        # line above it bolds the job title by design, independent of markup.
        bullet = doc.paragraphs[-1]
        self.assertEqual(
            runs_of(bullet), [("• ", False, False), ("Ran 5 * 3 jobs", False, False)]
        )


@mock_docx_modules
class TestChromeIgnoresMarkup(unittest.TestCase):
    """Template-supplied chrome must NOT be reinterpreted as markup."""

    def test_experience_header_fields_are_not_parsed(self):
        """Titles, companies, locations and dates keep their characters verbatim.

        A header is chrome assembled by the renderer, not authored prose, so an
        asterisk in it stays an asterisk rather than becoming emphasis.
        """
        from tests.fakes.docx import FakeDocument
        from resume.docx_sections_exp import ExperienceSectionRenderer
        doc = FakeDocument()
        ExperienceSectionRenderer(doc).render(
            Resume.from_dict(
                {
                    "experience": [
                        {"title": "**SRE**", "company": "Acme", "start": "2020"}
                    ]
                }
            )
        )
        self.assertIn("**SRE**", all_text(doc))

    def test_group_titles_are_not_parsed(self):
        from tests.fakes.docx import FakeDocument
        from resume.docx_renderers import HeaderRenderer
        doc = FakeDocument()
        HeaderRenderer(doc).add_group_title("**Languages**", {})
        self.assertIn("**Languages**", all_text(doc))


if __name__ == "__main__":
    unittest.main()
