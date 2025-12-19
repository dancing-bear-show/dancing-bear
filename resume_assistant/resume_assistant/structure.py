from __future__ import annotations

from typing import Any, Dict, List, Optional

from .io_utils import safe_import
from .docx_writer import _match_section_key


def infer_structure_from_docx(path: str) -> Dict[str, Any]:
    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Inferring structure requires python-docx; install python-docx.")
    from docx import Document  # type: ignore

    doc = Document(path)
    order: List[str] = []
    titles: Dict[str, str] = {}
    seen = set()
    for p in doc.paragraphs:
        style = getattr(p.style, "name", "") or ""
        if style.lower().startswith("heading") and p.text.strip():
            key = _match_section_key(p.text) or p.text.strip().lower()
            ckey = key if key in {"summary", "skills", "experience", "education"} else None
            if ckey and ckey not in seen:
                seen.add(ckey)
                order.append(ckey)
                titles[ckey] = p.text.strip()
    # Default to common order if nothing found
    if not order:
        order = ["summary", "skills", "experience", "education"]
        titles = {
            "summary": "Summary",
            "skills": "Skills",
            "experience": "Experience",
            "education": "Education",
        }
    return {"order": order, "titles": titles}

