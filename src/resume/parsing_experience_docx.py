"""DOCX resume parser helpers.

Extracted from parsing_experience. Provides:
  - _DocxParaHelper: paragraph style/text accessor
  - _docx_find_sections, _docx_try_extract_name, _docx_try_extract_headline
  - _docx_extract_name_headline, _docx_extract_summary, _filter_summary_lines
  - _docx_extract_education, _parse_h2_education
  - _process_exp_paragraph, _docx_extract_experience, _parse_h2_experience
  - _key_from_heading, _looks_like_company_line, _looks_like_section_heading
  - parse_resume_docx: public API
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .parsing_experience_text import (
    _extract_contact,
    _parse_education_entry,
    _parse_experience_entry,
    _parse_skills,
    _split_date_range,
)

# Style name constants used in DOCX parsing
_STYLE_TITLE_STYLES = {"title", "heading 0"}
_STYLE_HEADING_2 = "heading 2"


class _DocxParaHelper:
    """Helper for accessing paragraph style and text by index."""

    def __init__(self, paragraphs):
        self._paragraphs = paragraphs

    def style(self, i: int) -> str:
        return (getattr(self._paragraphs[i].style, "name", "") or "").lower()

    def text(self, i: int) -> str:
        return self._paragraphs[i].text.strip()

    def __len__(self) -> int:
        return len(self._paragraphs)


def _docx_find_sections(helper: _DocxParaHelper) -> tuple[List[int], Dict[str, Dict[str, int]]]:
    """Find H1 section indices and their bounds."""
    h1_indices = [i for i in range(len(helper)) if helper.style(i).startswith("heading 1")]
    sections: Dict[str, Dict[str, int]] = {}
    for idx in h1_indices:
        key = _key_from_heading(helper.text(idx))
        if key:
            sections[key] = {"start": idx}
    # Mark end bounds
    sorted_h1 = sorted([v["start"] for v in sections.values()])
    for key, info in sections.items():
        starts_after = [s for s in sorted_h1 if s > info["start"]]
        info["end"] = (starts_after[0] - 1) if starts_after else (len(helper) - 1)
    return h1_indices, sections


def _docx_try_extract_name(helper: _DocxParaHelper) -> str:
    """Try to extract candidate name from first paragraph."""
    if len(helper) and helper.style(0) in _STYLE_TITLE_STYLES:
        nm = helper.text(0)
        if any(c.isalpha() for c in nm) and len(nm) < 80:
            return nm
    return ""


def _docx_try_extract_headline(helper: _DocxParaHelper, i: int, txt: str) -> str:
    """Try to extract headline from second paragraph (index 1)."""
    if i == 1 and helper.style(0) in _STYLE_TITLE_STYLES and helper.style(1) == "normal":
        if not re.search(r"[@|]", txt) and len(txt) < 100:
            return txt
    return ""


def _docx_extract_name_headline(helper: _DocxParaHelper, first_h1: int) -> tuple[str, str, List[str]]:
    """Extract name, headline, and early lines from docx."""
    name = _docx_try_extract_name(helper)
    headline = ""
    early_lines: List[str] = []
    for i in range(min(first_h1, 10)):
        txt = helper.text(i)
        if txt:
            early_lines.append(txt)
            if not headline:
                headline = _docx_try_extract_headline(helper, i, txt)
    return name, headline, early_lines


def _docx_extract_summary(
    helper: _DocxParaHelper,
    sections: Dict[str, Dict[str, int]],
    h1_indices: List[int],
    first_h1: int,
) -> str:
    """Extract summary/profile from docx."""
    if "summary" in sections:
        s = sections["summary"]
        block = [helper.text(i) for i in range(s["start"] + 1, s["end"] + 1) if helper.text(i)]
        return " ".join(block).strip()

    if not h1_indices:
        return ""

    start_idx = 1 if helper.style(0) in _STYLE_TITLE_STYLES else 0
    if first_h1 <= start_idx:
        return ""

    preface = [helper.text(i) for i in range(start_idx, first_h1) if helper.text(i)]
    return " ".join(_filter_summary_lines(preface)).strip()


def _filter_summary_lines(lines: List[str]) -> List[str]:
    """Filter out contact/name/label lines from potential summary text."""
    cleaned = []
    for ln in lines:
        if re.search(r"[\w.\-+]+@[\w.\-]+", ln):
            continue
        if re.search(r"\+?\d[\d\s\-()]{6,}\d", ln):
            continue
        if "•" in ln:
            continue
        if ln.strip().lower().startswith("profile"):
            ln = ln.split(":", 1)[-1].strip()
            if not ln:
                continue
        cleaned.append(ln)
    return cleaned


def _docx_extract_education(
    helper: _DocxParaHelper, sections: Dict[str, Dict[str, int]]
) -> List[Dict[str, str]]:
    """Extract education entries from docx."""
    if "education" not in sections:
        return []

    education: List[Dict[str, str]] = []
    s = sections["education"]
    for i in range(s["start"] + 1, s["end"] + 1):
        line = helper.text(i)
        if not line:
            continue
        edu_entry = _parse_education_entry(line)
        if edu_entry:
            education.append(edu_entry)
            continue
        if helper.style(i).startswith(_STYLE_HEADING_2):
            education.append(_parse_h2_education(line))
    return education


def _parse_h2_education(line: str) -> Dict[str, str]:
    """Parse education from H2-style heading."""
    parts = [p.strip() for p in re.split(r"\t+|\s{2,}", line)]
    degree = parts[0] if parts else line
    year = ""
    if len(parts) > 1:
        m = re.search(r"(\d{4})(?!.*\d{4})", parts[-1])
        if m:
            year = m.group(1)
    return {"degree": degree, "institution": "", "year": year}


def _append_bullet_text(text: str, current: Optional[Dict[str, Any]], is_list_style: bool) -> None:
    """Append text as a bullet on current, stripping any bullet glyph if list-styled."""
    if not current:
        return
    bullet_text = re.sub(r"^[•\-\*]\s*", "", text).strip() if is_list_style else text
    if bullet_text:
        current.setdefault("bullets", []).append(bullet_text)


def _role_header_or_none(text: str) -> Optional[Dict[str, Any]]:
    """Parse text as a role header, or None if it is a bullet line.

    A line opening with a bullet glyph is always a bullet, never a role header.
    Without this guard, bullets phrased "<verb> ... at <Company>" match the role
    pattern and get promoted to standalone roles, splitting the real role's
    bullet list across phantom entries.

    The whitespace after the glyph is optional: DOCX exports and hand-typed
    resumes both produce unspaced bullets ("•Improve ...", "-Improve ..."), and
    those bypass a \\s+ guard. A role header never starts with one of these
    glyphs, so treating any glyph-prefixed line as a bullet is safe.
    """
    if re.match(r"^\s*[•\-\*]\s*", text):
        return None
    return _parse_experience_entry(text)


def _process_exp_paragraph(
    style: str, text: str, current: Optional[Dict[str, Any]], last_company: str,
    is_next_h2: bool
) -> tuple[Optional[Dict[str, Any]], str, Optional[Dict[str, Any]]]:
    """Process a single experience paragraph. Returns (current, last_company, completed_role)."""
    # _role_header_or_none, not _parse_experience_entry: a glyph-prefixed line
    # is always a bullet, never a role header (see #173).
    exp_entry = _role_header_or_none(text)
    if exp_entry and style in {"normal", "list paragraph"}:
        return {**exp_entry, "bullets": []}, last_company, current

    if style.startswith(_STYLE_HEADING_2):
        new_current, last_company = _parse_h2_experience(text, last_company)
        return new_current, last_company, current

    if style.startswith("list"):
        _append_bullet_text(text, current, is_list_style=True)
    elif _looks_like_company_line(text) and (current is None or is_next_h2):
        last_company = text.split("\t")[0].strip()
    elif current:
        _append_bullet_text(text, current, is_list_style=False)

    return current, last_company, None


def _docx_extract_experience(
    helper: _DocxParaHelper, sections: Dict[str, Dict[str, int]]
) -> List[Dict[str, Any]]:
    """Extract experience entries from docx."""
    exp_key = next((k for k in ("experience", "work experiences", "work experience") if k in sections), None)
    if not exp_key:
        return []

    s = sections[exp_key]
    experience: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    last_company = ""

    for i in range(s["start"] + 1, s["end"] + 1):
        text = helper.text(i)
        if not text:
            continue
        is_next_h2 = (i + 1) <= s["end"] and helper.style(i + 1).startswith(_STYLE_HEADING_2)
        current, last_company, completed = _process_exp_paragraph(
            helper.style(i), text, current, last_company, is_next_h2
        )
        if completed:
            experience.append(completed)

    if current:
        experience.append(current)
    return experience


def _parse_h2_experience(text: str, last_company: str) -> tuple[Dict[str, Any], str]:
    """Parse experience role from H2-style heading."""
    parts = [p.strip() for p in re.split(r"\t+|\s{2,}", text)]
    title = parts[0] if parts else text
    start, end = "", ""
    if len(parts) > 1 and "-" in parts[1]:
        start, end = _split_date_range(parts[1])
    role = {
        "title": title,
        "company": last_company,
        "start": start,
        "end": end,
        "location": "",
        "bullets": [],
    }
    return role, last_company


def _key_from_heading(text: str) -> Optional[str]:
    """Map heading text to section key based on keyword patterns."""
    low = (text or "").strip().lower()
    if not low:
        return None

    # Map section keys to their matching keywords
    keyword_map = {
        "experience": ["work experiences", "work experience", "experience", "employment", "career"],
        "education": ["education", "academics"],
        "skills": ["technical skills", "skills", "technologies"],
        "summary": ["summary", "profile", "about"],
    }

    for section_key, keywords in keyword_map.items():
        if any(k in low for k in keywords):
            return section_key

    return None


def _looks_like_company_line(text: str) -> bool:
    # Heuristic: Company <tab> Location OR contains Inc./Corp./Ltd or two tokens capitalized
    if "\t" in text:
        return True
    if re.search(r"\b(inc\.|corp\.|ltd\.|llc|technologies|labs|systems)\b", text, re.I):
        return True
    # Two or more capitalized words
    caps = re.findall(r"\b[A-Z][A-Za-z]+\b", text)
    return len(caps) >= 2


def _looks_like_section_heading(text: str) -> bool:
    """Check if a line looks like a section heading in a PDF.

    Heuristics:
    - Short line (< 40 chars)
    - All caps or title case
    - Matches known section patterns
    - No punctuation except colons
    """
    t = text.strip()
    if not t or len(t) > 50:
        return False
    # Check if it matches known sections
    if _key_from_heading(t):
        return True
    # All caps short line
    if t.isupper() and len(t) < 30:
        return True
    # Title case with no punctuation (except colon)
    stripped = re.sub(r"[:\s]", "", t)
    if stripped.istitle() and len(t) < 40 and not re.search(r"[.,;!?]", t):
        return True
    return False


def parse_resume_docx(path: str) -> Dict[str, Any]:
    """Parse resume directly from a .docx using heading styles."""
    from .io_utils import safe_import

    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Parsing .docx requires python-docx; install python-docx.")
    from docx import Document  # type: ignore

    doc = Document(path)
    helper = _DocxParaHelper(doc.paragraphs)

    h1_indices, sections = _docx_find_sections(helper)
    first_h1 = min(h1_indices) if h1_indices else len(helper)

    name, headline, early_lines = _docx_extract_name_headline(helper, first_h1)
    contact = _extract_contact(early_lines)
    summary = _docx_extract_summary(helper, sections, h1_indices, first_h1)

    skills: List[str] = []
    if "skills" in sections:
        s = sections["skills"]
        block = [helper.text(i) for i in range(s["start"] + 1, s["end"] + 1) if helper.text(i)]
        skills = _parse_skills(block)

    education = _docx_extract_education(helper, sections)
    experience = _docx_extract_experience(helper, sections)

    return {
        "name": name,
        "headline": headline,
        **contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
    }
