"""Plain-text resume parser helpers.

Extracted from parsing_experience. Provides:
  - SECTION_PATTERNS: section heading regex patterns
  - Shared string utilities: _split_lines, _match_first, _match_website
  - Contact extraction: _extract_contact, _extract_sections
  - Entry parsers: _split_date_range, _parse_experience_entry, _parse_education_entry
  - Section parsers: _parse_experience, _parse_experience_block, _parse_education, _parse_skills
  - Public API: parse_resume_text, merge_profiles
"""
from __future__ import annotations

import re
from typing import Any

from core.collections import dedupe


SECTION_PATTERNS = {
    "experience": re.compile(r"^\s*(experience|work history|employment)\s*$", re.I),
    "education": re.compile(r"^\s*(education|academics)\s*$", re.I),
    "skills": re.compile(r"^\s*(skills|technologies|technical skills)\s*$", re.I),
    "summary": re.compile(r"^\s*(summary|profile|about)\s*$", re.I),
    "contact": re.compile(r"^\s*(contact|contact info|info)\s*$", re.I),
}

# Date range pattern fragment used in experience parsing
# Matches: "2020", "Jan 2020", combined with "-" or "–" separator
_DATE_PART = r"(?:\d{4}|\w+\s+\d{4})"
_DATE_RANGE_PAT = rf"({_DATE_PART}\s*[-–]\s*(?:\d{{4}}|Present|Current|{_DATE_PART}))"


def _split_date_range(date_range: str) -> tuple[str, str]:
    """Split a date range string like '2020 - Present' into (start, end)."""
    if "–" in date_range or "-" in date_range:
        parts = re.split(r"\s*[-–]\s*", date_range)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _parse_experience_entry(text: str) -> dict[str, Any] | None:
    """Parse a job header line into structured data.

    Handles common formats:
    - "Title at Company — [Location] — (Start – End)"  (generated DOCX format)
    - "Title at Company, 2020-2023"
    - "Title | Company | 2020 - Present"
    - "Title at Company (Jan 2020 - Dec 2023)"

    Returns dict with: title, company, location, start, end, or None if not matched.
    """
    # Pattern 1: Generated DOCX format "Title at Company — [Location] — (Start – End)"
    m = re.match(
        r"(.+?)\s+at\s+(.+?)"  # Title at Company
        r"(?:\s*[—\-]\s*\[?([^\]—\-\(]+?)\]?)?"  # — [Location] or — Location
        r"(?:\s*[—\-]\s*\(?([\d\w\s]+?)\s*[–\-]\s*([\d\w\s]+?)\)?\s*)?$",  # — (Start – End)
        text
    )
    if m:
        return {
            "title": m.group(1).strip(),
            "company": m.group(2).strip(),
            "location": (m.group(3) or "").strip(),
            "start": (m.group(4) or "").strip(),
            "end": (m.group(5) or "").strip(),
        }

    # Pattern 2: "Title at Company, dates" or "Title at Company (dates)"
    m = re.match(
        rf"(.+?)\s+at\s+(.+?)(?:[,\s]+|\s*\(){_DATE_RANGE_PAT}\)?",
        text, re.I
    )
    if m:
        start, end = _split_date_range(m.group(3).strip())
        return {
            "title": m.group(1).strip(),
            "company": m.group(2).strip().rstrip(","),
            "location": "",
            "start": start,
            "end": end,
        }

    # Pattern 3: "Title | Company | dates"
    parts = [p.strip() for p in re.split(r"\s*[|•·]\s*", text)]
    if len(parts) >= 2:
        date_idx = next(
            (i for i, p in enumerate(parts)
             if re.search(r"\d{4}\s*[-–]\s*(?:\d{4}|Present|Current)", p, re.I)),
            -1
        )
        if date_idx >= 0:
            start, end = _split_date_range(parts[date_idx])
            return {
                "title": parts[0],
                "company": parts[1] if len(parts) > 1 and date_idx != 1 else "",
                "location": "",
                "start": start,
                "end": end,
            }

    # Pattern 4: Simple "Title at Company"
    m = re.match(r"(.+?)\s+at\s+(.+)$", text)
    if m:
        return {
            "title": m.group(1).strip(),
            "company": m.group(2).strip(),
            "location": "",
            "start": "",
            "end": "",
        }

    return None


def _parse_education_entry(text: str) -> dict[str, str] | None:
    """Parse an education line into structured data.

    Handles common formats:
    - "Degree at Institution — (Year)"  (generated DOCX format)
    - "B.S. Computer Science, MIT, 2016"
    - "Bachelor of Science in CS — MIT (2016)"
    - "Degree from Institution (Year)"

    Returns dict with: degree, institution, year, or None if not matched.
    """
    # Pattern 1: Generated format "Degree at Institution — (Year)", where the
    # parenthesised part may be a single year or a range ("2003 – 2007"). On a
    # range the graduation year is the later one, which is what a resume shows;
    # without the range branch the whole "— (2003 – 2007)" stays glued to the
    # institution and year comes back empty.
    m = re.match(
        r"(.+?)\s+at\s+(.+?)"
        r"(?:\s*[—\-]\s*\((\d{4})(?:\s*[–\-]\s*(\d{4}))?\))?$",
        text,
    )
    if m:
        return {
            "degree": m.group(1).strip(),
            "institution": m.group(2).strip(),
            "year": (m.group(4) or m.group(3) or "").strip(),
        }

    # Pattern 2: "Degree, Institution, Year"
    m = re.match(r"(.+?),\s*(.+?),\s*(\d{4})", text)
    if m:
        return {
            "degree": m.group(1).strip(),
            "institution": m.group(2).strip(),
            "year": m.group(3).strip(),
        }

    # Pattern 3: "Degree from Institution (Year)" - greedy institution match
    m = re.match(r"(.+?)\s+from\s+(.+?)(?:\s*[\(\-—]\s*(\d{4})\)?)?$", text, re.I)
    if m:
        return {
            "degree": m.group(1).strip(),
            "institution": m.group(2).strip().rstrip("()"),
            "year": (m.group(3) or "").strip(),
        }

    # Pattern 4: Look for year anywhere in short line
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match and len(text) < 100:
        year = year_match.group(0)
        rest = text.replace(year, "").strip(" ,-–—()")
        if rest:
            return {
                "degree": rest,
                "institution": "",
                "year": year,
            }

    return None


def _split_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines()]


_PAT_EMAIL = re.compile(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}")
_PAT_PHONE = re.compile(r"\+?1?\s*\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
_PAT_LOCATION = re.compile(r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*),\s*[A-Z]{2}")
_PAT_LINKEDIN = re.compile(r"linkedin\.com/in/[\w\-]+", re.I)
_PAT_GITHUB = re.compile(r"github\.com/[\w\-]+", re.I)
_PAT_WEBSITE = re.compile(r"(?:https?://|www\.)([a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(?:/[\w\-/]*)?)")


def _match_first(pat: re.Pattern, ln: str) -> str:
    m = pat.search(ln)
    return m.group(0) if m else ""


def _match_website(ln: str) -> str:
    m = _PAT_WEBSITE.search(ln)
    if m and "linkedin" not in m.group(0).lower() and "github" not in m.group(0).lower():
        return m.group(0)
    return ""


# Field name -> single-arg matcher (line -> matched substring or "").
_CONTACT_MATCHERS: dict[str, Any] = {
    "email": lambda ln: _match_first(_PAT_EMAIL, ln),
    "phone": lambda ln: _match_first(_PAT_PHONE, ln),
    "location": lambda ln: _match_first(_PAT_LOCATION, ln),
    "linkedin": lambda ln: _match_first(_PAT_LINKEDIN, ln),
    "github": lambda ln: _match_first(_PAT_GITHUB, ln),
    "website": _match_website,
}


def _extract_contact(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {k: "" for k in _CONTACT_MATCHERS}
    for ln in lines[:10]:  # top lines commonly have contact
        for key, matcher in _CONTACT_MATCHERS.items():
            if not fields[key]:
                fields[key] = matcher(ln)
    return {k: v.strip() for k, v in fields.items()}


def _extract_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "body"
    sections[current] = []
    for ln in lines:
        matched = False
        for key, pat in SECTION_PATTERNS.items():
            if pat.match(ln):
                current = key
                sections.setdefault(current, [])
                matched = True
                break
        if matched:
            continue
        sections.setdefault(current, [])
        sections[current].append(ln)
    return sections


def _parse_experience(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    buf: list[str] = []
    def push() -> None:
        if not buf:
            return
        items.append(_parse_experience_block(buf.copy()))
        buf.clear()
    for ln in lines:
        # simple delimiter between roles: blank line or leading dash indicator of new role
        if not ln.strip():
            push()
            continue
        if re.match(r"^[A-Z].* at .+", ln) and buf:
            push()
        buf.append(ln)
    push()
    # drop empties
    return [it for it in items if any(v for v in it.values())]


def _parse_experience_header(header: str) -> dict[str, str]:
    """Parse the header line: "Senior Engineer at FooCorp (2020-2023) - City, ST"."""
    title = company = start = end = location = ""
    m = re.match(r"(.+?)\s+at\s+(.+?)(?:\s*\(([^)]+)\))?(?:\s*-\s*(.+))?$", header, re.I)
    if m:
        title = m.group(1).strip()
        company = m.group(2).strip()
        date_span = (m.group(3) or "").strip()
        if date_span and "-" in date_span:
            parts = [s.strip() for s in date_span.split("-")]
            if len(parts) == 2:
                start, end = parts
        location = (m.group(4) or "").strip()
    return {"title": title, "company": company, "start": start, "end": end, "location": location}


def _extract_bullets(lines: list[str]) -> list[str]:
    """Extract bullet/description lines: '-'/'*'-prefixed or plain non-empty lines."""
    bullets: list[str] = []
    for ln in lines:
        if re.match(r"^[-*]\s+", ln):
            bullets.append(re.sub(r"^[-*]\s+", "", ln).strip())
        elif ln:
            bullets.append(ln)
    return bullets


def _parse_experience_block(block: list[str]) -> dict[str, Any]:
    if not block:
        return {"title": "", "company": "", "start": "", "end": "", "location": "", "bullets": []}
    header_fields = _parse_experience_header(block[0])
    bullets = _extract_bullets(block[1:])
    return {**header_fields, "bullets": bullets}


def _parse_education(lines: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ln in lines:
        # e.g., BS Computer Science, University, 2015
        m = re.match(r"(.+?),\s*(.+?),\s*(\d{4})", ln)
        if m:
            out.append({"degree": m.group(1).strip(), "institution": m.group(2).strip(), "year": m.group(3).strip()})
        else:
            # fallback single-line
            if ln:
                out.append({"degree": ln, "institution": "", "year": ""})
    return out


def _parse_skills(lines: list[str]) -> list[str]:
    text = " ".join(lines)
    # split by pipes, commas, semicolons, or bullet points
    parts = [p.strip() for p in re.split(r"[|,;•·]\s*", text) if p.strip()]
    return dedupe(parts, key_fn=str.lower)


def parse_resume_text(text: str) -> dict[str, Any]:
    lines = _split_lines(text)
    sections = _extract_sections(lines)
    head = lines[0] if lines else ""
    name = head.strip()
    contact = _extract_contact(lines)
    summary_lines = sections.get("summary", []) or sections.get("body", [])[:3]
    summary = " ".join(summary_lines).strip()
    experience = _parse_experience(sections.get("experience", []))
    education = _parse_education(sections.get("education", []))
    skills = _parse_skills(sections.get("skills", []))
    return {
        "name": name,
        "headline": "",
        **contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
    }


def merge_profiles(linkedin: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    # Merge with field-aware precedence: prefer LinkedIn for identity fields
    out: dict[str, Any] = {**linkedin, **{k: v for k, v in resume.items() if v}}
    # Merge list fields with resume-first then linkedin-only missing
    def merge_lists(a: list[Any], b: list[Any]) -> list[Any]:
        return (a or []) + ([x for x in b or [] if x not in (a or [])])

    out["skills"] = merge_lists(resume.get("skills", []), linkedin.get("skills", []))
    # Prefer LinkedIn-derived name/headline when available
    name_li = linkedin.get("name") or ""
    if name_li:
        out["name"] = name_li
    headline_li = linkedin.get("headline") or ""
    if headline_li:
        out["headline"] = headline_li
    return out
