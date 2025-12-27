from __future__ import annotations

import re
from typing import Any, Dict, List
from typing import Optional


SECTION_PATTERNS = {
    "experience": re.compile(r"^\s*(experience|work history|employment)\s*$", re.I),
    "education": re.compile(r"^\s*(education|academics)\s*$", re.I),
    "skills": re.compile(r"^\s*(skills|technologies|technical skills)\s*$", re.I),
    "summary": re.compile(r"^\s*(summary|profile|about)\s*$", re.I),
    "contact": re.compile(r"^\s*(contact|contact info|info)\s*$", re.I),
}


# =============================================================================
# Shared extraction utilities (used by both DOCX and PDF parsers)
# =============================================================================


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
        r"(.+?)\s+at\s+(.+?)(?:[,\s]+|\s*\()((?:\d{4}|\w+\s+\d{4})\s*[-–]\s*(?:\d{4}|Present|Current|\w+\s+\d{4}))\)?",
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
    m = re.match(r"(.+?)\s+at\s+(.+?)$", text)
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


def _extract_contact(lines: List[str]) -> Dict[str, str]:
    email = ""
    phone = ""
    location = ""
    linkedin = ""
    github = ""
    website = ""
    for ln in lines[:10]:  # top lines commonly have contact
        if not email:
            m = re.search(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", ln)
            if m:
                email = m.group(0)
        if not phone:
            # Match phone formats: (555) 123-4567, +1 (555) 123-4567, 555-123-4567
            m = re.search(r"\+?1?\s*\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}", ln)
            if m:
                phone = m.group(0)
        if not location:
            # naive location: look for City, ST pattern
            m = re.search(r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*),\s*[A-Z]{2}", ln)
            if m:
                location = m.group(0)
        if not linkedin:
            m = re.search(r"linkedin\.com/in/[\w\-]+", ln, re.I)
            if m:
                linkedin = m.group(0)
        if not github:
            m = re.search(r"github\.com/[\w\-]+", ln, re.I)
            if m:
                github = m.group(0)
        if not website:
            # Generic URL that's not linkedin/github/email domain
            # Must have scheme or www prefix, or be a standalone domain (not part of email)
            m = re.search(r"(?:https?://|www\.)([a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(?:/[\w\-/]*)?)", ln)
            if m and "linkedin" not in m.group(0).lower() and "github" not in m.group(0).lower():
                website = m.group(0)
    return {
        "email": email.strip(),
        "phone": phone.strip(),
        "location": location.strip(),
        "linkedin": linkedin.strip(),
        "github": github.strip(),
        "website": website.strip(),
    }


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


def parse_linkedin_text(text: str) -> Dict[str, Any]:
    # If HTML, attempt to parse metadata (og:title, og:description, profile:* meta tags)
    if "<html" in text.lower() or "<meta" in text.lower():
        meta = _parse_linkedin_meta_from_html(text)
        if meta:
            return meta
    # Fallback plain-text heuristics
    lines = _split_lines(text)
    sections = _extract_sections(lines)
    head = lines[0] if lines else ""
    name = head.strip()
    contact = _extract_contact(lines)
    summary = " ".join(sections.get("summary", [])).strip()
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


def _parse_linkedin_meta_from_html(html_text: str) -> Dict[str, Any]:
    # Extract name/headline/location/summary from meta tags in public profile HTML
    def mprop(prop: str) -> str:
        m = re.search(rf"<meta[^>]+property=\"{re.escape(prop)}\"[^>]+content=\"([^\"]+)\"", html_text, re.I)
        return (m.group(1).strip() if m else "")

    def mname(name: str) -> str:
        m = re.search(rf"<meta[^>]+name=\"{re.escape(name)}\"[^>]+content=\"([^\"]+)\"", html_text, re.I)
        return (m.group(1).strip() if m else "")

    title_tag = ""
    m = re.search(r"<title>([^<]+)</title>", html_text, re.I)
    if m:
        title_tag = m.group(1).strip()

    first = mprop("profile:first_name")
    last = mprop("profile:last_name")
    og_title = mprop("og:title") or title_tag
    desc = mname("og:description") or mname("description")

    name = (first + " " + last).strip()
    headline = ""
    # title form: "Name - Headline | LinkedIn"
    if not name and og_title:
        # extract text before ' - '
        if " - " in og_title:
            name = og_title.split(" - ", 1)[0].strip()
            headline = og_title.split(" - ", 1)[1].split("|")[0].strip()
        else:
            name = og_title.split("|")[0].strip()

    if name and og_title and not headline and " - " in og_title:
        headline = og_title.split(" - ", 1)[1].split("|")[0].strip()

    # Parse description: "<summary> · Experience: <company> · Location: <loc> · ..."
    summary = ""
    location = ""
    if desc:
        parts = [p.strip() for p in desc.split("·")]
        if parts:
            summary = parts[0].strip()
        for p in parts[1:]:
            if p.lower().startswith("location:"):
                location = p.split(":", 1)[1].strip()

    out = {
        "name": name,
        "headline": headline,
        "email": "",
        "phone": "",
        "location": location,
        "summary": summary,
        "skills": [],
        "experience": [],
        "education": [],
    }
    # If we got at least a name or summary, consider success
    if any(out.get(k) for k in ("name", "summary", "headline")):
        return out
    return {}


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


# =============================================================================
# DOCX parsing helpers
# =============================================================================


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


def _docx_extract_name_headline(helper: _DocxParaHelper, first_h1: int) -> tuple[str, str, List[str]]:
    """Extract name, headline, and early lines from docx."""
    name = ""
    headline = ""
    if len(helper) and helper.style(0) in {"title", "heading 0"}:
        nm = helper.text(0)
        if any(c.isalpha() for c in nm) and len(nm) < 80:
            name = nm

    early_lines: List[str] = []
    for i in range(min(first_h1, 10)):
        txt = helper.text(i)
        if txt:
            early_lines.append(txt)
            if i == 1 and helper.style(0) in {"title", "heading 0"} and helper.style(1) == "normal":
                if not re.search(r"[@|]", txt) and len(txt) < 100:
                    headline = txt
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

    start_idx = 1 if helper.style(0) in {"title", "heading 0"} else 0
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
        if "\u2022" in ln or "•" in ln:
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
        if helper.style(i).startswith("heading 2"):
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


def _process_exp_paragraph(
    style: str, text: str, current: Optional[Dict[str, Any]], last_company: str,
    is_next_h2: bool
) -> tuple[Optional[Dict[str, Any]], str, Optional[Dict[str, Any]]]:
    """Process a single experience paragraph. Returns (current, last_company, completed_role)."""
    completed = None

    # Try shared experience entry parser
    exp_entry = _parse_experience_entry(text)
    if exp_entry and style in {"normal", "list paragraph"}:
        if current:
            completed = current
        return {**exp_entry, "bullets": []}, last_company, completed

    if style.startswith("heading 2"):
        if current:
            completed = current
        new_current, last_company = _parse_h2_experience(text, last_company)
        return new_current, last_company, completed

    if style.startswith("list"):
        bullet_text = re.sub(r"^[•\-\*]\s*", "", text).strip()
        if current and bullet_text:
            current.setdefault("bullets", []).append(bullet_text)
    elif _looks_like_company_line(text) and (current is None or is_next_h2):
        last_company = text.split("\t")[0].strip()
    elif current:
        current.setdefault("bullets", []).append(text)

    return current, last_company, completed


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
        is_next_h2 = (i + 1) <= s["end"] and helper.style(i + 1).startswith("heading 2")
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


def _key_from_heading(text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    if not low:
        return None
    if any(k in low for k in ["work experiences", "work experience", "experience", "employment", "career"]):
        return "experience"
    if any(k in low for k in ["education", "academics"]):
        return "education"
    if any(k in low for k in ["technical skills", "skills", "technologies"]):
        return "skills"
    if any(k in low for k in ["summary", "profile", "about"]):
        return "summary"
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


# =============================================================================
# PDF parsing helpers
# =============================================================================


def _pdf_empty_result() -> Dict[str, Any]:
    """Return empty resume structure for PDF parsing."""
    return {
        "name": "", "headline": "", "email": "", "phone": "",
        "location": "", "linkedin": "", "github": "", "website": "",
        "summary": "", "skills": [], "experience": [], "education": [],
    }


def _pdf_extract_name_headline(lines: List[str]) -> tuple[str, str]:
    """Extract name and headline from first lines of PDF."""
    name = ""
    headline = ""
    if not lines:
        return name, headline

    first_line = lines[0]
    if first_line and len(first_line) < 60:
        if not _looks_like_section_heading(first_line):
            if not re.search(r"[@()\d]{3,}", first_line):
                name = first_line

    if len(lines) > 1 and name:
        second = lines[1]
        if len(second) < 80 and not _looks_like_section_heading(second):
            if not re.search(r"[@|]", second):
                headline = second

    return name, headline


def _pdf_find_sections(lines: List[str]) -> tuple[Dict[str, int], List[tuple[str, int]]]:
    """Find section indices and sorted section list."""
    section_indices: Dict[str, int] = {}
    for i, ln in enumerate(lines):
        if _looks_like_section_heading(ln):
            key = _key_from_heading(ln)
            if key and key not in section_indices:
                section_indices[key] = i
    sorted_sections = sorted(section_indices.items(), key=lambda x: x[1])
    return section_indices, sorted_sections


def _pdf_get_section_lines(
    key: str, lines: List[str], section_indices: Dict[str, int],
    sorted_sections: List[tuple[str, int]]
) -> List[str]:
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
    lines: List[str], section_indices: Dict[str, int],
    sorted_sections: List[tuple[str, int]], has_name: bool
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


def _pdf_extract_experience(exp_lines: List[str]) -> List[Dict[str, Any]]:
    """Extract experience entries from PDF lines."""
    experience: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

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


def _pdf_extract_education(edu_lines: List[str]) -> List[Dict[str, str]]:
    """Extract education entries from PDF lines."""
    entries = []
    for ln in edu_lines:
        entry = _parse_education_entry(ln)
        if entry:
            entries.append(entry)
    return entries


def parse_resume_pdf(path: str) -> Dict[str, Any]:
    """Parse resume from a PDF file."""
    from .io_utils import safe_import

    pdfminer = safe_import("pdfminer.high_level")
    if not pdfminer:
        raise RuntimeError("Parsing .pdf requires pdfminer.six; install pdfminer.six.")

    from pdfminer.high_level import extract_text  # type: ignore
    from pdfminer.layout import LAParams  # type: ignore

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
