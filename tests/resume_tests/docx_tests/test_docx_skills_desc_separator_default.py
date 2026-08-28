"""The ``desc_separator`` fallback is one value, shared by every path.

``show_desc`` and ``desc_separator`` are independent keys, so a template may
enable descriptions without naming a separator. When it does, every renderer
that prints a name/description pair must fall back to the same string.

WHAT WENT WRONG BEFORE
    Three call sites each read ``desc_separator`` with their own default.
    ``SkillsSectionRenderer._render_groups`` and ``_render_bullet_items`` used
    " -- ", while ``TechnologiesSectionRenderer._collect_tech_items`` used
    ": ". ``_render_bullet_items`` is shared by both renderers, so a
    technologies section with ``show_desc: true`` and no ``desc_separator``
    normalized its items with ": " -- which is what the non-bulleted joined
    form printed -- and then rendered them bulleted with " -- ". One config
    shape, two different rendered strings, decided by a branch the template
    author never sees.

    This is the same defect class PR #314 fixed on the skills path, where the
    two disagreeing defaults meant the name/desc split never matched and
    bolding could never fire.

WHY THESE COMPARE PATHS RATHER THAN PIN A LITERAL
    Asserting each path equals ": " would pass even if a later edit moved both
    to some third value in lockstep -- but it would also let the two drift
    apart again if only one assertion were updated. The load-bearing property
    is that the paths *agree*, so these render the same data through each path
    and compare the results to each other. One test pins the shared constant
    itself, so a silent change of the shipped separator still fails.

Every shipped template sets ``desc_separator: ": "`` explicitly, so nothing
here describes what shipped output looks like -- only what an under-specified
template gets.

No content from any real document appears here; every fixture value is
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

NAME = "Kubernetes"
DESC = "multi-cluster operations"

# Sections that enable descriptions but name no separator -- the shape whose
# fallback used to differ between paths. Keep these ``desc_separator``-free.
_TECH_BULLETED = {
    "key": "technologies",
    "title": "Technologies",
    "show_desc": True,
    "bullets": True,
}
_TECH_JOINED = {
    "key": "technologies",
    "title": "Technologies",
    "show_desc": True,
    "bullets": False,
}
_SKILLS_BULLETED = {
    "key": "skills",
    "title": "Skills",
    "show_desc": True,
    "bullets": True,
}


def _template(section: dict) -> dict:
    return {
        "page": {"compact": True, "body_pt": 10},
        "sections": [dict(section)],
    }


def _tech_resume() -> dict:
    return {
        "name": "Ada Placeholder",
        "technologies": [{"name": NAME, "desc": DESC}],
    }


def _skills_resume() -> dict:
    return {
        "name": "Ada Placeholder",
        "skills_groups": [
            {"title": "Platform", "items": [{"name": NAME, "desc": DESC}]}
        ],
    }


def _render(resume_data: dict, section: dict) -> list[str]:
    """Render through the public writer and return body paragraph texts."""
    import docx

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "resume.docx")
        write_resume_docx(Resume.from_dict(resume_data), _template(section), out)
        return [p.text for p in docx.Document(out).paragraphs]


def _separator_between(paragraphs: list[str]) -> str:
    """Extract whatever the renderer put between the name and the description.

    Reads the separator out of the rendered text rather than assuming a value,
    so a disagreement shows up as two different extracted strings instead of
    one assertion that happens to match.
    """
    for text in paragraphs:
        if NAME in text and DESC in text:
            body = text[text.index(NAME) + len(NAME) : text.index(DESC)]
            return body
    raise AssertionError(
        f"no paragraph carried both {NAME!r} and {DESC!r}: {paragraphs}"
    )


class DescSeparatorFallbackAgreementTests(unittest.TestCase):
    """Every path falls back to the same separator."""

    def test_technologies_bulleted_and_joined_forms_agree(self):
        """The two branches of the technologies renderer print one separator.

        These are the two sides of the reported disagreement: the bulleted
        branch went through ``_render_bullet_items`` while the joined branch
        printed ``LabeledItem.text``, and the two were built with different
        fallbacks.
        """
        bulleted = _separator_between(_render(_tech_resume(), _TECH_BULLETED))
        joined = _separator_between(_render(_tech_resume(), _TECH_JOINED))

        self.assertEqual(
            bulleted,
            joined,
            "bulleted and joined technologies output disagree on the "
            "desc_separator fallback",
        )

    def test_skills_and_technologies_bullets_agree(self):
        """Both renderers share ``_render_bullet_items``; both must agree."""
        skills = _separator_between(_render(_skills_resume(), _SKILLS_BULLETED))
        tech = _separator_between(_render(_tech_resume(), _TECH_BULLETED))

        self.assertEqual(
            skills,
            tech,
            "skills and technologies bullets disagree on the desc_separator "
            "fallback",
        )

    def test_fallback_matches_the_shared_constant(self):
        """The rendered fallback is the one constant, not a restated literal."""
        for label, resume_data, section in (
            ("technologies bulleted", _tech_resume(), _TECH_BULLETED),
            ("technologies joined", _tech_resume(), _TECH_JOINED),
            ("skills bulleted", _skills_resume(), _SKILLS_BULLETED),
        ):
            with self.subTest(path=label):
                self.assertEqual(
                    _separator_between(_render(resume_data, section)),
                    DEFAULT_DESC_SEPARATOR,
                )

    def test_shared_constant_is_the_value_shipped_templates_set(self):
        """Every shipped template writes ``desc_separator: ": "`` explicitly.

        Pinning it here means unifying the fallback cannot quietly change what
        those templates would render if the key were ever dropped from one.
        """
        self.assertEqual(DEFAULT_DESC_SEPARATOR, ": ")


class DescSeparatorExplicitConfigTests(unittest.TestCase):
    """An explicit ``desc_separator`` still wins on every path."""

    def test_explicit_separator_is_honoured_on_both_technologies_branches(self):
        explicit = " ~~ "
        bulleted = _separator_between(
            _render(_tech_resume(), {**_TECH_BULLETED, "desc_separator": explicit})
        )
        joined = _separator_between(
            _render(_tech_resume(), {**_TECH_JOINED, "desc_separator": explicit})
        )

        self.assertEqual(bulleted, explicit)
        self.assertEqual(joined, explicit)

    def test_explicit_separator_is_honoured_on_the_skills_bullet_path(self):
        explicit = " ~~ "
        rendered = _separator_between(
            _render(_skills_resume(), {**_SKILLS_BULLETED, "desc_separator": explicit})
        )

        self.assertEqual(rendered, explicit)


if __name__ == "__main__":
    unittest.main()
