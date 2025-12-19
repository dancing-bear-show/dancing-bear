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


def _split_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines()]


def _extract_contact(lines: List[str]) -> Dict[str, str]:
    email = ""
    phone = ""
    location = ""
    for ln in lines[:10]:  # top lines commonly have contact
        if not email:
            m = re.search(r"[\w.\-+]+@[\w.\-]+", ln)
            if m:
                email = m.group(0)
        if not phone:
            m = re.search(r"\+?\d[\d\s\-()]{6,}\d", ln)
            if m:
                phone = m.group(0)
        if not location:
            # naive location: look for City, ST pattern
            m = re.search(r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*),\s*[A-Z]{2}", ln)
            if m:
                location = m.group(0)
    return {"email": email, "phone": phone, "location": location}


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
    push = lambda: (items.append(_parse_experience_block(buf.copy())), buf.clear()) if buf else None
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
    m = re.match(r"(.+?)\s+at\s+(.+?)(?:\s*\(([^)]+)\))?(?:\s*-\s*(.+))?", header, re.I)
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
    # split by commas or semicolons
    parts = [p.strip() for p in re.split(r"[,;]\s*", text) if p.strip()]
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


def parse_resume_docx(path: str) -> Dict[str, Any]:
    """Parse resume directly from a .docx using heading styles.

    Heuristics tuned for common structures:
    - H1: section titles like Education, Technical Skills, Work Experience(s)
    - H2 under Work Experience: role with date span (tab-separated)
      Preceded by a normal paragraph with company and location
      Following normal paragraphs are bullets/achievements until next H2 or H1
    - H2 under Education: degree line (tab-separated with dates)
    - Skills: paragraphs under Technical Skills until next H1
    """
    from .io_utils import safe_import

    docx = safe_import("docx")
    if not docx:
        raise RuntimeError("Parsing .docx requires python-docx; install python-docx.")
    from docx import Document  # type: ignore

    doc = Document(path)
    paragraphs = doc.paragraphs

    def para_style(i: int) -> str:
        return (getattr(paragraphs[i].style, "name", "") or "").lower()

    def para_text(i: int) -> str:
        return paragraphs[i].text.strip()

    # Identify H1 sections (exclude the document Title)
    h1_indices: List[int] = [i for i, p in enumerate(paragraphs) if para_style(i).startswith("heading 1")]
    sections: Dict[str, Dict[str, int]] = {}
    for idx in h1_indices:
        title = para_text(idx)
        key = _key_from_heading(title)
        if key:
            sections[key] = {"start": idx}
    # mark end bounds
    sorted_h1 = sorted([v["start"] for v in sections.values()])
    for key, info in sections.items():
        starts_after = [s for s in sorted_h1 if s > info["start"]]
        info["end"] = (starts_after[0] - 1) if starts_after else (len(paragraphs) - 1)

    # Name: first title paragraph if present and not generic
    name = ""
    if paragraphs and para_style(0) in {"title", "heading 0"}:
        nm = para_text(0)
        # Avoid capturing filenames
        if any(c.isalpha() for c in nm) and len(nm) < 80:
            name = nm

    # Summary/Profile
    summary = ""
    if "summary" in sections:
        s = sections["summary"]
        block = [para_text(i) for i in range(s["start"] + 1, s["end"] + 1) if para_text(i)]
        summary = " ".join(block).strip()
    else:
        # If no explicit summary section, use text before first H1 as profile
        if h1_indices:
            first_h1 = min(h1_indices)
            # Skip first paragraph if it's a title/filename
            start_idx = 1 if para_style(0) in {"title", "heading 0"} else 0
            if first_h1 > start_idx:
                preface = [para_text(i) for i in range(start_idx, first_h1) if para_text(i)]
                # Drop likely contact/name/label lines
                cleaned = []
                for ln in preface:
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
                summary = " ".join(cleaned).strip()

    # Skills
    skills: List[str] = []
    if "skills" in sections:
        s = sections["skills"]
        block = [para_text(i) for i in range(s["start"] + 1, s["end"] + 1) if para_text(i)]
        skills = _parse_skills(block)

    # Education
    education: List[Dict[str, str]] = []
    if "education" in sections:
        s = sections["education"]
        i = s["start"] + 1
        while i <= s["end"]:
            if para_style(i).startswith("heading 2"):
                line = para_text(i)
                parts = [p.strip() for p in re.split(r"\t+|\s{2,}", line)]
                degree = parts[0] if parts else line
                year = ""
                if len(parts) > 1:
                    # try to find last 4-digit number
                    m = re.search(r"(\d{4})(?!.*\d{4})", parts[-1])
                    if m:
                        year = m.group(1)
                education.append({"degree": degree, "institution": "", "year": year})
            i += 1

    # Experience
    experience: List[Dict[str, Any]] = []
    exp_key = None
    for k in ("experience", "work experiences", "work experience"):
        if k in sections:
            exp_key = k
            break
    if exp_key:
        s = sections[exp_key]
        i = s["start"] + 1
        current: Optional[Dict[str, Any]] = None
        last_company: str = ""
        while i <= s["end"]:
            style = para_style(i)
            text = para_text(i)
            if not text:
                i += 1
                continue
            if style.startswith("heading 2"):
                # start new role
                if current:
                    experience.append(current)
                title = text
                # split by tab or multiple spaces for dates
                parts = [p.strip() for p in re.split(r"\t+|\s{2,}", text)]
                if parts:
                    title = parts[0]
                start = end = ""
                if len(parts) > 1 and "-" in parts[1]:
                    se = [p.strip() for p in parts[1].split("-")]
                    if len(se) == 2:
                        start, end = se
                current = {
                    "title": title,
                    "company": last_company,
                    "start": start,
                    "end": end,
                    "location": "",
                    "bullets": [],
                }
            else:
                # normal paragraph; treat as company line in two cases:
                # 1) before first role (current is None)
                # 2) immediately preceding a new role heading (next is Heading 2)
                next_is_h2 = (i + 1) <= s["end"] and para_style(i + 1).startswith("heading 2")
                if _looks_like_company_line(text) and (current is None or next_is_h2):
                    last_company = text.split("\t")[0].strip()
                else:
                    if current:
                        current.setdefault("bullets", []).append(text)
            i += 1
        if current:
            experience.append(current)

    return {
        "name": name,
        "headline": "",
        "email": "",
        "phone": "",
        "location": "",
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
