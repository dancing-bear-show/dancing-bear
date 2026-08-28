"""Simple one-field list section renderers for DOCX resume output.

Provides renderers for sections that delegate directly to render_simple_list:
  - InterestsSectionRenderer, TeachingSectionRenderer, LanguagesSectionRenderer
  - CourseworkSectionRenderer, CertificationsSectionRenderer
  - PresentationsSectionRenderer
"""
from __future__ import annotations

from .docx_links import add_hyperlink, display_url, normalize_link_url
from .docx_renderers import ListSectionRenderer
from .schema import Presentation, Resume


class InterestsSectionRenderer(ListSectionRenderer):
    """Renders interests section."""

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        return self.render_simple_list(resume.interests, sec)


class TeachingSectionRenderer(ListSectionRenderer):
    """Renders teaching/instruction section."""

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        # ``teaching`` is deliberately untyped (schema-design.md §1), so its
        # entries stay raw strings/dicts and take _extract_item_text's dict path.
        return self.render_simple_list(resume.teaching, sec)


class LanguagesSectionRenderer(ListSectionRenderer):
    """Renders languages section with proficiency levels."""

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        # NamedLevelItem resolves the "language" spelling onto `name` at
        # from_dict time; name_keys still declares which spellings this
        # section accepts. See ListSectionRenderer._item_name.
        return self.render_simple_list(
            resume.languages,
            sec,
            name_keys=("name", "language", "title", "label"),
            desc_key="level",
            desc_sep=" — ",
        )


class CourseworkSectionRenderer(ListSectionRenderer):
    """Renders coursework section."""

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        return self.render_simple_list(
            resume.coursework,
            sec,
            name_keys=("name", "course", "title", "label"),
            desc_key="desc",
            desc_sep=" — ",
        )


class CertificationsSectionRenderer(ListSectionRenderer):
    """Renders certifications section."""

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        # ``year`` is the desc field here and is an int in real data;
        # _extract_item_text stringifies it, as the dict path did.
        return self.render_simple_list(
            resume.certifications,
            sec,
            name_keys=("name", "title", "cert", "label"),
            desc_key="year",
            desc_sep=" — ",
        )


class PresentationsSectionRenderer(ListSectionRenderer):
    """Renders presentations/talks section."""

    @staticmethod
    def _format_presentation(pres: Presentation) -> tuple[str, str]:
        """Return (display_line, link_url) for a presentation entry.

        display_line is the plain text (title, event, year). link_url is the
        resolved URL from the `link` field, or empty string if absent.

        The old ``it.get("title") or it.get("name")`` fallback is gone because
        ``Presentation`` now aliases ``name`` onto ``title``, so the spelling
        is resolved once at ``from_dict`` time rather than at every read.
        """
        title = str(pres.title or "").strip()
        event = str(pres.event or "").strip()
        year = str(pres.year or "").strip()
        link = str(pres.link or "").strip()
        parts = [p for p in [title or event, event if title else "", year] if p]
        line = " — ".join(parts)
        url = normalize_link_url(link) if link else ""
        return line, url

    def _render_presentation(self, pres: Presentation, glyph: str, plain: bool = True) -> str | None:
        """Render a single presentation entry; return display text or None."""
        line, url = self._format_presentation(pres)
        cleaned = self.text.clean_inline(line) if line else ""
        if not cleaned and not url:
            return None
        if cleaned:
            # Normal case: render the title/event/year line, append link if present.
            p = self._make_bullet_paragraph(cleaned, glyph=glyph, plain=plain)
            if url:
                p.add_run(" ")
                add_hyperlink(p, url, display_url(url))
            return cleaned
        # Link-only: no title/event/year text — render a single hyperlink run
        # (cleaned display of URL) without duplicating the raw URL as plain text.
        link_display = display_url(url)
        p = self._make_bullet_paragraph("", glyph=glyph, plain=plain)
        add_hyperlink(p, url, link_display)
        return link_display

    def _make_bullet_paragraph(self, text: str, *, glyph: str, plain: bool):
        """Create and return a single bullet paragraph honoring the *plain* flag."""
        if plain:
            return self.bullets.add_bullet_line(text, glyph=glyph)
        # Non-plain: use Word list style so the presentation respects section config.
        p = self.bullets.doc.add_paragraph(style="List Bullet")
        self.bullets.styles.tight_paragraph(p, after_pt=0)
        self.bullets.styles.compact_bullet(p)
        if text:
            p.add_run(text)
        return p

    def render(self, resume: Resume, sec: dict | None = None) -> list[str]:
        """Render every presentation entry.

        The pre-migration split between a dict branch and a bare-string branch
        is gone: ``Resume.from_dict`` upgrades a bare string into a
        ``Presentation`` carrying it as ``title``, and that entry formats to
        the same single-part line the string branch produced.
        """
        plain, glyph = self.bullets.get_bullet_config(sec)
        lines: list[str] = []

        for pres in resume.presentations:
            display = self._render_presentation(pres, glyph, plain=plain)
            if display:
                lines.append(display)

        return lines
