"""DOCX resume writer.

Renders resume data to DOCX format using templates and styling configuration.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .io_utils import safe_import
from docx.shared import Pt, Inches, RGBColor  # type: ignore
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
from docx.enum.table import WD_TABLE_ALIGNMENT  # type: ignore
from docx.oxml.ns import qn  # type: ignore
from docx.oxml import OxmlElement  # type: ignore

# Import from new abstraction modules
from .docx_styles import (
    _parse_hex_color,
    _is_dark,
    _tight_paragraph,
    _flush_left,
    _apply_paragraph_shading,
    _format_phone_display,
    _format_link_display,
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
    TeachingSectionRenderer,
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
    except Exception:  # noqa: S110 - invalid header_level
        pass
    return 1


def _use_plain_bullets(sec: Dict[str, Any] | None, page_cfg: Dict[str, Any] | None) -> tuple:
    renderer = BulletRenderer.__new__(BulletRenderer)
    renderer.page_cfg = page_cfg or {}
    return renderer.get_bullet_config(sec)


def _apply_page_styles(doc, page_cfg: Dict[str, Any]) -> None:
    """Apply compact page styles (margins and fonts)."""
    if not page_cfg.get("compact"):
        return

    try:
        sec = doc.sections[0]
        m = float(page_cfg.get("margins_in", 0.5))
        sec.top_margin = Inches(m)
        sec.bottom_margin = Inches(m)
        sec.left_margin = Inches(m)
        sec.right_margin = Inches(m)
    except Exception:  # noqa: S110 - margin setting failure
        pass

    try:
        body_pt = float(page_cfg.get("body_pt", 10.5))
        h1_pt = float(page_cfg.get("h1_pt", 12))
        title_pt = float(page_cfg.get("title_pt", 14))
        h1_color = page_cfg.get("h1_color") or page_cfg.get("heading_color")
        h1_bg = page_cfg.get("h1_bg") or page_cfg.get("heading_bg")
        title_color = page_cfg.get("title_color")

        doc.styles["Normal"].font.size = Pt(body_pt)

        if "Heading 1" in doc.styles:
            doc.styles["Heading 1"].font.size = Pt(h1_pt)
            doc.styles["Heading 1"].font.bold = True
            rgb = _parse_hex_color(h1_color)
            bg = _parse_hex_color(h1_bg)
            if (not rgb) and bg:
                rgb = (255, 255, 255) if _is_dark(bg) else (0, 0, 0)
            if rgb:
                doc.styles["Heading 1"].font.color.rgb = RGBColor(*rgb)

        if "Title" in doc.styles:
            doc.styles["Title"].font.size = Pt(title_pt)
            doc.styles["Title"].font.bold = True
            rgbt = _parse_hex_color(title_color)
            if rgbt:
                doc.styles["Title"].font.color.rgb = RGBColor(*rgbt)
    except Exception:  # noqa: S110 - style setting failure
        pass


def _extract_experience_locations(data: Dict[str, Any]) -> List[str]:
    """Extract unique location strings from experience entries."""
    locs = [str(e.get("location") or "").strip() for e in (data.get("experience") or [])]
    return list(dict.fromkeys([loc for loc in locs if loc]))


def _set_document_metadata(doc, data: Dict[str, Any], template: Dict[str, Any]) -> None:
    """Set document core properties (title, author, keywords)."""
    try:
        name = data.get("name") or ""
        contact = data.get("contact") or {}
        email = data.get("email") or contact.get("email") or ""
        phone = data.get("phone") or contact.get("phone") or ""
        location = data.get("location") or contact.get("location") or ""

        cp = doc.core_properties
        contact_line = " | ".join([p for p in [email, phone, location] if p])
        cp.title = " - ".join([p for p in [name, contact_line] if p]) or "Resume"
        cp.subject = "Resume"
        if name:
            cp.author = name

        kw = [k for k in [name, email, phone, location] if k]
        include_exp_locs = bool((template.get("page") or {}).get("metadata_include_locations", True))

        if include_exp_locs:
            uniq_locs = _extract_experience_locations(data)
            kw.extend(uniq_locs)
            if uniq_locs:
                try:
                    cp.category = "; ".join(uniq_locs)
                except Exception:  # noqa: S110 - category set failure
                    pass

        cp.keywords = "; ".join(kw)
    except Exception:  # noqa: S110 - metadata set failure
        pass


def _center_paragraph(para) -> None:
    """Center a paragraph and remove indents."""
    try:
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = para.paragraph_format
        pf.left_indent = Pt(0)
        pf.first_line_indent = Pt(0)
    except Exception:  # noqa: S110 - alignment failure
        pass


def _get_contact_field(data: Dict[str, Any], field: str) -> str:
    """Get a contact field from data or nested contact dict."""
    contact = data.get("contact") or {}
    return data.get(field) or contact.get(field) or ""


def _collect_link_extras(data: Dict[str, Any]) -> List[str]:
    """Collect formatted link extras (website, linkedin, github, links list)."""
    extras = []
    for field in ["website", "linkedin", "github"]:
        val = _get_contact_field(data, field)
        if val:
            extras.append(_format_link_display(val))
    links_list = _get_contact_field(data, "links") or []
    for val in (links_list if isinstance(links_list, list) else []):
        if isinstance(val, str) and val.strip():
            extras.append(_format_link_display(val))
    return extras


def _render_document_header(doc, data: Dict[str, Any]) -> None:
    """Render the name, headline, and contact line at the top of the resume."""
    name = _get_contact_field(data, "name")
    headline = _get_contact_field(data, "headline")
    email = _get_contact_field(data, "email")
    phone = _get_contact_field(data, "phone")
    display_phone = _format_phone_display(phone) if phone else ""
    location = _get_contact_field(data, "location")

    # Name heading
    if name:
        doc.add_heading(name, level=0)
        _tight_paragraph(doc.paragraphs[-1], after_pt=2)
        _center_paragraph(doc.paragraphs[-1])

    # Headline
    if headline:
        p_head = doc.add_paragraph(str(headline))
        _tight_paragraph(p_head, after_pt=2)
        _center_paragraph(p_head)

    # Contact line with links
    subtitle_parts = [p for p in [email, display_phone, location] if p]
    subtitle_parts.extend(_collect_link_extras(data))

    if subtitle_parts:
        p = doc.add_paragraph(" | ".join(subtitle_parts))
        _tight_paragraph(p, after_pt=6)
        _center_paragraph(p)


def _resolve_sections(template: Dict[str, Any], structure: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resolve section order and configuration from template/structure."""
    sections = template.get("sections") or []

    if structure and isinstance(structure.get("order"), list):
        order_keys: List[str] = structure.get("order", [])
        key_to_title: Dict[str, str] = structure.get("titles", {})
        tpl_by_key = {s.get("key"): s for s in sections if s.get("key")}
        sections = [
            {**tpl_by_key.get(k, {"key": k, "title": key_to_title.get(k, k.title())})}
            for k in order_keys
            if k in tpl_by_key or key_to_title.get(k)
        ]

    return sections


def _render_section_heading(doc, title: str, template: Dict[str, Any]) -> None:
    """Render a section heading with optional shading."""
    if not title:
        return
    doc.add_heading(str(title), level=1)
    _tight_paragraph(doc.paragraphs[-1], before_pt=6, after_pt=2)
    _flush_left(doc.paragraphs[-1])
    page_h1_bg = (template.get("page") or {}).get("h1_bg") or (template.get("page") or {}).get("heading_bg")
    bg_rgb = _parse_hex_color(page_h1_bg)
    if bg_rgb:
        _apply_paragraph_shading(doc.paragraphs[-1], bg_rgb)


# Sidebar layout constants
SIDEBAR_SECTIONS = {"summary", "skills", "contact"}
MAIN_SECTIONS = {"education", "experience", "teaching", "presentations", "certifications", "languages"}


def _set_cell_shading(cell, hex_color: str) -> None:
    """Set background shading on a table cell."""
    rgb = _parse_hex_color(hex_color)
    if not rgb:
        return
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), hex_color.lstrip('#'))
    tcPr.append(shd)


def _remove_cell_borders(cell) -> None:
    """Remove all borders from a table cell."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'nil')
        tcBorders.append(border)
    tcPr.append(tcBorders)


def _render_sidebar_header(cell, data: Dict[str, Any], page_cfg: Dict[str, Any]) -> None:
    """Render name and headline in sidebar cell."""
    name = _get_contact_field(data, "name")
    headline = _get_contact_field(data, "headline")

    name_color = page_cfg.get("sidebar_name_color", "#333333")
    text_color = page_cfg.get("sidebar_text_color", "#333333")

    # Name - large
    if name:
        p = cell.add_paragraph()
        run = p.add_run(name)
        run.bold = True
        run.font.size = Pt(page_cfg.get("sidebar_name_pt", 24))
        rgb = _parse_hex_color(name_color)
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        _tight_paragraph(p, after_pt=2)

    # Headline
    if headline:
        p = cell.add_paragraph()
        run = p.add_run(headline)
        run.font.size = Pt(page_cfg.get("sidebar_headline_pt", 11))
        rgb = _parse_hex_color(text_color)
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        _tight_paragraph(p, after_pt=12)


def _render_sidebar_contact(cell, data: Dict[str, Any], page_cfg: Dict[str, Any], title: str = "Contacto") -> None:
    """Render contact section in sidebar."""
    email = _get_contact_field(data, "email")
    phone = _get_contact_field(data, "phone")
    location = _get_contact_field(data, "location")

    h1_color = page_cfg.get("h1_color", "#D4A84B")
    text_color = page_cfg.get("sidebar_text_color", "#333333")

    # Section title
    p = cell.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(page_cfg.get("h1_pt", 14))
    rgb = _parse_hex_color(h1_color)
    if rgb:
        run.font.color.rgb = RGBColor(*rgb)
    _tight_paragraph(p, before_pt=12, after_pt=6)

    # Contact items
    for item in [phone, email, location]:
        if item:
            p = cell.add_paragraph()
            run = p.add_run(item)
            run.font.size = Pt(page_cfg.get("body_pt", 10))
            rgb = _parse_hex_color(text_color)
            if rgb:
                run.font.color.rgb = RGBColor(*rgb)
            _tight_paragraph(p, after_pt=2)


def _render_sidebar_section(cell, title: str, items: List[str], page_cfg: Dict[str, Any], bulleted: bool = True) -> None:
    """Render a generic section in sidebar with optional bullets."""
    h1_color = page_cfg.get("h1_color", "#D4A84B")
    text_color = page_cfg.get("sidebar_text_color", "#333333")
    bullet_color = page_cfg.get("sidebar_bullet_color", "#4A90A4")

    # Section title
    p = cell.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(page_cfg.get("h1_pt", 14))
    rgb = _parse_hex_color(h1_color)
    if rgb:
        run.font.color.rgb = RGBColor(*rgb)
    _tight_paragraph(p, before_pt=12, after_pt=6)

    # Items
    for item in items:
        p = cell.add_paragraph()
        if bulleted:
            bullet_run = p.add_run("• ")
            bullet_rgb = _parse_hex_color(bullet_color)
            if bullet_rgb:
                bullet_run.font.color.rgb = RGBColor(*bullet_rgb)
            bullet_run.font.size = Pt(page_cfg.get("body_pt", 10))
        run = p.add_run(item)
        run.font.size = Pt(page_cfg.get("body_pt", 10))
        rgb = _parse_hex_color(text_color)
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        _tight_paragraph(p, after_pt=2)


def _render_main_section_heading(cell, title: str, page_cfg: Dict[str, Any]) -> None:
    """Render a section heading in main column."""
    h1_color = page_cfg.get("h1_color", "#D4A84B")

    p = cell.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(page_cfg.get("h1_pt", 14))
    rgb = _parse_hex_color(h1_color)
    if rgb:
        run.font.color.rgb = RGBColor(*rgb)
    _tight_paragraph(p, before_pt=10, after_pt=6)


def _render_main_education(cell, data: Dict[str, Any], page_cfg: Dict[str, Any], sec: Dict[str, Any]) -> None:
    """Render education in main column."""
    education = data.get("education") or []
    bullet_color = page_cfg.get("main_bullet_color", "#4A90A4")

    for edu in education:
        degree = edu.get("degree", "")
        institution = edu.get("institution", "")
        year = edu.get("year", "")

        # Bullet + degree
        p = cell.add_paragraph()
        bullet_run = p.add_run("• ")
        bullet_rgb = _parse_hex_color(bullet_color)
        if bullet_rgb:
            bullet_run.font.color.rgb = RGBColor(*bullet_rgb)

        deg_run = p.add_run(degree)
        deg_run.bold = True
        deg_run.font.size = Pt(page_cfg.get("body_pt", 10))
        _tight_paragraph(p, after_pt=0)

        # Institution + year on same line
        if institution or year:
            p2 = cell.add_paragraph()
            p2.paragraph_format.left_indent = Inches(0.25)
            inst_run = p2.add_run(institution)
            inst_run.italic = True
            inst_run.font.size = Pt(page_cfg.get("meta_pt", 9))
            inst_rgb = _parse_hex_color("#666666")
            if inst_rgb:
                inst_run.font.color.rgb = RGBColor(*inst_rgb)
            if year:
                year_run = p2.add_run(f"  {year}")
                year_run.font.size = Pt(page_cfg.get("meta_pt", 9))
                if inst_rgb:
                    year_run.font.color.rgb = RGBColor(*inst_rgb)
            _tight_paragraph(p2, after_pt=6)


def _render_main_experience(cell, data: Dict[str, Any], page_cfg: Dict[str, Any], sec: Dict[str, Any]) -> None:
    """Render experience in main column."""
    experience = data.get("experience") or []
    bullet_color = page_cfg.get("main_bullet_color", "#4A90A4")

    for exp in experience:
        title = exp.get("title", "")
        company = exp.get("company", "")
        start = exp.get("start", "")
        end = exp.get("end", "")
        span = f"{start} – {end}" if end else f"{start} – presente"
        bullets = exp.get("bullets") or []

        # Bullet + title
        p = cell.add_paragraph()
        bullet_run = p.add_run("• ")
        bullet_rgb = _parse_hex_color(bullet_color)
        if bullet_rgb:
            bullet_run.font.color.rgb = RGBColor(*bullet_rgb)

        title_run = p.add_run(title)
        title_run.bold = True
        title_run.font.size = Pt(page_cfg.get("body_pt", 10))

        # Year on right
        if span:
            span_run = p.add_run(f"  {span}")
            span_run.font.size = Pt(page_cfg.get("meta_pt", 9))
            span_rgb = _parse_hex_color("#666666")
            if span_rgb:
                span_run.font.color.rgb = RGBColor(*span_rgb)
        _tight_paragraph(p, after_pt=0)

        # Company
        if company:
            p2 = cell.add_paragraph()
            p2.paragraph_format.left_indent = Inches(0.25)
            comp_run = p2.add_run(company)
            comp_run.italic = True
            comp_run.font.size = Pt(page_cfg.get("meta_pt", 9))
            comp_rgb = _parse_hex_color("#666666")
            if comp_rgb:
                comp_run.font.color.rgb = RGBColor(*comp_rgb)
            _tight_paragraph(p2, after_pt=2)

        # Bullets
        for b in bullets[:sec.get("recent_max_bullets", 3)]:
            text = b.get("text", b) if isinstance(b, dict) else b
            p3 = cell.add_paragraph()
            p3.paragraph_format.left_indent = Inches(0.25)
            run = p3.add_run(text)
            run.font.size = Pt(page_cfg.get("body_pt", 10) - 1)
            _tight_paragraph(p3, after_pt=1)


def _render_main_teaching(cell, data: Dict[str, Any], page_cfg: Dict[str, Any], sec: Dict[str, Any]) -> None:
    """Render teaching in main column (uppercase titles with institution below)."""
    teaching = data.get("teaching") or []

    for item in teaching:
        text = item.get("text", item) if isinstance(item, dict) else item
        # Split on parentheses to get title and institution
        if "(" in text and text.endswith(")"):
            parts = text.rsplit("(", 1)
            title = parts[0].strip()
            institution = parts[1].rstrip(")")
        else:
            title = text
            institution = ""

        # Title (uppercase)
        p = cell.add_paragraph()
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(page_cfg.get("body_pt", 10))
        _tight_paragraph(p, after_pt=0)

        # Institution
        if institution:
            p2 = cell.add_paragraph()
            run2 = p2.add_run(institution)
            run2.italic = True
            run2.font.size = Pt(page_cfg.get("meta_pt", 9))
            inst_rgb = _parse_hex_color("#666666")
            if inst_rgb:
                run2.font.color.rgb = RGBColor(*inst_rgb)
            _tight_paragraph(p2, after_pt=6)


def _render_main_presentations(cell, data: Dict[str, Any], page_cfg: Dict[str, Any], sec: Dict[str, Any]) -> None:
    """Render presentations/publications in main column."""
    presentations = data.get("presentations") or []
    bullet_color = page_cfg.get("main_bullet_color", "#4A90A4")

    for pres in presentations:
        title = pres.get("title", "")
        authors = pres.get("authors", "")
        event = pres.get("event", "")
        note = pres.get("note", "")

        # Bullet + title
        p = cell.add_paragraph()
        bullet_run = p.add_run("• ")
        bullet_rgb = _parse_hex_color(bullet_color)
        if bullet_rgb:
            bullet_run.font.color.rgb = RGBColor(*bullet_rgb)

        title_run = p.add_run(title)
        title_run.bold = True
        title_run.font.size = Pt(page_cfg.get("body_pt", 10))
        _tight_paragraph(p, after_pt=0)

        # Authors
        if authors:
            p2 = cell.add_paragraph()
            p2.paragraph_format.left_indent = Inches(0.25)
            auth_run = p2.add_run(authors)
            auth_run.italic = True
            auth_run.font.size = Pt(page_cfg.get("meta_pt", 9))
            auth_rgb = _parse_hex_color("#666666")
            if auth_rgb:
                auth_run.font.color.rgb = RGBColor(*auth_rgb)
            _tight_paragraph(p2, after_pt=0)

        # Event
        if event:
            p3 = cell.add_paragraph()
            p3.paragraph_format.left_indent = Inches(0.25)
            ev_run = p3.add_run(event)
            ev_run.font.size = Pt(page_cfg.get("meta_pt", 9) - 1)
            ev_rgb = _parse_hex_color("#888888")
            if ev_rgb:
                ev_run.font.color.rgb = RGBColor(*ev_rgb)
            _tight_paragraph(p3, after_pt=0)

        # Note (award)
        if note:
            p4 = cell.add_paragraph()
            p4.paragraph_format.left_indent = Inches(0.25)
            note_run = p4.add_run(note)
            note_run.italic = True
            note_run.font.size = Pt(page_cfg.get("meta_pt", 9) - 1)
            _tight_paragraph(p4, after_pt=4)
        else:
            # Add spacing after last element
            if event:
                p3.paragraph_format.space_after = Pt(4)
            elif authors:
                p2.paragraph_format.space_after = Pt(4)


def _render_page_header_sidebar(doc, data: Dict[str, Any], page_cfg: Dict[str, Any], layout_cfg: Dict[str, Any]) -> None:
    """Add name, headline, and contact as left-aligned sidebar in page header (repeats on each page)."""
    section = doc.sections[0]
    header = section.header

    name = _get_contact_field(data, "name")
    headline = _get_contact_field(data, "headline")
    email = _get_contact_field(data, "email")
    phone = _get_contact_field(data, "phone")
    location = _get_contact_field(data, "location")

    name_color = page_cfg.get("sidebar_name_color", "#2C5282")
    text_color = page_cfg.get("sidebar_text_color", "#333333")

    # Clear and use first paragraph for name
    if header.paragraphs:
        p = header.paragraphs[0]
        p.clear()
    else:
        p = header.add_paragraph()

    # Name (in first paragraph)
    if name:
        run = p.add_run(name)
        run.bold = True
        run.font.size = Pt(page_cfg.get("sidebar_name_pt", 24))
        rgb = _parse_hex_color(name_color)
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        _tight_paragraph(p, after_pt=0)
        _flush_left(p)

    # Headline
    if headline:
        p2 = header.add_paragraph()
        run = p2.add_run(headline)
        run.font.size = Pt(page_cfg.get("sidebar_headline_pt", 11))
        rgb = _parse_hex_color(text_color)
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        _tight_paragraph(p2, after_pt=4)
        _flush_left(p2)

    # Contact items (stacked, left-aligned)
    for item in [phone, email, location]:
        if item:
            p3 = header.add_paragraph()
            run = p3.add_run(item)
            run.font.size = Pt(page_cfg.get("body_pt", 10) - 1)
            rgb = _parse_hex_color("#666666")
            if rgb:
                run.font.color.rgb = RGBColor(*rgb)
            _tight_paragraph(p3, after_pt=1)
            _flush_left(p3)


def write_resume_docx_sidebar(
    data: Dict[str, Any],
    template: Dict[str, Any],
    out_path: str,
    seed: Optional[Dict[str, Any]] = None,
    structure: Optional[Dict[str, Any]] = None,
) -> None:
    """Write resume with two-column sidebar layout."""
    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Rendering DOCX requires python-docx; install python-docx.")

    from docx import Document  # type: ignore

    doc = Document()
    page_cfg = template.get("page") or {}
    layout_cfg = template.get("layout") or {}

    # Apply page styles and metadata
    _apply_page_styles(doc, page_cfg)
    _set_document_metadata(doc, data, template)

    # Layout dimensions
    sidebar_width = layout_cfg.get("sidebar_width", 2.3)
    main_width = layout_cfg.get("main_width", 5.2)
    sidebar_bg = layout_cfg.get("sidebar_bg")

    # Contact title
    contact_title = "Contacto"
    for sec in (template.get("sections") or []):
        if sec.get("key") == "contact":
            contact_title = sec.get("title", "Contacto")
            break

    # Put sidebar content in page header (repeats on all pages)
    section = doc.sections[0]
    header = section.header

    name = _get_contact_field(data, "name")
    headline = _get_contact_field(data, "headline")
    email = _get_contact_field(data, "email")
    phone = _get_contact_field(data, "phone")
    location = _get_contact_field(data, "location")

    name_color = page_cfg.get("sidebar_name_color", "#1A365D")
    text_color = page_cfg.get("sidebar_text_color", "#333333")

    header_bg = page_cfg.get("header_bg", "#F7F9FC")

    # Name in header (centered)
    if header.paragraphs:
        p = header.paragraphs[0]
        p.clear()
    else:
        p = header.add_paragraph()
    run = p.add_run(name)
    run.bold = True
    run.font.size = Pt(page_cfg.get("sidebar_name_pt", 20))
    rgb = _parse_hex_color(name_color)
    if rgb:
        run.font.color.rgb = RGBColor(*rgb)
    _tight_paragraph(p, after_pt=0)
    _center_paragraph(p)
    bg_rgb = _parse_hex_color(header_bg)
    if bg_rgb:
        _apply_paragraph_shading(p, bg_rgb)

    # Headline (centered)
    if headline:
        p2 = header.add_paragraph()
        run2 = p2.add_run(headline)
        run2.font.size = Pt(page_cfg.get("sidebar_headline_pt", 10))
        rgb2 = _parse_hex_color(text_color)
        if rgb2:
            run2.font.color.rgb = RGBColor(*rgb2)
        _tight_paragraph(p2, after_pt=2)
        _center_paragraph(p2)
        if bg_rgb:
            _apply_paragraph_shading(p2, bg_rgb)

    # Contact line (centered)
    contact_parts = [x for x in [phone, email, location] if x]
    if contact_parts:
        p3 = header.add_paragraph()
        run3 = p3.add_run(" | ".join(contact_parts))
        run3.font.size = Pt(page_cfg.get("body_pt", 10) - 1)
        rgb3 = _parse_hex_color("#666666")
        if rgb3:
            run3.font.color.rgb = RGBColor(*rgb3)
        _tight_paragraph(p3, after_pt=6)
        _center_paragraph(p3)
        if bg_rgb:
            _apply_paragraph_shading(p3, bg_rgb)

    # Create two-column table for body (sidebar col empty, aligns with header)
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    table.columns[0].width = Inches(sidebar_width)
    table.columns[1].width = Inches(main_width)

    sidebar_cell = table.rows[0].cells[0]
    main_cell = table.rows[0].cells[1]

    _remove_cell_borders(sidebar_cell)
    _remove_cell_borders(main_cell)

    if sidebar_bg:
        _set_cell_shading(sidebar_cell, sidebar_bg)

    # Clear default paragraphs
    if sidebar_cell.paragraphs:
        sidebar_cell.paragraphs[0].clear()
    if main_cell.paragraphs:
        main_cell.paragraphs[0].clear()

    # Page 1 sidebar: Profile + Skills (header already has name/contact)
    for sec in (template.get("sections") or []):
        if sec.get("key") == "summary":
            summary_items = data.get("summary") or []
            if isinstance(summary_items, str):
                summary_items = [summary_items]
            elif isinstance(summary_items, list):
                summary_items = [s.get("text", s) if isinstance(s, dict) else s for s in summary_items]
            if summary_items:
                _render_sidebar_section(
                    sidebar_cell,
                    sec.get("title", "Perfil profesional"),
                    summary_items[:6],
                    page_cfg,
                    bulleted=True
                )
            break

    for sec in (template.get("sections") or []):
        if sec.get("key") == "skills":
            skills_groups = data.get("skills_groups") or []
            skill_items = []
            for group in skills_groups:
                for item in (group.get("items") or []):
                    name = item.get("name", item) if isinstance(item, dict) else item
                    skill_items.append(name)
            if skill_items:
                _render_sidebar_section(sidebar_cell, sec.get("title", "Habilidades claves"), skill_items[:8], page_cfg)
            break

    # === MAIN CONTENT (natural flow) ===
    sections = template.get("sections") or []

    for sec in sections:
        key = sec.get("key")
        title = sec.get("title", "")

        if key == "education":
            _render_main_section_heading(main_cell, title, page_cfg)
            _render_main_education(main_cell, data, page_cfg, sec)
        elif key == "experience":
            _render_main_section_heading(main_cell, title, page_cfg)
            _render_main_experience(main_cell, data, page_cfg, sec)
        elif key == "teaching":
            _render_main_section_heading(main_cell, title, page_cfg)
            _render_main_teaching(main_cell, data, page_cfg, sec)
        elif key == "presentations":
            _render_main_section_heading(main_cell, title, page_cfg)
            _render_main_presentations(main_cell, data, page_cfg, sec)

    doc.save(out_path)


# Section renderer registry - maps section keys to renderer classes
SECTION_RENDERERS = {
    "summary": SummarySectionRenderer,
    "skills": SkillsSectionRenderer,
    "technologies": TechnologiesSectionRenderer,
    "interests": InterestsSectionRenderer,
    "presentations": PresentationsSectionRenderer,
    "languages": LanguagesSectionRenderer,
    "coursework": CourseworkSectionRenderer,
    "certifications": CertificationsSectionRenderer,
    "experience": ExperienceSectionRenderer,
    "education": EducationSectionRenderer,
    "teaching": TeachingSectionRenderer,
}

# Sections that need keywords passed to render()
SECTIONS_WITH_KEYWORDS = {"summary", "experience"}


def write_resume_docx(
    data: Dict[str, Any],
    template: Dict[str, Any],
    out_path: str,
    seed: Optional[Dict[str, Any]] = None,
    structure: Optional[Dict[str, Any]] = None,
) -> None:
    # Check for sidebar layout
    layout_cfg = template.get("layout") or {}
    if layout_cfg.get("type") == "sidebar":
        return write_resume_docx_sidebar(data, template, out_path, seed, structure)

    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Rendering DOCX requires python-docx; install python-docx.")

    from docx import Document  # type: ignore

    doc = Document()
    page_cfg = template.get("page") or {}

    # Apply page styles, metadata, and header
    _apply_page_styles(doc, page_cfg)
    _set_document_metadata(doc, data, template)
    _render_document_header(doc, data)

    # Extract keywords from seed
    keywords = []
    if seed and isinstance(seed.get("keywords"), list):
        keywords = [str(k) for k in seed.get("keywords", [])]

    # Resolve and render sections
    sections = _resolve_sections(template, structure)

    for sec in sections:
        key = sec.get("key")
        if not key:
            continue
        title = sec.get("title") or (key.title() if isinstance(key, str) else "")
        _render_section_heading(doc, title, template)

        renderer_class = SECTION_RENDERERS.get(key)
        if renderer_class:
            renderer = renderer_class(doc, page_cfg)
            if key in SECTIONS_WITH_KEYWORDS:
                renderer.render(data, sec, keywords)
            else:
                renderer.render(data, sec)

    doc.save(out_path)
