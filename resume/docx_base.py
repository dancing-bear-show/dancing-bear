"""Base class for DOCX resume writers.

Provides common functionality for resume rendering.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from docx.shared import Pt, Inches, RGBColor  # type: ignore

from .io_utils import safe_import
from .docx_styles import (
    StyleManager,
    TextFormatter,
    _parse_hex_color,
    _is_dark,
    _format_link_display,
)


STYLE_HEADING_1 = "Heading 1"


def _apply_h1_color(doc, h1_color, h1_bg) -> None:
    """Apply color to Heading 1 style, auto-contrasting if needed."""
    rgb = _parse_hex_color(h1_color)
    bg = _parse_hex_color(h1_bg)
    if (not rgb) and bg:
        rgb = (255, 255, 255) if _is_dark(bg) else (0, 0, 0)
    if rgb:
        doc.styles[STYLE_HEADING_1].font.color.rgb = RGBColor(*rgb)


def _apply_font_styles(doc, page_cfg: Dict[str, Any]) -> None:
    """Apply font sizes and colors to Normal, Heading 1, and Title styles."""
    body_pt = float(page_cfg.get("body_pt", 10.5))
    h1_pt = float(page_cfg.get("h1_pt", 12))
    title_pt = float(page_cfg.get("title_pt", 14))
    h1_color = page_cfg.get("h1_color") or page_cfg.get("heading_color")
    h1_bg = page_cfg.get("h1_bg") or page_cfg.get("heading_bg")
    title_color = page_cfg.get("title_color")

    doc.styles["Normal"].font.size = Pt(body_pt)

    if STYLE_HEADING_1 in doc.styles:
        doc.styles[STYLE_HEADING_1].font.size = Pt(h1_pt)
        doc.styles[STYLE_HEADING_1].font.bold = True
        _apply_h1_color(doc, h1_color, h1_bg)

    if "Title" in doc.styles:
        doc.styles["Title"].font.size = Pt(title_pt)
        doc.styles["Title"].font.bold = True
        rgbt = _parse_hex_color(title_color)
        if rgbt:
            doc.styles["Title"].font.color.rgb = RGBColor(*rgbt)


def apply_page_styles_to_doc(doc, page_cfg: Dict[str, Any]) -> None:
    """Apply compact page styles (margins and fonts) to a document object.

    Shared implementation used by both ResumeWriterBase and legacy module helpers.
    """
    if not page_cfg.get("compact"):
        return

    try:
        sec = doc.sections[0]
        m = float(page_cfg.get("margins_in", 0.5))
        sec.top_margin = Inches(m)
        sec.bottom_margin = Inches(m)
        sec.left_margin = Inches(m)
        sec.right_margin = Inches(m)
    except Exception:  # nosec B110 - non-critical margin setting failure
        pass

    try:
        _apply_font_styles(doc, page_cfg)
    except Exception:  # nosec B110 - non-critical font/style setting failure
        pass


def _extract_locations(data: Dict[str, Any]) -> List[str]:
    """Extract unique non-empty location strings from experience entries."""
    locs = [str(e.get("location") or "").strip() for e in (data.get("experience") or [])]
    return list(dict.fromkeys([loc for loc in locs if loc]))


def _set_category(cp, locs: List[str]) -> None:
    """Set category on core properties, silently ignoring failures."""
    try:
        cp.category = "; ".join(locs)
    except Exception:  # nosec B110 - non-critical category metadata setting
        pass


def set_document_metadata_on_doc(
    doc, data: Dict[str, Any], page_cfg: Dict[str, Any]
) -> None:
    """Set document core properties (title, author, keywords).

    Shared implementation used by both ResumeWriterBase and legacy module helpers.
    """
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
        if bool(page_cfg.get("metadata_include_locations", True)):
            uniq_locs = _extract_locations(data)
            kw.extend(uniq_locs)
            if uniq_locs:
                _set_category(cp, uniq_locs)

        cp.keywords = "; ".join(kw)
    except Exception:  # nosec B110 - non-critical metadata setting failure
        pass


class ResumeWriterBase(ABC):
    """Base class for DOCX resume writers."""

    def __init__(self, data: Dict[str, Any], template: Dict[str, Any]):
        """Initialize writer with resume data and template config.

        Args:
            data: Resume data (name, experience, education, etc.)
            template: Template configuration (sections, page styles, etc.)
        """
        self.data = data
        self.template = template
        self.page_cfg = template.get("page") or {}
        self.layout_cfg = template.get("layout") or {}
        self.doc = None
        self.styles = StyleManager()
        self.text = TextFormatter()

    def write(self, out_path: str, seed: Optional[Dict[str, Any]] = None) -> None:
        """Write resume to DOCX file.

        Args:
            out_path: Output file path
            seed: Optional seed data (keywords, etc.)
        """
        docx = safe_import("docx")
        if not docx:
            raise RuntimeError("Rendering DOCX requires python-docx; install python-docx.")

        from docx import Document  # type: ignore
        self.doc = Document()

        self._apply_page_styles()
        self._set_document_metadata()
        self._render_content(seed)
        self.doc.save(out_path)

    @abstractmethod
    def _render_content(self, seed: Optional[Dict[str, Any]] = None) -> None:
        """Render the main document content. Subclasses must implement."""
        pass

    # -------------------------------------------------------------------------
    # Page setup and metadata
    # -------------------------------------------------------------------------

    def _apply_page_styles(self) -> None:
        """Apply compact page styles (margins and fonts)."""
        apply_page_styles_to_doc(self.doc, self.page_cfg)

    def _set_document_metadata(self) -> None:
        """Set document core properties (title, author, keywords)."""
        set_document_metadata_on_doc(self.doc, self.data, self.page_cfg)

    def _extract_experience_locations(self) -> List[str]:
        """Extract unique location strings from experience entries."""
        locs = [str(e.get("location") or "").strip() for e in (self.data.get("experience") or [])]
        return list(dict.fromkeys([loc for loc in locs if loc]))

    # -------------------------------------------------------------------------
    # Contact field helpers
    # -------------------------------------------------------------------------

    def _get_contact_field(self, field: str) -> str:
        """Get a contact field from data or nested contact dict."""
        contact = self.data.get("contact") or {}
        return self.data.get(field) or contact.get(field) or ""

    def _collect_link_extras(self) -> List[str]:
        """Collect formatted link extras (website, linkedin, github, links list)."""
        extras = []
        for field in ["website", "linkedin", "github"]:
            val = self._get_contact_field(field)
            if val:
                extras.append(_format_link_display(val))
        links_list = self._get_contact_field("links") or []
        for val in (links_list if isinstance(links_list, list) else []):
            if isinstance(val, str) and val.strip():
                extras.append(_format_link_display(val))
        return extras

    # -------------------------------------------------------------------------
    # Paragraph helpers
    # -------------------------------------------------------------------------

    def _center_paragraph(self, para) -> None:
        """Center a paragraph and remove indents."""
        self.styles.center_paragraph(para)

    def _add_colored_run(self, paragraph, text: str, hex_color: Optional[str], **kwargs) -> Any:
        """Add a run with optional color and formatting."""
        run = paragraph.add_run(text)
        if hex_color:
            rgb = _parse_hex_color(hex_color)
            if rgb:
                run.font.color.rgb = RGBColor(*rgb)
        for key, val in kwargs.items():
            setattr(run, key, val) if hasattr(run, key) else setattr(run.font, key, val)
        return run


def create_resume_writer(
    data: Dict[str, Any],
    template: Dict[str, Any],
) -> ResumeWriterBase:
    """Factory function to create the appropriate resume writer.

    Args:
        data: Resume data (name, experience, education, etc.)
        template: Template configuration (sections, page styles, layout type)

    Returns:
        ResumeWriterBase subclass instance (StandardResumeWriter or SidebarResumeWriter)

    Examples:
        >>> # Standard single-column layout
        >>> data = {"name": "John Doe", "experience": [...]}
        >>> template = {"sections": [...], "page": {"compact": True}}
        >>> writer = create_resume_writer(data, template)
        >>> writer.write("resume.docx")

        >>> # Sidebar layout (two-column with repeating header)
        >>> template = {
        ...     "layout": {"type": "sidebar", "sidebar_width": 2.5},
        ...     "sections": [...],
        ...     "page": {"compact": True}
        ... }
        >>> writer = create_resume_writer(data, template)
        >>> writer.write("resume_sidebar.docx")
    """
    layout_cfg = template.get("layout") or {}
    layout_type = layout_cfg.get("type", "standard")

    if layout_type == "sidebar":
        from .docx_sidebar import SidebarResumeWriter
        return SidebarResumeWriter(data, template)
    else:
        from .docx_standard import StandardResumeWriter
        return StandardResumeWriter(data, template)
