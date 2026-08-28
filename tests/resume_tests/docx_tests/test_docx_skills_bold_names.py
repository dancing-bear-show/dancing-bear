"""Run-level weighting contract for the skills section.

The reference document this output is styled after bolds two things in its
skills section and nothing else there: the group title, and the name half of
each skill bullet up to the separator. The description after the separator
stays plain, and nothing in the section is italic.

WHY THESE ASSERT ON ``run.bold`` AND NOT ON TEXT
    Bolding changes no characters. The rendered text of a skills bullet is
    byte-identical before and after, so a test that reads ``paragraph.text``
    passes just as happily against unbolded output and pins nothing. The only
    observable difference is the run split and the ``bold`` flag on the runs,
    which is what every assertion here reads.

No content from the reference document appears here; every fixture value is
invented.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from resume.docx_sections_skills import DEFAULT_DESC_SEPARATOR
from resume.docx_writer import write_resume_docx
from resume.schema import Resume

GLYPH = "• "

# A skills section config that takes the bulleted branch with an explicit
# separator, matching the shipped templates.
_BULLETED_SKILLS = {
    "key": "skills",
    "title": "Skills",
    "bullets": True,
    "show_desc": True,
    "desc_separator": ": ",
}

# The same section with no bullets/separator keys at all, which is the shape
# the golden fixtures use and the branch that renders a group title.
_PLAIN_SKILLS = {"key": "skills", "title": "Skills"}

# Bulleted, but with no explicit ``desc_separator`` -- so the default applies.
# This is the configuration the name/desc split used to get wrong: the join
# defaulted to " — " while the re-split defaulted to ": ", so the split never
# matched and the name was never bold. Keep this fixture separator-free.
_BULLETED_DEFAULT_SEP = {
    "key": "skills",
    "title": "Skills",
    "bullets": True,
    "show_desc": True,
}

# The separator the renderer falls back to when config supplies none. There is
# exactly one such fallback (``docx_sections_skills.DEFAULT_DESC_SEPARATOR``),
# shared by the skills and technologies paths, and it matches the value every
# shipped template sets explicitly. Imported rather than restated so this file
# cannot drift from the renderer the way the two former defaults drifted apart.
DEFAULT_DESC_SEP = DEFAULT_DESC_SEPARATOR


def _template(skills_section: dict) -> dict:
    return {
        "page": {"compact": True, "body_pt": 10, "meta_pt": 9},
        "sections": [
            {"key": "summary", "title": "Summary"},
            dict(skills_section),
            {"key": "experience", "title": "Experience"},
            {"key": "education", "title": "Education"},
        ],
    }


def _resume(skills_groups: list) -> dict:
    """A resume carrying a summary, experience and education alongside skills.

    The non-skills sections are present so the blast-radius test has something
    to prove stayed plain. Without them it would assert over an empty set.
    """
    return {
        "name": "Ada Placeholder",
        "headline": "Staff Reliability Engineer",
        "summary": [
            {"text": "Runs imaginary systems at imaginary scale.", "priority": 1},
            {"text": "Mentors an invented team of six.", "priority": 2},
        ],
        "skills_groups": skills_groups,
        "experience": [
            {
                "title": "Staff Engineer",
                "company": "Nonexistent Systems",
                "start": "2021",
                "end": "2025",
                "bullets": [{"text": "Did an invented thing.", "priority": 1}],
            }
        ],
        "education": [
            {
                "degree": "BSc Imaginary Studies",
                "school": "Invented University",
                "end": "2015",
            }
        ],
    }


def _render(resume_data: dict, template: dict) -> list:
    """Render through the public writer and return the body paragraphs."""
    import docx

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "resume.docx")
        write_resume_docx(Resume.from_dict(resume_data), template, out)
        return list(docx.Document(out).paragraphs)


def _runs(paragraph) -> list[tuple[str, bool | None, bool | None]]:
    return [(r.text, r.bold, r.italic) for r in paragraph.runs]


def _find(paragraphs, text: str):
    """The one paragraph whose text matches exactly, or a failure."""
    matches = [p for p in paragraphs if p.text == text]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one paragraph {text!r}, found {len(matches)}: "
            f"{[p.text for p in paragraphs]}"
        )
    return matches[0]


class SkillItemBoldNameTests(unittest.TestCase):
    """A skill bullet bolds its name and leaves the rest plain."""

    def test_named_item_splits_into_glyph_bold_name_and_plain_remainder(self):
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Kubernetes", "desc": "multi-cluster operations"}],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))
        bullet = _find(paragraphs, "• Kubernetes: multi-cluster operations")

        runs = _runs(bullet)
        self.assertGreaterEqual(
            len(runs), 3, f"expected at least glyph/name/remainder runs, got {runs}"
        )
        self.assertEqual(runs[0], (GLYPH, None, None))
        self.assertEqual(runs[1], ("Kubernetes", True, None))

        # Everything after the name is plain, and reassembles the remainder.
        self.assertEqual(
            "".join(text for text, _, _ in runs[2:]), ": multi-cluster operations"
        )
        for text, bold, italic in runs[2:]:
            self.assertNotEqual(bold, True, f"run {text!r} must not be bold")
            self.assertNotEqual(italic, True, f"run {text!r} must not be italic")

    def test_item_without_desc_bolds_name_and_adds_no_separator(self):
        """A name-only item keeps its bold name and grows no dangling separator.

        The separator is emitted between two halves; with no second half there
        is nothing to separate, and a trailing ": " would be visible on the
        page.
        """
        groups = [{"title": "Languages", "items": [{"name": "Go"}]}]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))
        bullet = _find(paragraphs, "• Go")

        self.assertEqual(_runs(bullet), [(GLYPH, None, None), ("Go", True, None)])

    def test_name_containing_the_separator_is_bold_in_full(self):
        """The name/desc split comes from the data, not from string searching.

        A *name* that itself contains the separator is the case string
        splitting cannot get right: joining the halves and splitting the result
        on the first occurrence cuts inside the name, bolding only the fragment
        before it. The boundary is known exactly from the schema fields, so the
        whole name is bold however many separators it contains.
        """
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Ratio: p99", "desc": "latency objective"}],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))
        bullet = _find(paragraphs, "• Ratio: p99: latency objective")

        runs = _runs(bullet)
        self.assertEqual(runs[1], ("Ratio: p99", True, None))
        self.assertEqual(
            [text for text, bold, _ in runs if bold is True],
            ["Ratio: p99"],
            "the whole name is bold, not just the fragment before the separator",
        )

    def test_desc_containing_the_separator_keeps_it_in_the_description(self):
        """A separator inside the description stays plain."""
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Tracing", "desc": "spans: traces: baggage"}],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))
        bullet = _find(paragraphs, "• Tracing: spans: traces: baggage")

        runs = _runs(bullet)
        self.assertEqual(runs[1], ("Tracing", True, None))
        self.assertEqual(
            [text for text, bold, _ in runs if bold is True],
            ["Tracing"],
            "only the name may be bold",
        )

    def test_name_is_bold_when_config_supplies_no_separator(self):
        """The default-separator path bolds the name like the explicit one does.

        This is the configuration the previous implementation got wrong. It
        flattened name and description into one string using one default
        separator and then recovered the boundary by splitting that string on a
        *different* default, so with no explicit ``desc_separator`` the split
        never matched and the whole item rendered as a single plain run.
        """
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Kubernetes", "desc": "multi-cluster operations"}],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_DEFAULT_SEP))
        bullet = _find(
            paragraphs, f"{GLYPH}Kubernetes{DEFAULT_DESC_SEP}multi-cluster operations"
        )

        runs = _runs(bullet)
        self.assertEqual(runs[0], (GLYPH, None, None))
        self.assertEqual(runs[1], ("Kubernetes", True, None))
        self.assertEqual(
            [text for text, bold, _ in runs if bold is True], ["Kubernetes"]
        )
        self.assertEqual(
            "".join(text for text, _, _ in runs[2:]),
            f"{DEFAULT_DESC_SEP}multi-cluster operations",
        )

    def test_every_item_in_a_multi_group_resume_bolds_exactly_its_name(self):
        groups = [
            {
                "title": "Platform",
                "items": [
                    {"name": "Kubernetes", "desc": "multi-cluster operations"},
                    {"name": "Terraform", "desc": "module authoring"},
                ],
            },
            {
                "title": "Languages",
                "items": [
                    {"name": "Python", "desc": "primary language"},
                    {"name": "Go", "desc": "services and tooling"},
                ],
            },
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))

        for name, desc in (
            ("Kubernetes", "multi-cluster operations"),
            ("Terraform", "module authoring"),
            ("Python", "primary language"),
            ("Go", "services and tooling"),
        ):
            with self.subTest(item=name):
                bullet = _find(paragraphs, f"• {name}: {desc}")
                runs = _runs(bullet)
                self.assertEqual(runs[0], (GLYPH, None, None))
                self.assertEqual(runs[1], (name, True, None))
                self.assertEqual(
                    [text for text, bold, _ in runs if bold is True], [name]
                )


class SkillGroupTitleBoldTests(unittest.TestCase):
    """A skills-group title renders as a single bold, non-italic run."""

    def test_group_title_is_one_bold_run(self):
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Kubernetes", "desc": "multi-cluster operations"}],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_PLAIN_SKILLS))

        self.assertEqual(_runs(_find(paragraphs, "Platform")), [("Platform", True, None)])

    def test_every_group_title_is_bold(self):
        groups = [
            {"title": "Platform", "items": [{"name": "Kubernetes", "desc": "ops"}]},
            {"title": "Languages", "items": [{"name": "Python", "desc": "primary"}]},
            {"title": "Practices", "items": [{"name": "Testing", "desc": "unit"}]},
        ]
        paragraphs = _render(_resume(groups), _template(_PLAIN_SKILLS))

        for title in ("Platform", "Languages", "Practices"):
            with self.subTest(group=title):
                self.assertEqual(
                    _runs(_find(paragraphs, title)), [(title, True, None)]
                )

    def test_group_title_is_bold_in_the_bulleted_branch_too(self):
        """Both skills branches weight the title the same way.

        The bulleted and non-bulleted branches build the title through
        different code paths, so each needs its own assertion or one of them
        can silently lose the weighting.
        """
        groups = [
            {"title": "Platform", "items": [{"name": "Kubernetes", "desc": "ops"}]}
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))

        runs = _runs(_find(paragraphs, "Platform"))
        self.assertEqual([text for text, _, _ in runs], ["Platform"])
        self.assertTrue(runs[0][1], "group title must be bold")


class SkillsEmptyItemTests(unittest.TestCase):
    """Items that normalize to nothing stay skipped."""

    def test_item_normalizing_to_empty_renders_no_bare_glyph(self):
        """A blank item must not become a lone bullet glyph on an empty line."""
        groups = [
            {
                "title": "Platform",
                "items": [
                    {"name": "Kubernetes", "desc": "multi-cluster operations"},
                    {"name": "   ", "desc": "   "},
                ],
            }
        ]
        paragraphs = _render(_resume(groups), _template(_BULLETED_SKILLS))

        self.assertEqual(
            [p.text for p in paragraphs if p.text.strip() in (GLYPH.strip(), "")],
            [],
            "a blank skills item must not render a bare glyph",
        )


class SkillsBoldBlastRadiusTests(unittest.TestCase):
    """Nothing outside the skills section gained bold from this change."""

    def _paragraphs(self):
        groups = [
            {
                "title": "Platform",
                "items": [{"name": "Kubernetes", "desc": "multi-cluster operations"}],
            }
        ]
        return _render(_resume(groups), _template(_BULLETED_SKILLS))

    def test_summary_bullets_stay_entirely_plain(self):
        paragraphs = self._paragraphs()
        for text in (
            "• Runs imaginary systems at imaginary scale",
            "• Mentors an invented team of six",
        ):
            with self.subTest(summary=text):
                runs = _runs(_find(paragraphs, text))
                self.assertEqual(
                    [bold for _, bold, _ in runs],
                    [None] * len(runs),
                    "the summary section is out of scope and must stay plain",
                )

    def test_experience_bullet_stays_plain(self):
        runs = _runs(_find(self._paragraphs(), "• Did an invented thing"))
        self.assertEqual([bold for _, bold, _ in runs], [None] * len(runs))

    def test_experience_header_keeps_its_existing_weighting(self):
        """The header was already partly bold; that must be unchanged, not extended."""
        paragraphs = self._paragraphs()
        header = next(p for p in paragraphs if p.text.startswith("Staff Engineer at"))
        bold_runs = [text for text, bold, _ in _runs(header) if bold is True]
        self.assertEqual(bold_runs, ["Staff Engineer", "Nonexistent Systems"])

    def test_no_italics_are_introduced_in_the_skills_section(self):
        paragraphs = self._paragraphs()
        for text in ("Platform", "• Kubernetes: multi-cluster operations"):
            with self.subTest(paragraph=text):
                for run_text, _, italic in _runs(_find(paragraphs, text)):
                    self.assertNotEqual(
                        italic, True, f"run {run_text!r} must not be italic"
                    )


if __name__ == "__main__":
    unittest.main()
