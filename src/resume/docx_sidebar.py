"""DOCX sidebar layout resume writer.

Provides two-column sidebar layout with repeating header.

This module is a re-export shim. Implementation lives in:
  - docx_sidebar_cells: cell-level formatting primitives
  - docx_sidebar_sections: section-level rendering and SidebarResumeWriter
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .docx_sidebar_cells import (  # noqa: F401
    _remove_cell_borders,
    _render_main_section_heading,
    _render_sidebar_section,
    _set_cell_shading,
)
from .docx_sidebar_sections import (  # noqa: F401
    SidebarResumeWriter,
    _render_exp_entry,
    _render_main_education,
    _render_main_experience,
    _render_main_presentations,
    _render_main_teaching,
    _render_pres_entry,
)


# Backward-compatible function defined here so that
# `@patch("resume.docx_sidebar.SidebarResumeWriter")` resolves correctly.
def write_resume_docx_sidebar(
    data: Dict[str, Any],
    template: Dict[str, Any],
    out_path: str,
    seed: Optional[Dict[str, Any]] = None,
) -> None:
    """Write resume with two-column sidebar layout.

    This function is provided for backward compatibility.
    Prefer using SidebarResumeWriter directly.
    """
    writer = SidebarResumeWriter(data, template)
    writer.write(out_path, seed)
