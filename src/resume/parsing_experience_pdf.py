"""PDF resume parser helpers.

Extracted from parsing_experience. Provides:
  - _pdf_empty_result, _pdf_looks_like_name, _pdf_looks_like_headline
  - _pdf_extract_name_headline, _pdf_find_sections, _pdf_get_section_lines
  - _pdf_extract_summary, _pdf_extract_experience, _pdf_extract_education
  - parse_resume_pdf: public API
"""
from __future__ import annotations

import re
from typing import Any

from .parsing_experience_text import (
    _extract_contact,
    _parse_education_entry,
    _parse_experience_entry,
    _parse_skills,
)
from .parsing_experience_docx import (
    _key_from_heading,
    _looks_like_section_heading,
)


def _pdf_empty_result() -> dict[str, Any]:
    """Return empty resume structure for PDF parsing."""
    return {
        "name": "", "headline": "", "email": "", "phone": "",
        "location": "", "linkedin": "", "github": "", "website": "",
        "summary": "", "skills": [], "experience": [], "education": [],
    }


def _pdf_looks_like_name(line: str) -> bool:
    return bool(line and len(line) < 60 and not _looks_like_section_heading(line) and not re.search(r"[@()\d]{3,}", line))


def _pdf_looks_like_headline(line: str) -> bool:
    return bool(len(line) < 80 and not _looks_like_section_heading(line) and not re.search(r"[@|]", line))


def _pdf_extract_name_headline(lines: list[str]) -> tuple[str, str]:
    """Extract name and headline from first lines of PDF."""
    if not lines:
        return "", ""
    name = lines[0] if _pdf_looks_like_name(lines[0]) else ""
    headline = ""
    if len(lines) > 1 and name and _pdf_looks_like_headline(lines[1]):
        headline = lines[1]
    return name, headline


def _pdf_find_sections(lines: list[str]) -> tuple[dict[str, int], list[tuple[str, int]]]:
    """Find section indices and sorted section list."""
    section_indices: dict[str, int] = {}
    for i, ln in enumerate(lines):
        if _looks_like_section_heading(ln):
            key = _key_from_heading(ln)
            if key and key not in section_indices:
                section_indices[key] = i
    sorted_sections = sorted(section_indices.items(), key=lambda x: x[1])
    return section_indices, sorted_sections


def _pdf_get_section_lines(
    key: str, lines: list[str], section_indices: dict[str, int],
    sorted_sections: list[tuple[str, int]]
) -> list[str]:
    """Get lines for a specific section."""
    if key not in section_indices:
        return []
    start = section_indices[key] + 1
    end = len(lines)
    for k, idx in sorted_sections:
        if idx > section_indices[key]:
            end = idx
            break
    return lines[start:end]


def _pdf_extract_summary(
    lines: list[str], section_indices: dict[str, int],
    sorted_sections: list[tuple[str, int]], has_name: bool
) -> str:
    """Extract summary from PDF."""
    summary_lines = _pdf_get_section_lines("summary", lines, section_indices, sorted_sections)
    if summary_lines:
        return " ".join(summary_lines).strip()

    if not sorted_sections:
        return ""

    first_section_idx = sorted_sections[0][1]
    start_idx = 2 if has_name else 0
    if first_section_idx <= start_idx:
        return ""

    candidate = lines[start_idx:first_section_idx]
    filtered = [
        ln for ln in candidate
        if not re.search(r"[@()\d]{5,}", ln)
        and not re.search(r"linkedin|github", ln, re.I)
    ]
    return " ".join(filtered).strip()


def _pdf_extract_experience(exp_lines: list[str]) -> list[dict[str, Any]]:
    """Extract experience entries from PDF lines."""
    experience: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for ln in exp_lines:
        job = _parse_experience_entry(ln)
        if job:
            if current:
                experience.append(current)
            current = {**job, "bullets": []}
        elif current:
            bullet = re.sub(r"^[•\-\*▪▸►]\s*", "", ln).strip()
            if bullet:
                current["bullets"].append(bullet)

    if current:
        experience.append(current)
    return experience


def _pdf_extract_education(edu_lines: list[str]) -> list[dict[str, str]]:
    """Extract education entries from PDF lines."""
    entries = []
    for ln in edu_lines:
        entry = _parse_education_entry(ln)
        if entry:
            entries.append(entry)
    return entries


def parse_resume_pdf(path: str) -> dict[str, Any]:
    """Parse resume from a PDF file."""
    from .io_utils import safe_import

    pdfminer = safe_import("pdfminer.high_level")
    if not pdfminer:
        raise RuntimeError("Parsing .pdf requires pdfminer.six; install pdfminer.six.")

    from pdfminer.high_level import extract_text
    from pdfminer.layout import LAParams

    laparams = LAParams(line_margin=0.5, word_margin=0.1, char_margin=2.0, boxes_flow=0.5)
    text = extract_text(path, laparams=laparams)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    if not lines:
        return _pdf_empty_result()

    contact = _extract_contact(lines[:15])
    name, headline = _pdf_extract_name_headline(lines)
    section_indices, sorted_sections = _pdf_find_sections(lines)

    summary = _pdf_extract_summary(lines, section_indices, sorted_sections, bool(name))
    skills = _parse_skills(_pdf_get_section_lines("skills", lines, section_indices, sorted_sections))
    experience = _pdf_extract_experience(
        _pdf_get_section_lines("experience", lines, section_indices, sorted_sections)
    )
    education = _pdf_extract_education(
        _pdf_get_section_lines("education", lines, section_indices, sorted_sections)
    )

    return {
        "name": name,
        "headline": headline,
        **contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
    }
