"""Base class for DOCX resume writers.

Provides common functionality for resume rendering.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from docx.shared import Pt, Inches, RGBColor  # type: ignore
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore

from .io_utils import safe_import
from .docx_styles import (
    StyleManager,
    TextFormatter,
    _parse_hex_color,
    _is_dark,
    _format_link_display,
)


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
        if not self.page_cfg.get("compact"):
            return

        try:
            sec = self.doc.sections[0]
            m = float(self.page_cfg.get("margins_in", 0.5))
            sec.top_margin = Inches(m)
            sec.bottom_margin = Inches(m)
            sec.left_margin = Inches(m)
            sec.right_margin = Inches(m)
        except Exception:  # noqa: S110
            pass

        try:
            body_pt = float(self.page_cfg.get("body_pt", 10.5))
            h1_pt = float(self.page_cfg.get("h1_pt", 12))
            title_pt = float(self.page_cfg.get("title_pt", 14))
            h1_color = self.page_cfg.get("h1_color") or self.page_cfg.get("heading_color")
            h1_bg = self.page_cfg.get("h1_bg") or self.page_cfg.get("heading_bg")
            title_color = self.page_cfg.get("title_color")

            self.doc.styles["Normal"].font.size = Pt(body_pt)

            if "Heading 1" in self.doc.styles:
                self.doc.styles["Heading 1"].font.size = Pt(h1_pt)
                self.doc.styles["Heading 1"].font.bold = True
                rgb = _parse_hex_color(h1_color)
                bg = _parse_hex_color(h1_bg)
                if (not rgb) and bg:
                    rgb = (255, 255, 255) if _is_dark(bg) else (0, 0, 0)
                if rgb:
                    self.doc.styles["Heading 1"].font.color.rgb = RGBColor(*rgb)

            if "Title" in self.doc.styles:
                self.doc.styles["Title"].font.size = Pt(title_pt)
                self.doc.styles["Title"].font.bold = True
                rgbt = _parse_hex_color(title_color)
                if rgbt:
                    self.doc.styles["Title"].font.color.rgb = RGBColor(*rgbt)
        except Exception:  # noqa: S110
            pass

    def _set_document_metadata(self) -> None:
        """Set document core properties (title, author, keywords)."""
        try:
            name = self.data.get("name") or ""
            contact = self.data.get("contact") or {}
            email = self.data.get("email") or contact.get("email") or ""
            phone = self.data.get("phone") or contact.get("phone") or ""
            location = self.data.get("location") or contact.get("location") or ""

            cp = self.doc.core_properties
            contact_line = " | ".join([p for p in [email, phone, location] if p])
            cp.title = " - ".join([p for p in [name, contact_line] if p]) or "Resume"
            cp.subject = "Resume"
            if name:
                cp.author = name

            kw = [k for k in [name, email, phone, location] if k]
            include_exp_locs = bool(self.page_cfg.get("metadata_include_locations", True))

            if include_exp_locs:
                uniq_locs = self._extract_experience_locations()
                kw.extend(uniq_locs)
                if uniq_locs:
                    try:
                        cp.category = "; ".join(uniq_locs)
                    except Exception:  # noqa: S110
                        pass

            cp.keywords = "; ".join(kw)
        except Exception:  # noqa: S110
            pass

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
        try:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = para.paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
        except Exception:  # noqa: S110
            pass

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
