"""Simple one-field list section renderers for DOCX resume output.

Provides renderers for sections that delegate directly to render_simple_list:
  - InterestsSectionRenderer, TeachingSectionRenderer, LanguagesSectionRenderer
  - CourseworkSectionRenderer, CertificationsSectionRenderer
  - PresentationsSectionRenderer
"""
from __future__ import annotations

from .docx_links import add_hyperlink, display_url, normalize_link_url
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
    def _format_presentation_dict(it: dict) -> tuple[str, str]:
        """Return (display_line, link_url) for a presentation dict.

        display_line is the plain text (title, event, year). link_url is the
        resolved URL from the `link` field, or empty string if absent.
        """
        title = str(it.get("title") or it.get("name") or "").strip()
        event = str(it.get("event") or "").strip()
        year = str(it.get("year") or "").strip()
        link = str(it.get("link") or "").strip()
        parts = [p for p in [title or event, event if title else "", year] if p]
        line = " — ".join(parts)
        url = normalize_link_url(link) if link else ""
        return line, url

    def _render_dict_item(self, it: dict, glyph: str) -> str | None:
        """Render a single dict presentation item; return display text or None."""
        line, url = self._format_presentation_dict(it)
        cleaned = self.text.clean_inline(line) if line else ""
        if not cleaned and not url:
            return None
        display = cleaned or url
        p = self.bullets.add_bullet_line(display, glyph=glyph)
        if url:
            p.add_run(" ")
            add_hyperlink(p, url, display_url(url))
        return display

    def _render_str_item(self, it: object, glyph: str) -> str | None:
        """Render a single string presentation item; return display text or None."""
        s = str(it).strip()
        if not s:
            return None
        cleaned = self.text.clean_inline(s)
        self.bullets.add_bullet_line(cleaned, glyph=glyph)
        return cleaned

    def render(self, data: dict, sec: dict | None = None) -> list[str]:
        items_raw = data.get("presentations") or []
        _, glyph = self.bullets.get_bullet_config(sec)
        lines: list[str] = []

        for it in items_raw:
            display = (
                self._render_dict_item(it, glyph)
                if isinstance(it, dict)
                else self._render_str_item(it, glyph)
            )
            if display:
                lines.append(display)

        return lines
