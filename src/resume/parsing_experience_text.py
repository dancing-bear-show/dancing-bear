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
from typing import Any, Dict, List, Optional


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


def _parse_experience_entry(text: str) -> Optional[Dict[str, Any]]:
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


def _parse_education_entry(text: str) -> Optional[Dict[str, str]]:
    """Parse an education line into structured data.

    Handles common formats:
    - "Degree at Institution — (Year)"  (generated DOCX format)
    - "B.S. Computer Science, MIT, 2016"
    - "Bachelor of Science in CS — MIT (2016)"
    - "Degree from Institution (Year)"

    Returns dict with: degree, institution, year, or None if not matched.
    """
    # Pattern 1: Generated format "Degree at Institution — (Year)"
    m = re.match(r"(.+?)\s+at\s+(.+?)(?:\s*—\s*\((\d{4})\))?$", text)
    if m:
        return {
            "degree": m.group(1).strip(),
            "institution": m.group(2).strip(),
            "year": (m.group(3) or "").strip(),
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


def _split_lines(text: str) -> List[str]:
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


def _extract_contact(lines: List[str]) -> Dict[str, str]:
    fields: Dict[str, str] = {k: "" for k in ("email", "phone", "location", "linkedin", "github", "website")}
    for ln in lines[:10]:  # top lines commonly have contact
        if not fields["email"]:
            fields["email"] = _match_first(_PAT_EMAIL, ln)
        if not fields["phone"]:
            fields["phone"] = _match_first(_PAT_PHONE, ln)
        if not fields["location"]:
            fields["location"] = _match_first(_PAT_LOCATION, ln)
        if not fields["linkedin"]:
            fields["linkedin"] = _match_first(_PAT_LINKEDIN, ln)
        if not fields["github"]:
            fields["github"] = _match_first(_PAT_GITHUB, ln)
        if not fields["website"]:
            fields["website"] = _match_website(ln)
    return {k: v.strip() for k, v in fields.items()}


def _extract_sections(lines: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
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


def _parse_experience(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    buf: List[str] = []
    def push():
        return (items.append(_parse_experience_block(buf.copy())), buf.clear()) if buf else None
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


def _parse_experience_block(block: List[str]) -> Dict[str, Any]:
    title = company = start = end = location = ""
    bullets: List[str] = []
    if not block:
        return {"title": title, "company": company, "start": start, "end": end, "location": location, "bullets": bullets}
    header = block[0]
    # Heuristic: "Senior Engineer at FooCorp (2020-2023) - City, ST"
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
    # bullets are lines starting with - or * otherwise description lines
    for ln in block[1:]:
        if re.match(r"^[-*]\s+", ln):
            bullets.append(re.sub(r"^[-*]\s+", "", ln).strip())
        elif ln:
            bullets.append(ln)
    return {"title": title, "company": company, "start": start, "end": end, "location": location, "bullets": bullets}


def _parse_education(lines: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
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


def _parse_skills(lines: List[str]) -> List[str]:
    text = " ".join(lines)
    # split by pipes, commas, semicolons, or bullet points
    parts = [p.strip() for p in re.split(r"[|,;•·]\s*", text) if p.strip()]
    # dedupe while preserving order
    seen = set()
    skills = []
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            skills.append(p)
    return skills


def parse_resume_text(text: str) -> Dict[str, Any]:
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


def merge_profiles(linkedin: Dict[str, Any], resume: Dict[str, Any]) -> Dict[str, Any]:
    # Merge with field-aware precedence: prefer LinkedIn for identity fields
    out: Dict[str, Any] = {**linkedin, **{k: v for k, v in resume.items() if v}}
    # Merge list fields with resume-first then linkedin-only missing
    def merge_lists(a: List[Any], b: List[Any]) -> List[Any]:
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
