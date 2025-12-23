"""DOCX resume writer.

Renders resume data to DOCX format using templates and styling configuration.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .io_utils import safe_import
from docx.shared import Pt, Inches, RGBColor  # type: ignore
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore

# Import from new abstraction modules
from .docx_styles import (
    _parse_hex_color,
    _is_dark,
    _tight_paragraph,
    _compact_bullet,
    _flush_left,
    _apply_paragraph_shading,
    _normalize_present,
    _format_phone_display,
    _format_link_display,
    _clean_inline_text,
    _normalize_bullet_text,
)
from .docx_sections import (
    BulletRenderer,
    HeaderRenderer,
    InterestsSectionRenderer,
    LanguagesSectionRenderer,
    CourseworkSectionRenderer,
    CertificationsSectionRenderer,
    PresentationsSectionRenderer,
    SummarySectionRenderer,
    SkillsSectionRenderer,
    TechnologiesSectionRenderer,
    ExperienceSectionRenderer,
    EducationSectionRenderer,
)


SECTION_SYNONYMS = {
    "summary": {"summary", "profile", "about"},
    "skills": {"skills", "technical skills"},
    "technologies": {"technologies", "technology", "tools"},
    "experience": {"experience", "work history", "employment"},
    "education": {"education", "academics"},
}


def _match_section_key(title: str) -> Optional[str]:
    t = title.strip().lower()
    for key, names in SECTION_SYNONYMS.items():
        if t in names:
            return key
    return None


# Backward-compatible function aliases that delegate to renderers
def _bold_keywords(paragraph, text: str, keywords: List[str]):
    """Bold keywords in paragraph text."""
    renderer = BulletRenderer.__new__(BulletRenderer)
    renderer._bold_keywords(paragraph, text, keywords)


def _add_bullet_line(doc, text: str, *, sec: Dict[str, Any] | None = None, keywords: List[str] | None = None, glyph: str = "•"):
    renderer = BulletRenderer(doc)
    return renderer.add_bullet_line(text, sec=sec, keywords=keywords, glyph=glyph)


def _add_plain_bullet(doc, text: str, keywords: List[str] | None = None):
    return _add_bullet_line(doc, text, keywords=keywords, glyph="•")


def _add_bullets(
    doc,
    items: List[str],
    *,
    sec: Dict[str, Any] | None = None,
    keywords: List[str] | None = None,
    plain: bool = True,
    glyph: str = "•",
    list_style: str = "List Bullet",
):
    renderer = BulletRenderer(doc)
    renderer.add_bullets(items, sec=sec, keywords=keywords, plain=plain, glyph=glyph, list_style=list_style)


def _render_group_title(doc, title: str, sec: Dict[str, Any] | None = None):
    renderer = HeaderRenderer(doc)
    return renderer.add_group_title(title, sec)


def _add_header_line(
    doc,
    *,
    title_text: str = "",
    company_text: str = "",
    loc_text: str = "",
    span_text: str = "",
    sec: Dict[str, Any] | None = None,
    style: str = "Normal",
):
    renderer = HeaderRenderer(doc)
    return renderer.add_header_line(
        title_text=title_text,
        company_text=company_text,
        loc_text=loc_text,
        span_text=span_text,
        sec=sec,
        style=style,
    )


def _add_named_bullet(
    doc,
    name_text: str,
    desc_text: str,
    *,
    sec: Dict[str, Any] | None = None,
    glyph: str = "•",
    sep: str = ": ",
):
    renderer = BulletRenderer(doc)
    return renderer.add_named_bullet(name_text, desc_text, sec=sec, glyph=glyph, sep=sep)


def _get_header_level(sec: Dict[str, Any] | None, page_cfg: Dict[str, Any] | None) -> int:
    try:
        if sec and isinstance(sec.get("header_level"), int):
            return int(sec.get("header_level"))
        if page_cfg and isinstance(page_cfg.get("header_level"), int):
            return int(page_cfg.get("header_level"))
    except Exception:
        pass  # nosec B110 - invalid header_level
    return 1


def _use_plain_bullets(sec: Dict[str, Any] | None, page_cfg: Dict[str, Any] | None) -> tuple:
    renderer = BulletRenderer.__new__(BulletRenderer)
    renderer.page_cfg = page_cfg or {}
    return renderer.get_bullet_config(sec)


def write_resume_docx(
    data: Dict[str, Any],
    template: Dict[str, Any],
    out_path: str,
    seed: Optional[Dict[str, Any]] = None,
    structure: Optional[Dict[str, Any]] = None,
) -> None:
    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Rendering DOCX requires python-docx; install python-docx.")

    from docx import Document  # type: ignore

    doc = Document()
    # Page compaction settings
    page_cfg = template.get("page") or {}
    if page_cfg.get("compact"):
        try:
            sec = doc.sections[0]
            m = float(page_cfg.get("margins_in", 0.5))
            sec.top_margin = Inches(m)
            sec.bottom_margin = Inches(m)
            sec.left_margin = Inches(m)
            sec.right_margin = Inches(m)
        except Exception:
            pass  # nosec B110 - margin setting failure
        try:
            body_pt = float(page_cfg.get("body_pt", 10.5))
            h1_pt = float(page_cfg.get("h1_pt", 12))
            title_pt = float(page_cfg.get("title_pt", 14))
            h1_color = page_cfg.get("h1_color") or page_cfg.get("heading_color")
            h1_bg = page_cfg.get("h1_bg") or page_cfg.get("heading_bg")
            title_color = page_cfg.get("title_color")
            normal = doc.styles["Normal"]
            normal.font.size = Pt(body_pt)
            if "Heading 1" in doc.styles:
                doc.styles["Heading 1"].font.size = Pt(h1_pt)
                doc.styles["Heading 1"].font.bold = True
                rgb = _parse_hex_color(h1_color)
                bg = _parse_hex_color(h1_bg)
                # If no explicit h1_color, auto-contrast against background
                if (not rgb) and bg:
                    rgb = (255, 255, 255) if _is_dark(bg) else (0, 0, 0)
                if rgb:
                    doc.styles["Heading 1"].font.color.rgb = RGBColor(*rgb)
            if "Title" in doc.styles:
                doc.styles["Title"].font.size = Pt(title_pt)
                # keep title bold for prominence
                doc.styles["Title"].font.bold = True
                rgbt = _parse_hex_color(title_color)
                if rgbt:
                    doc.styles["Title"].font.color.rgb = RGBColor(*rgbt)
        except Exception:
            pass  # nosec B110 - style setting failure
    # Core metadata
    name = data.get("name") or ""
    # Contact fields (accept top-level or under contact)
    contact = data.get("contact") or {}
    headline = data.get("headline") or contact.get("headline") or ""
    email = data.get("email") or contact.get("email") or ""
    phone = data.get("phone") or contact.get("phone") or ""
    display_phone = _format_phone_display(phone) if phone else ""
    location = data.get("location") or contact.get("location") or ""
    website = data.get("website") or contact.get("website") or ""
    linkedin = data.get("linkedin") or contact.get("linkedin") or ""
    github = data.get("github") or contact.get("github") or ""
    links_list = data.get("links") or contact.get("links") or []
    try:
        cp = doc.core_properties
        contact_line = " | ".join([p for p in [email, phone, location] if p])
        cp.title = " - ".join([p for p in [name, contact_line] if p]) or "Resume"
        cp.subject = "Resume"
        if name:
            cp.author = name
        # include phone/location in keywords for easy search
        kw = [k for k in [name, email, phone, location] if k]
        # Optionally include job locations in metadata keywords/category
        try:
            include_exp_locs = bool((template.get("page") or {}).get("metadata_include_locations", True))
        except Exception:
            include_exp_locs = True
        if include_exp_locs:
            locs = []
            for e in (data.get("experience") or []):
                loc_str = str(e.get("location") or "").strip()
                if loc_str:
                    locs.append(loc_str)
            # de-dup preserve order
            uniq_locs = list(dict.fromkeys(locs))
            kw.extend(uniq_locs)
            if uniq_locs:
                try:
                    cp.category = "; ".join(uniq_locs)
                except Exception:
                    pass  # nosec B110 - category set failure
        cp.keywords = "; ".join(kw)
    except Exception:
        pass  # nosec B110 - metadata set failure

    # Header
    if name:
        doc.add_heading(name, level=0)
        _tight_paragraph(doc.paragraphs[-1], after_pt=2)
        try:
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = doc.paragraphs[-1].paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
        except Exception:
            pass  # nosec B110 - alignment failure
    # Optional headline line directly under the name
    if headline:
        p_head = doc.add_paragraph(str(headline))
        _tight_paragraph(p_head, after_pt=2)
        try:
            p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = p_head.paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
        except Exception:
            pass  # nosec B110 - alignment failure
    # Build compact contact line with auto-included extras
    extras = []
    for val in [website, linkedin, github]:
        if isinstance(val, str) and val.strip():
            extras.append(_format_link_display(val))
    for val in (links_list if isinstance(links_list, list) else []):
        if isinstance(val, str) and val.strip():
            extras.append(_format_link_display(val))
    subtitle_parts = [p for p in [email, display_phone, location] if p]
    if extras:
        subtitle_parts.extend(extras)
    if subtitle_parts:
        p = doc.add_paragraph(" | ".join(subtitle_parts))
        _tight_paragraph(p, after_pt=6)
        try:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = p.paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
        except Exception:
            pass  # nosec B110 - alignment failure

    sections = template.get("sections") or []
    keywords = []
    if seed and isinstance(seed.get("keywords"), list):
        keywords = [str(k) for k in seed.get("keywords", [])]

    # Optionally replace order/titles from structure reference
    if structure and isinstance(structure.get("order"), list):
        # Map from key to title in structure; fall back to template
        order_keys: List[str] = structure.get("order", [])
        key_to_title: Dict[str, str] = structure.get("titles", {})
        # rebuild sections preserving configuration from template by key
        tpl_by_key = {s.get("key"): s for s in sections if s.get("key")}
        sections = [
            {**tpl_by_key.get(k, {"key": k, "title": key_to_title.get(k, k.title())})}
            for k in order_keys
            if k in tpl_by_key or key_to_title.get(k)
        ]

    for sec in sections:
        key = sec.get("key")
        title = sec.get("title") or (key.title() if isinstance(key, str) else "")
        if not key:
            continue
        if title:
            doc.add_heading(str(title), level=1)
            _tight_paragraph(doc.paragraphs[-1], before_pt=6, after_pt=2)
            _flush_left(doc.paragraphs[-1])
            # Optional shading for section headings
            try:
                page_h1_bg = (template.get("page") or {}).get("h1_bg") or (template.get("page") or {}).get("heading_bg")
            except Exception:
                page_h1_bg = None
            bg_rgb = _parse_hex_color(page_h1_bg)
            if bg_rgb:
                _apply_paragraph_shading(doc.paragraphs[-1], bg_rgb)

        if key == "summary":
            renderer = SummarySectionRenderer(doc, page_cfg)
            renderer.render(data, sec, keywords)
        elif key == "skills":
            renderer = SkillsSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "technologies":
            renderer = TechnologiesSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "interests":
            renderer = InterestsSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "presentations":
            renderer = PresentationsSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "languages":
            renderer = LanguagesSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "coursework":
            renderer = CourseworkSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "certifications":
            renderer = CertificationsSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        elif key == "experience":
            renderer = ExperienceSectionRenderer(doc, page_cfg)
            renderer.render(data, sec, keywords)
        elif key == "education":
            renderer = EducationSectionRenderer(doc, page_cfg)
            renderer.render(data, sec)
        else:
            # Unknown section: noop
            pass

    doc.save(out_path)
