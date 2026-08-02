"""Simple one-field list section renderers for DOCX resume output.

Provides renderers for sections that delegate directly to render_simple_list:
  - InterestsSectionRenderer, TeachingSectionRenderer, LanguagesSectionRenderer
  - CourseworkSectionRenderer, CertificationsSectionRenderer
  - PresentationsSectionRenderer
"""
from __future__ import annotations

from .docx_renderers import ListSectionRenderer


class InterestsSectionRenderer(ListSectionRenderer):
    """Renders interests section."""

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items = data.get("interests") or []
        return self.render_simple_list(items, sec)


class TeachingSectionRenderer(ListSectionRenderer):
    """Renders teaching/instruction section."""

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items = data.get("teaching") or []
        return self.render_simple_list(items, sec)


class LanguagesSectionRenderer(ListSectionRenderer):
    """Renders languages section with proficiency levels."""

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items = data.get("languages") or []
        return self.render_simple_list(
            items,
            sec,
            name_keys=("name", "language", "title"),
            desc_key="level",
            desc_sep=" — ",
        )


class CourseworkSectionRenderer(ListSectionRenderer):
    """Renders coursework section."""

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items = data.get("coursework") or []
        return self.render_simple_list(
            items,
            sec,
            name_keys=("name", "course", "title"),
            desc_key="desc",
            desc_sep=" — ",
        )


class CertificationsSectionRenderer(ListSectionRenderer):
    """Renders certifications section."""

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items = data.get("certifications") or []
        return self.render_simple_list(
            items,
            sec,
            name_keys=("name", "title", "cert"),
            desc_key="year",
            desc_sep=" — ",
        )


class PresentationsSectionRenderer(ListSectionRenderer):
    """Renders presentations/talks section."""

    @staticmethod
    def _format_presentation_dict(it: dict) -> str:
        """Format a presentation dict to a display line."""
        title = str(it.get("title") or it.get("name") or "").strip()
        event = str(it.get("event") or "").strip()
        year = str(it.get("year") or "").strip()
        link = str(it.get("link") or "").strip()
        parts = [p for p in [title or event, event if title else "", year] if p]
        line = " — ".join(parts)
        if link:
            line = f"{line} ({link})" if line else link
        return line

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items_raw = data.get("presentations") or []
        lines: list[str] = []

        for it in items_raw:
            if isinstance(it, dict):
                line = self._format_presentation_dict(it)
                if line:
                    lines.append(self.text.clean_inline(line))
            else:
                s = str(it).strip()
                if s:
                    lines.append(self.text.clean_inline(s))

        if lines:
            plain, glyph = self.bullets.get_bullet_config(sec)
            self.bullets.add_bullets(lines, plain=plain, glyph=glyph)

        return lines
